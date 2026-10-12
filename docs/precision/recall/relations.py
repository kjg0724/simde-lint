"""Clause 2 to 7 of the grammar: when one call reaches another.

Imports no `simde_lint`. Every function here answers one clause and nothing
else, so that an exclusion reason can name the clause it came from.

The vocabulary, from `docs/precision/grammar.md`:

- a **binding** edge is a producer that is the whole right-hand side of an
  assignment or the whole initializer of a declaration, whose identifier the
  consumer names as an argument;
- a **nesting** edge is a producer written inside the consumer's argument
  list;
- a pair of participants must be **siblings** in one compound statement with
  no control statement, jump or `throw` between them, the binding must not be
  rebound or possibly rebound between them, both must sit in an evaluated
  context, and neither may be in a conditional branch the other is not.
"""

from __future__ import annotations

from dataclasses import dataclass

from syntax import (
    CONTROL,
    JUMP,
    UNEVALUATED,
    enclosing_body,
    normalized,
    statement_of,
    strip_wrappers,
    walk,
)
from tables import BY_VALUE

#: The reasons in the order the grammar's exclusion table lists them, which is
#: the precedence a record's primary reason is chosen by.
REASON_ORDER = (
    "macro_spelled",
    "macro_ambiguous",
    "unrecognized_consumer",
    "indirect_callee",
    "control_between",
    "not_siblings",
    "rebound_between",
    "passed_to_a_call_between",
    "shadowed_between",
    "unevaluated_context",
    "conditional_operand",
    "ambiguous_order",
    "parse_error",
)


def primary(reasons) -> str | None:
    """The first reason in the table's order, which is the record's primary."""
    for reason in REASON_ORDER:
        if reason in reasons:
            return reason
    return None


@dataclass(frozen=True)
class Edge:
    """One admitted producer-to-consumer edge, or the reasons it was not."""

    kind: str | None  # "binding" or "nesting", None when not admitted
    binding: str | None
    reasons: frozenset

    @property
    def admitted(self) -> bool:
        return self.kind is not None


def _declared_identifier(statement, call, source: bytes) -> str | None:
    """The binding identifier a statement establishes for `call`, if any.

    For a declaration it is the declared name; for an assignment it is the
    left-hand side only where that is a plain identifier. Any other lvalue
    establishes no binding identifier, which is what the grammar says: an
    assignment to `dd[0]` admits no binding relation for F, W or P.
    """
    for node in walk(statement):
        if node.type == "init_declarator":
            value = node.child_by_field_name("value")
            declarator = node.child_by_field_name("declarator")
            if value is None or declarator is None:
                continue
            if strip_wrappers(value).id == call.id and declarator.type == "identifier":
                return normalized(declarator, source)
        elif node.type == "assignment_expression":
            if node.child_by_field_name("operator") is not None:
                pass
            right = node.child_by_field_name("right")
            left = node.child_by_field_name("left")
            if right is None or left is None:
                continue
            if strip_wrappers(right).id == call.id and left.type == "identifier":
                return normalized(left, source)
    return None


def _names_identifier(consumer, identifier: str, source: bytes) -> bool:
    """Whether the consumer takes `identifier` as one of its arguments."""
    arguments = consumer.child_by_field_name("arguments")
    if arguments is None:
        return False
    for argument in arguments.named_children:
        if argument.type == "comment":
            continue
        if normalized(strip_wrappers(argument), source) == identifier:
            return True
    return False


def is_nested_in(producer, consumer) -> bool:
    """Whether the producer sits inside the consumer's argument list."""
    arguments = consumer.child_by_field_name("arguments")
    if arguments is None:
        return False
    return arguments.start_byte <= producer.start_byte and producer.end_byte <= arguments.end_byte


def _unevaluated(node) -> bool:
    current = node.parent
    while current is not None:
        if current.type in UNEVALUATED:
            return True
        current = current.parent
    return False


def _conditional_ancestors(node) -> set[int]:
    """Ids of conditional branches this node's evaluation depends on.

    A conditional expression's consequence and alternative, and the right
    operand of `&&` or `||`: each is evaluated only on some paths, so two
    participants in different ones do not share evaluation.
    """
    branches = set()
    current = node
    while current is not None and current.parent is not None:
        parent = current.parent
        if parent.type == "conditional_expression":
            condition = parent.child_by_field_name("condition")
            if condition is None or current.id != condition.id:
                branches.add(current.id)
        elif parent.type == "binary_expression":
            operator = parent.child_by_field_name("operator")
            right = parent.child_by_field_name("right")
            if (
                operator is not None
                and operator.text in (b"&&", b"||")
                and right is not None
                and current.id == right.id
            ):
                branches.add(current.id)
        current = parent
    return branches


