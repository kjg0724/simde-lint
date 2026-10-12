"""Parsing, positions and normalized text, as the grammar defines them.

Imports no `simde_lint`. It uses `tree_sitter_cpp`, which the tool also uses:
`docs/precision/grammar.md` records that as a disclosed shared dependency
rather than independence, and `parse_error` exists as an exclusion so that
part of the overlap is counted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import tree_sitter_cpp
from tree_sitter import Language, Parser

_WHITESPACE = re.compile(rb"\s+")
_PARSER = Parser(Language(tree_sitter_cpp.language()))

#: Expression wrappers the grammar's stripping reduction removes.
_WRAPPERS = ("parenthesized_expression", "cast_expression")
_CAST_OPERATORS = ("static_cast", "reinterpret_cast", "const_cast")

#: Statements that end a straight-line sequence under clause 3.
CONTROL = frozenset({
    "if_statement", "for_statement", "while_statement", "do_statement",
    "switch_statement", "labeled_statement", "for_range_loop",
})
JUMP = frozenset({"return_statement", "goto_statement", "break_statement",
                  "continue_statement", "throw_statement"})

#: Nodes whose operands the grammar treats as unevaluated (clause 5).
UNEVALUATED = frozenset({
    "sizeof_expression", "alignof_expression", "decltype", "noexcept",
    "requires_clause", "requires_expression", "static_assert_declaration",
})

#: Bodies that are their own compound statement (clause 6).
NESTED_BODY = frozenset({"lambda_expression"})


def parse(source: bytes):
    return _PARSER.parse(source)


def normalized(node, source: bytes) -> str:
    """The node's non-comment leaf tokens, in source order, joined by a space.

    The grammar's one definition of equality. It is token-based rather than
    span-based on purpose: rule W's pair test is over argument lists "equal as
    written", and a span definition would distinguish `(a, b)` from `(a,b)`
    and fail that test on formatting. Nothing else is normalized -- no case
    folding, no parenthesis removal, no reordering, nothing elided -- so `(1)`
    and `1` are not equal.

    `node` must come from parsing `source`. Passing a node parsed from some
    other buffer slices this one at the wrong offsets and returns plausible
    nonsense -- it produced `int x = /*c* 1 ;` from a mismatched pair while
    this module was being written, which looked like a comment-stripping bug
    for as long as it took to print the pieces. The bounds check below is the
    cheap half of that mistake; a node that happens to fit cannot be caught
    here.
    """
    if node.end_byte > len(source):
        raise ValueError(
            f"node ends at {node.end_byte}, source is {len(source)} bytes: "
            "the node was parsed from a different buffer"
        )
    pieces = []
    _collect_text(node, source, pieces)
    joined = b" ".join(pieces)
    return _WHITESPACE.sub(b" ", joined).strip().decode("utf-8", errors="replace")


def _collect_text(node, source: bytes, out: list[bytes]) -> None:
    if node.type == "comment":
        return
    if not node.children:
        out.append(source[node.start_byte : node.end_byte])
        return
    for child in node.children:
        _collect_text(child, source, out)


def walk(node):
    """Pre-order, children in source order -- the grammar's position key."""
    yield node
    for child in node.children:
        yield from walk(child)


@dataclass(frozen=True)
class Position:
    """The grammar's total position key: start, then end, then pre-order index."""

    start: int
    end: int
    index: int

    def __lt__(self, other: "Position") -> bool:
        return (self.start, self.end, self.index) < (other.start, other.end, other.index)


def index_preorder(root) -> dict[int, int]:
    """Pre-order index of every node, keyed by node id."""
    return {node.id: i for i, node in enumerate(walk(root))}


def strip_wrappers(node):
    """The grammar's stripping reduction: parentheses and the four cast forms.

    Returns the innermost expression after removing enclosing parentheses and
    any cast whose operand is the remainder. A call "is" an expression when
    this reduction yields exactly that call.
    """
    current = node
    while True:
        if current.type == "parenthesized_expression":
            inner = [c for c in current.named_children if c.type != "comment"]
            if len(inner) != 1:
                return current
            current = inner[0]
            continue
        if current.type == "cast_expression":
            value = current.child_by_field_name("value")
            if value is None:
                return current
            current = value
            continue
        if current.type in _CAST_OPERATORS or (
            current.type == "template_function" and current.text[:6] in (b"static", b"reinte")
        ):
            return current
        return current


def enclosing(node, types) -> object | None:
    """The nearest ancestor of one of `types`, or None."""
    current = node.parent
    while current is not None:
        if current.type in types:
            return current
        current = current.parent
    return None


def enclosing_body(node):
    """The compound statement this node is attributed to.

    A lambda body is its own compound statement, so a call inside one is
    never a sibling of a call outside it -- clause 6. The walk stops at the
    first `compound_statement`, which gives that for free, and the function
    this body belongs to is found separately.
    """
    return enclosing(node, {"compound_statement"})


def enclosing_function(node):
    """The function definition a node sits in, or None.

    A call with no enclosing function is not an anchor at all: the grammar
    puts it outside the population rather than counting it as an exclusion.
    """
    return enclosing(node, {"function_definition"})


def statement_of(node, body):
    """The direct child of `body` that contains `node`."""
    current = node
    while current is not None and current.parent is not None:
        if current.parent.id == body.id:
            return current
        current = current.parent
    return None


def has_parse_error(node) -> bool:
    """Whether an `ERROR` or `MISSING` node sits anywhere inside."""
    if node.has_error:
        return True
    return any(child.type == "ERROR" or child.is_missing for child in walk(node))
