"""Enumerate the eligible candidates for rules F, W, M and P.

Conforms to `docs/precision/grammar.md`, which was fixed before this file
existed and before any figure from it had been seen. Imports no `simde_lint`.

What this produces is **not** a recall figure. It is the denominator: every
candidate anchor, every prospective relation, which relations the grammar
admits, which it excludes and why. Whether an admitted relation is an
instance of a mechanism is adjudicated by hand afterwards, and the grammar
says why that half cannot be automated.

    SIMDE_LINT_VVDEC=... uv run python3 docs/precision/recall/enumerate.py \\
        "$SIMDE_LINT_VVDEC/source/Lib/CommonLib/x86" --rule F
    ... --json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from relations import edge, is_nested_in, primary  # noqa: E402
from syntax import (  # noqa: E402
    CONTROL,
    JUMP,
    Position,
    enclosing_body,
    enclosing_function,
    has_parse_error,
    index_preorder,
    normalized,
    parse,
    statement_of,
    strip_wrappers,
    walk,
)
from tables import (  # noqa: E402
    BY_VALUE,
    F_ADDS,
    F_MULTIPLIES,
    F_WIDENING,
    M_INSERTS,
    M_THRESHOLD,
    P_COMPARES,
    W_CONSUMERS,
    W_PARTNER,
    W_PRODUCER,
    recognized,
)

SUFFIXES = (".h", ".hpp", ".c", ".cc", ".cpp")


@dataclass
class Record:
    """One (rule, anchor, prospective consumer) triple, per the grammar.

    Every pair the prospective search yields gets one of these. `verdict` is
    `admitted`, `excluded` or `negative`: a negative is a searched pair with
    no edge and nothing observably blocking one, which the grammar counts in
    the prospective population and not among the exclusions.
    """

    rule: str
    anchor: str
    consumer: str
    verdict: str  # "admitted", "excluded" or "negative"
    # Whether the anchor's enclosing function parses. The grammar does not
    # adjudicate an anchor in a function containing an ERROR or MISSING node,
    # so adjudication reads this to know what is in its slice.
    adjudicable: bool = True
    # Whether this anchor is the one the rule's unit attributes the finding
    # to, by the grammar's position key. For F, one add belongs to one
    # multiply; the grammar adjudicates the add first and attributes
    # afterwards, so this records which anchor *would* own it and the
    # adjudication applies that. It is not a verdict.
    owns_the_consumer: bool = True
    reason: str | None = None
    reasons: list = field(default_factory=list)
    stratum: str | None = None
    conversions: list = field(default_factory=list)


@dataclass
class Anchor:
    """A candidate anchor and what became of it."""

    rule: str
    where: str
    parse_failed: bool = False
    records: list = field(default_factory=list)
    # The grammar's position key. Carried on the anchor rather than looked up
    # by `where`, which is file and line and is shared by two calls written
    # on one line: keying by it made both of them compare equal to an add's
    # owner, so 68 relations claimed ownership of 60 adds.
    position: Position | None = None

    @property
    def admitted(self):
        return [r for r in self.records if r.verdict == "admitted"]


@dataclass
class Call:
    node: object
    name: str | None  # None when the callee is not an identifier
    position: Position
    where: str

    @property
    def direct(self) -> bool:
        return self.name is not None


def _calls(path: Path):
    """Every call expression, whether or not its callee is an identifier.

    P's slot is "the next call, whatever it is", so an indirect call has to
    be able to fill it -- discarding non-identifier callees here made
    `indirect_callee` unreachable, which is a reason the grammar defines.
    """
    source = path.read_bytes()
    root = parse(source).root_node
    index = index_preorder(root)
    found = []
    for node in walk(root):
        if node.type != "call_expression":
            continue
        function = node.child_by_field_name("function")
        name = (
            normalized(function, source)
            if function is not None and function.type == "identifier"
            else None
        )
        found.append(
            Call(
                node=node,
                name=name,
                position=Position(node.start_byte, node.end_byte, index[node.id]),
                # Line and column, not line alone: VVdeC writes
                # `vsum = _mm256_add_epi32(vsum, _mm256_add_epi32(
                # _mm256_madd_epi16(..), _mm256_madd_epi16(..)))` on one
                # line, so two anchors and two consumers shared a single
                # spelling and 99 distinct pairs collapsed into fewer
                # records -- which made one add look owned twice.
                where=f"{path}:{node.start_point[0] + 1}:{node.start_point[1] + 1}",
            )
        )
    found.sort(key=lambda c: c.position)
    return source, root, found


def _macro_definitions(source: bytes, root) -> dict:
    """Same-file `#define` names, and whether the grammar can pin the spelling.

    Returns a name to verdict map: `macro_spelled` where there is exactly one
    unconditional definition, no `#undef` of the name anywhere, and the
    replacement text contains a frozen-table name; `macro_ambiguous` where
    there are several, or one inside a conditional, or an `#undef`.
    """
    counts: dict = {}
    conditional: set = set()
    undefined: set = set()
    bodies: dict = {}
    for node in walk(root):
        if node.type in ("preproc_def", "preproc_function_def"):
            name_node = node.child_by_field_name("name")
            if name_node is None:
                continue
            name = normalized(name_node, source)
            counts[name] = counts.get(name, 0) + 1
            bodies.setdefault(name, []).append(normalized(node, source))
            ancestor = node.parent
            while ancestor is not None:
                if ancestor.type.startswith("preproc_if") or ancestor.type.startswith(
                    "preproc_ifdef"
                ):
                    conditional.add(name)
                    break
                ancestor = ancestor.parent
        elif node.type == "preproc_call":
            directive = node.child_by_field_name("directive")
            argument = node.child_by_field_name("argument")
            if directive is not None and normalized(directive, source) == "#undef":
                if argument is not None:
                    undefined.add(normalized(argument, source).strip())

    verdicts = {}
    for name, count in counts.items():
        if count > 1 or name in conditional or name in undefined:
            verdicts[name] = "macro_ambiguous"
            continue
        body = bodies[name][0]
        if any(known in body for known in BY_VALUE):
            verdicts[name] = "macro_spelled"
        # A definition whose body names no intrinsic is not a macro-spelled
        # participant and not ambiguous either: it is an unrelated macro, and
        # a call to it is `unrecognized_consumer` like any other.
    return verdicts


def _in_same_function(first, second) -> bool:
    a, b = enclosing_function(first.node), enclosing_function(second.node)
    return a is not None and b is not None and a.id == b.id


def _in_search_scope(anchor, consumer) -> bool:
    """Whether the consumer is in F's or W's prospective search population.

    The sibling requirement lives here rather than in the exclusions. Searching
    the whole enclosing function is quadratic in its size, and the first dry
    run over the holdout returned 1117 of F's 1397 prospective relations as
    `not_siblings` -- pairs of calls in different blocks of one function, with
    nothing observably stopping them, which makes them unrelated calls rather
    than blocked relations.
    """
    if not _in_same_function(anchor, consumer):
        return False
    if is_nested_in(anchor.node, consumer.node):
        return True
    body = enclosing_body(anchor.node)
    consumer_body = enclosing_body(consumer.node)
    if body is None or consumer_body is None or body.id != consumer_body.id:
        return False
    first = statement_of(anchor.node, body)
    second = statement_of(consumer.node, body)
    if first is None or second is None:
        return False
    return second.start_byte > first.start_byte


def _reaches(producer, consumer, source):
    return edge(producer.node, consumer.node, source)


def _between_conversions(anchor, add, conversions, source):
    """Every F conversion lying between anchor and add, per the grammar.

    "Lies between" is one definition for every combination: both of its edges
    are clause-2 edges. Enumerating the concrete shapes instead missed the
    mixed case, which is why this asks the edge function twice.
    """
    found = []
    for conversion in conversions:
        if not (_in_same_function(anchor, conversion) and _in_same_function(conversion, add)):
            continue
        first = _reaches(anchor, conversion, source)
        second = _reaches(conversion, add, source)
        if first.admitted and second.admitted:
            found.append(conversion)
    return found


def enumerate_f(source, calls, definitions=None) -> list[Anchor]:
    adds = [c for c in calls if c.name in F_ADDS]
    conversions = [c for c in calls if c.name in F_WIDENING]
    anchors = []
    for anchor in (c for c in calls if c.name in F_MULTIPLIES):
        record = Anchor("F", anchor.where, _parse_failed(anchor), position=anchor.position)
        for add in adds:
            if not _in_search_scope(anchor, add):
                continue
            record.records.append(_f_relation(anchor, add, conversions, source))
        anchors.append(record)
    _attribute_adds(anchors)
    return anchors


def _f_relation(anchor, add, conversions, source) -> Record:
    between = _between_conversions(anchor, add, conversions, source)
    direct = _reaches(anchor, add, source)
    reasons = set()

    if not between and direct.admitted:
        return Record("F", anchor.where, add.where, "admitted", stratum="direct")

    admitted_conversions = []
    for conversion in between:
        # No further conversion on either edge, or the path is not a
        # one-conversion path and the pair is outside rule F's contract.
        if _between_conversions(anchor, conversion, conversions, source):
            continue
        if _between_conversions(conversion, add, conversions, source):
            continue
        admitted_conversions.append(conversion.name)
    if admitted_conversions:
        return Record(
            "F",
            anchor.where,
            add.where,
            "admitted",
            stratum="one_conversion",
            conversions=sorted(set(admitted_conversions)),
        )

    reasons |= set(direct.reasons)
    if not reasons:
        # No path and nothing observable blocking one: a negative, which the
        # grammar records as no record at all.
        return Record("F", anchor.where, add.where, "negative")
    return Record("F", anchor.where, add.where, "excluded",
                  reason=primary(reasons), reasons=sorted(reasons))


def _attribute_adds(anchors) -> None:
    """Which anchor the rule's unit attributes each add to.

    `docs/mechanisms.md` makes the add the counting unit, so where several
    multiplies reach one add, one of them owns the finding. The grammar
    adjudicates the add first and attributes afterwards, so this is not a
    verdict: it records which anchor *would* own it, and the adjudication
    applies that once it has judged the add. An earlier version wrote
    `superseded_by_earlier_anchor` as a verdict here, which attributed before
    adjudicating and left undefined the case of an earliest anchor judged a
    non-instance.

    Ordering is the grammar's position key -- start byte, end byte, pre-order
    index. An earlier version compared the `file:line` strings, which orders
    `file:100` before `file:99`.
    """
    owners: dict[str, Position] = {}
    for anchor in anchors:
        for record in anchor.admitted:
            current = owners.get(record.consumer)
            if current is None or anchor.position < current:
                owners[record.consumer] = anchor.position
    for anchor in anchors:
        for record in anchor.admitted:
            record.owns_the_consumer = owners[record.consumer] == anchor.position


def enumerate_w(source, calls, definitions=None) -> list[Anchor]:
    partners = [c for c in calls if c.name == W_PARTNER]
    unpacks = [c for c in calls if c.name in W_CONSUMERS]
    anchors = []
    for anchor in (c for c in calls if c.name == W_PRODUCER):
        record = Anchor("W", anchor.where, _parse_failed(anchor), position=anchor.position)
        anchor_args = _argument_text(anchor, source)
        for unpack in unpacks:
            if not _in_search_scope(anchor, unpack):
                continue
            record.records.append(
                _w_relation(anchor, anchor_args, unpack, partners, source)
            )
        anchors.append(record)
    return anchors


def _argument_text(call, source) -> str:
    arguments = call.node.child_by_field_name("arguments")
    return normalized(arguments, source) if arguments is not None else ""


def _w_relation(anchor, anchor_args, unpack, partners, source) -> Record:
    reasons = set()
    low = _reaches(anchor, unpack, source)
    reasons |= set(low.reasons)
    for partner in partners:
        # The partner stands in the same relation to the consuming unpack
        # that the anchor does. A `mulhi` in another block is not this pair's
        # partner but an unrelated call, and collecting its reasons put
        # `not_siblings` at the head of 17 holdout records whose real reason
        # was something else. An earlier version accepted a partner that
        # failed this test as long as the anchor reached the partner, which
        # let the same misleading reason back in.
        if not _in_search_scope(partner, unpack):
            continue
        if _argument_text(partner, source) != anchor_args:
            continue
        high = _reaches(partner, unpack, source)
        if low.admitted and high.admitted:
            return Record("W", anchor.where, unpack.where, "admitted")
        reasons |= set(high.reasons)
    if not reasons:
        return Record("W", anchor.where, unpack.where, "negative")
    return Record("W", anchor.where, unpack.where, "excluded",
                  reason=primary(reasons), reasons=sorted(reasons))


def enumerate_m(source, calls, definitions=None) -> list[Anchor]:
    """Runs of inserts on one lvalue, per the grammar's run construction."""
    inserts = [c for c in calls if c.name in M_INSERTS]
    claimed: set[int] = set()
    anchors = []
    for anchor in inserts:
        if anchor.node.id in claimed:
            continue
        lvalue = _assigned_lvalue(anchor, source)
        if lvalue is None:
            continue
        run, blocked = _build_run(anchor, lvalue, inserts, source)
        for call in run:
            claimed.add(call.node.id)
        record = Anchor("M", anchor.where, _parse_failed(anchor), position=anchor.position)
        if len(run) >= M_THRESHOLD:
            record.records.append(
                Record("M", anchor.where, run[-1].where, "admitted")
            )
        if blocked is not None:
            call, reasons = blocked
            record.records.append(
                Record("M", anchor.where, call.where, "excluded",
                       reason=primary(reasons), reasons=sorted(reasons))
            )
        anchors.append(record)
    return anchors