def _mutates(statement, identifier: str, source: bytes) -> set[str]:
    """Reasons a statement disturbs `identifier`, by the grammar's clause 4."""
    reasons = set()
    for node in walk(statement):
        if node.type in ("assignment_expression", "update_expression"):
            target = node.child_by_field_name("left") or node.child_by_field_name("argument")
            if target is not None and normalized(target, source) == identifier:
                reasons.add("rebound_between")
        elif node.type == "unary_expression":
            operator = node.child_by_field_name("operator")
            argument = node.child_by_field_name("argument")
            if (
                operator is not None
                and operator.text == b"&"
                and argument is not None
                and normalized(argument, source) == identifier
            ):
                reasons.add("passed_to_a_call_between")
        elif node.type == "call_expression":
            arguments = node.child_by_field_name("arguments")
            if arguments is None:
                continue
            if not any(
                normalized(inner, source) == identifier
                for inner in walk(arguments)
                if inner.type == "identifier"
            ):
                continue
            # A call on the by-value allowlist cannot mutate what it is
            # handed, so it does not block the relation. Anything else does:
            # whether it mutates needs overload resolution, which this
            # grammar does not do.
            function = node.child_by_field_name("function")
            callee = normalized(function, source) if function is not None else None
            if callee not in BY_VALUE:
                reasons.add("passed_to_a_call_between")
        elif node.type in ("declaration", "init_declarator"):
            declarator = node.child_by_field_name("declarator")
            if declarator is not None and normalized(declarator, source) == identifier:
                reasons.add("shadowed_between")
    return reasons


def edge(producer, consumer, source: bytes) -> Edge:
    """Whether the producer reaches the consumer, or why it does not."""
    reasons = set()

    if _unevaluated(producer) or _unevaluated(consumer):
        reasons.add("unevaluated_context")

    producer_branches = _conditional_ancestors(producer)
    consumer_branches = _conditional_ancestors(consumer)
    if producer_branches ^ consumer_branches:
        reasons.add("conditional_operand")

    if is_nested_in(producer, consumer):
        # One statement, so clause 3 holds by construction and there is no
        # binding to rebind.
        return Edge(None, None, frozenset(reasons)) if reasons else Edge("nesting", None, frozenset())

    body = enclosing_body(producer)
    consumer_body = enclosing_body(consumer)
    if body is None or consumer_body is None or body.id != consumer_body.id:
        reasons.add("not_siblings")
        return Edge(None, None, frozenset(reasons))

    producer_statement = statement_of(producer, body)
    consumer_statement = statement_of(consumer, body)
    if producer_statement is None or consumer_statement is None:
        reasons.add("not_siblings")
        return Edge(None, None, frozenset(reasons))
    if producer_statement.id == consumer_statement.id:
        # Same statement but not nested: the producer is not an operand of the
        # consumer, so there is no edge and nothing observable blocking one.
        return Edge(None, None, frozenset(reasons))

    if consumer_statement.start_byte < producer_statement.start_byte:
        # A producer reaches a consumer, which means it comes first. Without
        # this the sibling and binding tests alone accepted an edge backwards
        # in time -- `_statements_between` normalizes the order -- and the
        # "lies between" test built on it then reported an earlier accumulate
        # as lying between a later multiply and its own add, on twelve
        # holdout relations.
        return Edge(None, None, frozenset(reasons))

    identifier = _declared_identifier(producer_statement, producer, source)
    if identifier is None or not _names_identifier(consumer, identifier, source):
        return Edge(None, None, frozenset(reasons))

    between = _statements_between(body, producer_statement, consumer_statement)
    for statement in between:
        if statement.type in CONTROL or statement.type in JUMP:
            reasons.add("control_between")
        if any(node.type in JUMP for node in walk(statement)):
            reasons.add("control_between")
        reasons |= _mutates(statement, identifier, source)

    if reasons:
        return Edge(None, identifier, frozenset(reasons))
    return Edge("binding", identifier, frozenset())


def _statements_between(body, first, second):
    children = [c for c in body.named_children if c.type != "comment"]
    try:
        start = next(i for i, c in enumerate(children) if c.id == first.id)
        stop = next(i for i, c in enumerate(children) if c.id == second.id)
    except StopIteration:
        return []
    if stop < start:
        start, stop = stop, start
    return children[start + 1 : stop]