def _assigned_lvalue(call, source) -> str | None:
    """The lvalue an insert is assigned to, per the grammar's M anchor rule.

    Assignments only. A declaration initializer is not an M anchor: the
    grammar says a run-initial insert is "the right-hand side of an
    assignment", and `v = _mm_insert_epi16(v, ...)` is the shape, since the
    first argument has to be the same lvalue. An earlier version accepted
    initializers too, which admitted anchors the grammar does not define.
    """
    body = enclosing_body(call.node)
    if body is None:
        return None
    statement = statement_of(call.node, body)
    if statement is None:
        return None
    for node in walk(statement):
        if node.type != "assignment_expression":
            continue
        right = node.child_by_field_name("right")
        left = node.child_by_field_name("left")
        if right is not None and left is not None and strip_wrappers(right).id == call.node.id:
            return normalized(left, source)
    return None


def _first_argument(call, source) -> str | None:
    arguments = call.node.child_by_field_name("arguments")
    if arguments is None:
        return None
    named = [c for c in arguments.named_children if c.type != "comment"]
    return normalized(strip_wrappers(named[0]), source) if named else None


def _build_run(anchor, lvalue, inserts, source):
    """The run over `lvalue`, and the first blocked extension if there is one.

    A run spans intervening assignments to other targets -- the contract says
    an insert on another target does not end a chain. It ends at the compound
    statement closing, at a control statement or jump, or at `lvalue` being
    assigned by something that is not an insert.
    """
    body = enclosing_body(anchor.node)
    if body is None:
        return [anchor], None
    children = [c for c in body.named_children if c.type != "comment"]
    anchor_statement = statement_of(anchor.node, body)
    if anchor_statement is None:
        return [anchor], None
    start = next((i for i, c in enumerate(children) if c.id == anchor_statement.id), None)
    if start is None:
        return [anchor], None

    # Node identity is `.id`, never `is`: tree-sitter hands out a fresh Python
    # wrapper on every access, so `enclosing_body(x) is body` was false for
    # every call and no run ever extended past its first insert.
    by_statement = {}
    for call in inserts:
        call_body = enclosing_body(call.node)
        if call_body is None or call_body.id != body.id:
            continue
        statement = statement_of(call.node, body)
        if statement is not None:
            by_statement.setdefault(statement.id, []).append(call)

    run = [anchor]
    for child in children[start + 1 :]:
        if child.type in CONTROL or child.type in JUMP or any(
            node.type in JUMP for node in walk(child)
        ):
            following = _next_insert_on(lvalue, children, children.index(child), by_statement, source)
            if following is not None:
                return run, (following, {"control_between"})
            return run, None
        candidates = by_statement.get(child.id, [])
        extension = next(
            (
                c for c in candidates
                # The grammar requires both: assigned to the run's lvalue,
                # and taking that same lvalue as its first argument. An
                # earlier version checked only the assignment, which would
                # have joined `v = _mm_insert_epi16(w, ...)` to a run over
                # `v` -- a different vector being built, not a continuation.
                if _assigned_lvalue(c, source) == lvalue
                and _first_argument(c, source) == lvalue
            ),
            None,
        )
        if extension is not None:
            blocking = edge(run[-1].node, extension.node, source)
            if not blocking.admitted and blocking.reasons:
                # Clauses 4 to 7, applied through the same relation function
                # the other rules use rather than through a partial copy of
                # it: the earlier version checked control statements and
                # reassignment by hand and never applied shadowing,
                # intervening calls, address-taking, unevaluated contexts or
                # conditional operands at all.
                return run, (extension, set(blocking.reasons))
            run.append(extension)
            continue
        if _assigns_lvalue_without_insert(child, lvalue, source):
            following = _next_insert_on(lvalue, children, children.index(child), by_statement, source)
            if following is not None:
                return run, (following, {"rebound_between"})
            return run, None
    return run, None


def _assigns_lvalue_without_insert(statement, lvalue, source) -> bool:
    for node in walk(statement):
        if node.type != "assignment_expression":
            continue
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if left is None or normalized(left, source) != lvalue:
            continue
        if right is None:
            return True
        reduced = strip_wrappers(right)
        if reduced.type != "call_expression":
            return True
        function = reduced.child_by_field_name("function")
        if function is None or normalized(function, source) not in M_INSERTS:
            return True
    return False


def _next_insert_on(lvalue, children, after, by_statement, source):
    for child in children[after:]:
        for call in by_statement.get(child.id, []):
            if _assigned_lvalue(call, source) == lvalue:
                return call
    return None


def enumerate_p(source, calls, definitions=None) -> list[Anchor]:
    anchors = []
    for index, anchor in enumerate(calls):
        if anchor.name not in P_COMPARES:
            continue
        record = Anchor("P", anchor.where, _parse_failed(anchor), position=anchor.position)
        following = _next_call_in_function(calls, index, anchor)
        if following is None:
            anchors.append(record)
            continue
        if following.position.start == anchor.position.start:
            record.records.append(
                Record("P", anchor.where, following.where, "excluded",
                       reason="ambiguous_order", reasons=["ambiguous_order"])
            )
            anchors.append(record)
            continue
        if not recognized(following.name):
            record.records.append(
                Record("P", anchor.where, following.where, "excluded",
                       reason="unrecognized_consumer", reasons=["unrecognized_consumer"])
            )
            anchors.append(record)
            continue
        relation = _reaches(anchor, following, source)
        if relation.admitted:
            record.records.append(Record("P", anchor.where, following.where, "admitted"))
        elif relation.reasons:
            record.records.append(
                Record("P", anchor.where, following.where, "excluded",
                       reason=primary(set(relation.reasons)),
                       reasons=sorted(relation.reasons))
            )
        else:
            record.records.append(Record("P", anchor.where, following.where, "negative"))
        anchors.append(record)
    return anchors


def _next_call_in_function(calls, index, anchor):
    function = enclosing_function(anchor.node)
    if function is None:
        return None
    for candidate in calls[index + 1 :]:
        other = enclosing_function(candidate.node)
        if other is not None and other.id == function.id:
            return candidate
    return None


def _parse_failed(call) -> bool:
    function = enclosing_function(call.node)
    return function is not None and has_parse_error(function)


ENUMERATORS = {
    "F": enumerate_f,
    "W": enumerate_w,
    "M": enumerate_m,
    "P": enumerate_p,
}


def over(roots, rules):
    anchors = {rule: [] for rule in rules}
    for directory in roots:
        for path in sorted(Path(directory).rglob("*")):
            if path.suffix not in SUFFIXES or not path.is_file():
                continue
            source, root, calls = _calls(path)
            calls = [c for c in calls if enclosing_function(c.node) is not None]
            definitions = _macro_definitions(source, root)
            for rule in rules:
                found = ENUMERATORS[rule](source, calls, definitions)
                _apply_parse_error(found)
                anchors[rule].extend(found)
    return anchors


def _apply_parse_error(found) -> None:
    """`parse_error` joins every prospective relation of a failing anchor.

    The grammar makes it an exclusion with one record per triple, and it sits
    last in the precedence order, so a relation blocked for another reason
    keeps that reason as its primary and carries this one alongside. An
    admitted relation in such a function becomes excluded: the grammar does
    not adjudicate an anchor whose function the parser could not read, and
    counting the relation as admitted would have published it as part of a
    slice it is not in.
    """
    for anchor in found:
        if not anchor.parse_failed:
            continue
        for record in anchor.records:
            reasons = set(record.reasons) | {"parse_error"}
            record.reasons = sorted(reasons)
            record.reason = primary(reasons)
            record.verdict = "excluded"
            record.stratum = None


def summarize(anchors):
    out = {}
    for rule, found in anchors.items():
        # Every pair the search yielded is a prospective relation, which is
        # what the grammar says. An earlier version dropped the negatives
        # from the totals, so the printed prospective count was exactly
        # admitted plus excluded and was not the denominator the text
        # declares.
        every = [r for a in found for r in a.records]
        out[rule] = {
            "candidate_anchors": len(found),
            "parse_failure_anchors": sum(1 for a in found if a.parse_failed),
            # Per anchor, not per corpus: the first version asked `if real`,
            # which is the whole corpus's list and truthy for every anchor,
            # and reported more anchors with a relation than there were
            # relations.
            "anchors_with_a_prospective_relation": sum(1 for a in found if a.records),
            "prospective_relations": len(every),
            "admitted": sum(1 for r in every if r.verdict == "admitted"),
            "not_attributed_to_this_anchor": sum(
                1 for r in every if r.verdict == "admitted" and not r.owns_the_consumer
            ),
            "excluded": sum(1 for r in every if r.verdict == "excluded"),
            "negatives": sum(1 for r in every if r.verdict == "negative"),
            "adjudicable_anchors": sum(1 for a in found if not a.parse_failed),
            "adjudicable_anchors_with_a_relation": sum(
                1 for a in found if not a.parse_failed and a.records
            ),
            "admitted_on_adjudicable_anchors": sum(
                1 for a in found if not a.parse_failed
                for r in a.records if r.verdict == "admitted"
            ),
            "strata": dict(
                Counter(r.stratum for r in every if r.verdict == "admitted" and r.stratum)
            ),
            "exclusions_by_reason": dict(
                Counter(r.reason for r in every if r.verdict == "excluded")
            ),
        }
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", nargs="+")
    parser.add_argument("--rule", action="append", choices=sorted(ENUMERATORS))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--records", action="store_true",
                        help="print every record, which is what adjudication reads")
    args = parser.parse_args()

    rules = args.rule or sorted(ENUMERATORS)
    anchors = over(args.roots, rules)
    summary = summarize(anchors)

    if args.records:
        rows = []
        for rule in rules:
            for anchor in anchors[rule]:
                for record in anchor.records:
                    if record.verdict == "negative":
                        continue
                    record.adjudicable = not anchor.parse_failed
                    rows.append(asdict(record))
        print(json.dumps(rows, indent=2))
        return 0
    if args.json:
        print(json.dumps(summary, indent=2))
        return 0
    for rule, counts in summary.items():
        print(f"rule {rule}")
        for key, value in counts.items():
            print(f"  {key:38} {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
