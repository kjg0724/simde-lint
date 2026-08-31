"""Lower a tree-sitter CST into the IR.

This module and parser.py are the only places that touch the tree-sitter Node
API. Replacing the parser backend means rewriting this module; the IR is the
stable contract for everything downstream.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterator

from tree_sitter import Node

from .ir import (
    AnalysisUnit,
    Definition,
    FunctionUnit,
    IntrinsicCall,
    MacroUnit,
    MutableAnalysisUnit,
    ValueKind,
    ValueRef,
)
from .knowledge import Knowledge
from .macros import AliasMap, ReparsedMacro, _is_intrinsic, build_alias_map, line_column, original_byte, reparse_macros
from .parser import iter_nodes, node_text, parse_source, unparsed_regions
from .symbols import parse_int_literal

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _first_identifier(text: str) -> str | None:
    match = _IDENTIFIER.search(text)
    return match.group(0) if match else None


@dataclass(frozen=True)
class Coordinates:
    """Where a node's text and position come from.

    The function-unit and macro-unit extraction paths are identical in
    every decision they make about a body -- which calls are recognized
    intrinsics, which assignments bind a value, and so on. They differ in
    exactly three things: which tree they walk (a function's own body, or a
    macro's synthetic reparse), which bytes text is read from (`source`, or
    `macro.source`), and whether a node's position is its own or has to be
    mapped back to the real file because the tree it sits in is a synthetic
    reparse. This type carries the last two, so the shared extraction code
    below is written once against `Coordinates` instead of twice against
    `source` and `macro.source` separately.

    `of_file` and `of_macro` are the intended ways to build one, and they
    are asymmetric on purpose: `of_file` returns a node's own `start_point`
    / `start_byte` untouched, `of_macro` recomputes both by mapping the
    synthetic byte through `original_byte` and re-deriving line/column with
    `line_column`. That asymmetry is not an oversight to unify further --
    the function path has never gone through `line_column`, and this class
    must not become the thing that quietly changes that.

    `_macro` and `_source` are paired: a `Coordinates` in file mode has
    neither, one in macro mode has both. `__post_init__` enforces that
    pairing on every construction, factory or not, so a half-built instance
    (macro set, source missing, or the reverse) fails immediately at
    construction instead of surfacing later as `line_column` reading a
    `None` source.
    """

    text: bytes
    _macro: ReparsedMacro | None
    _source: bytes | None

    def __post_init__(self) -> None:
        if (self._macro is None) != (self._source is None):
            raise ValueError(
                "Coordinates: _macro and _source must be given together or not at all"
            )

    @classmethod
    def of_file(cls, source: bytes) -> Coordinates:
        """Positions read straight off the node, in the file's own tree."""
        return cls(text=source, _macro=None, _source=None)

    @classmethod
    def of_macro(cls, macro: ReparsedMacro, source: bytes) -> Coordinates:
        """Positions in `macro`'s synthetic reparse, mapped back to `source`."""
        return cls(text=macro.source, _macro=macro, _source=source)

    def place(self, node: Node) -> tuple[int, int, int]:
        """1-based (line, column, start_byte) of `node` in the real file.

        For `of_file`, this is exactly `node.start_point` and
        `node.start_byte` -- see the class docstring. For `of_macro`, the
        synthetic byte is mapped through `original_byte` and the line and
        column are recomputed from the real source with `line_column`.
        """
        if self._macro is None:
            return node.start_point[0] + 1, node.start_point[1] + 1, node.start_byte
        start_byte = original_byte(self._macro, node.start_byte)
        line, column = line_column(self._source, start_byte)
        return line, column, start_byte

    def end_of(self, node: Node) -> int:
        """`node.end_byte`, mapped back to the real file the same way `place` is."""
        if self._macro is None:
            return node.end_byte
        return original_byte(self._macro, node.end_byte)


# Byte constructors only. Rule S is the sole consumer of `lanes`, and it reads
# a byte shuffle mask. Wider constructors would need per-width handling that no
# rule needs, and recording them under a byte mask would truncate their values,
# so they stay opaque instead.
_SET_PREFIXES = (
    "_mm_setr_epi8",
    "_mm_set_epi8",
    "_mm256_setr_epi8",
    "_mm256_set_epi8",
)


def _symbol_name(node: Node, source: bytes) -> str | None:
    """Name the constant a non-call argument refers to.

    `*(__m128i *)even_odd_mask_x[base_shift]` must yield `even_odd_mask_x`.
    A plain regex over the argument text would return the cast type instead,
    so the subscript base is read from the CST. Cast types are `type_identifier`
    nodes rather than `identifier`, which keeps them out of the fallback.
    """
    for subscript in iter_nodes(node, "subscript_expression"):
        base = subscript.child_by_field_name("argument")
        name = _first_identifier(node_text(base, source))
        if name:
            return name
    identifiers = [node_text(n, source) for n in iter_nodes(node, "identifier")]
    return identifiers[-1] if identifiers else None


def _value_ref(node: Node, source: bytes, call_ids: dict[int, int]) -> ValueRef:
    text = node_text(node, source).strip()
    if node.type == "call_expression":
        callee = node_text(node.child_by_field_name("function"), source)
        lanes = _literal_lanes(node, source) if callee.startswith(_SET_PREFIXES) else None
        if lanes is not None:
            return ValueRef(ValueKind.LITERAL_VECTOR, text, lanes=lanes)
        return ValueRef(ValueKind.CALL_RESULT, text, call_id=call_ids.get(node.start_byte))
    if node.type == "identifier":
        return ValueRef(ValueKind.VARIABLE, text)
    symbol = _symbol_name(node, source)
    if symbol and ("[" in text or "*" in text):
        return ValueRef(ValueKind.SYMBOL, text, symbol=symbol)
    return ValueRef(ValueKind.UNKNOWN, text)


def _literal_lanes(call: Node, source: bytes) -> tuple[int, ...] | None:
    """Lane values of a set/setr constructor, in lane order.

    `_mm_setr_*` takes lane 0 first; `_mm_set_*` takes the highest lane first.
    """
    arguments = call.child_by_field_name("arguments")
    if arguments is None:
        return None
    lanes = []
    for child in arguments.named_children:
        value = parse_int_literal(node_text(child, source))
        if value is None:
            return None
        lanes.append(value & 0xFF)
    if not lanes:
        return None
    name = node_text(call.child_by_field_name("function"), source)
    return tuple(lanes) if "setr" in name else tuple(reversed(lanes))


def _is_compound_assignment(node: Node, source: bytes) -> bool:
    """True when an `assignment_expression` node's operator is not plain `=`.

    tree-sitter renders both `x = ...` and `x += ...` as the same node type,
    `assignment_expression`; only the `operator` field's text tells them
    apart. A compound assignment's new value depends on the old value of the
    target as well as on the right-hand side, so a call on that right-hand
    side must never be treated as directly bound to the target — see
    `_enclosing_result_var`.
    """
    operator = node.child_by_field_name("operator")
    return operator is not None and node_text(operator, source) != "="


# The only nodes a call's value passes through unchanged. A C-style cast is
# transparent by existing deliberate choice; a C++ `static_cast`-shaped node
# is not, and is not named `cast_expression` in the grammar, so it never
# matches here.
#
# Walking up to a binding and unwrapping down to a right-hand side are the
# same question asked from the two ends, so both read this one tuple --
# `_enclosing_binding` to decide what it may cross, `_unwrap_transparent` to
# decide what it may strip. Letting them disagree gave a parenthesized call
# two definitions for one write: `_enclosing_binding` crossed the parentheses
# and recorded a CALL_RESULT, while the unwrapper did not strip them, failed
# to recognize the intrinsic, and recorded a competing UNKNOWN at the same
# byte. `definition_before` could then return the UNKNOWN and hide the
# producer from every rule that traces through it.
_TRANSPARENT_BINDING_WRAPPERS = ("parenthesized_expression", "cast_expression")


def _enclosing_binding(call: Node) -> Node | None:
    """`init_declarator` or `assignment_expression` this call binds directly.

    A call nested in another call's argument list binds nothing of its own:
    its value flows into the enclosing call, not into that statement's
    target. A call nested in any other value-transforming construct —
    `binary_expression`, `unary_expression`, `conditional_expression`,
    `comma_expression`, `initializer_list`, and every node type not
    anticipated here — binds nothing either: the enclosing write's value is
    no longer this call's value alone. Only `parenthesized_expression` and
    `cast_expression` preserve that identity, so only those are crossed;
    everything else — including a nested `call_expression` and
    `function_definition` — terminates the walk and yields None, exactly as
    it always has for those two.
    """
    parent = call.parent
    while parent is not None:
        if parent.type in ("init_declarator", "assignment_expression"):
            return parent
        if parent.type not in _TRANSPARENT_BINDING_WRAPPERS:
            return None
        parent = parent.parent
    return None


def _enclosing_result_var(call: Node, source: bytes) -> str | None:
    """Variable this call's result is bound to, when the binding is direct.

    See `_enclosing_binding` for what counts as direct.

    A compound assignment (`x += call(...)`) is not a direct binding either:
    `x`'s new value depends on its old value as well as on the call's result,
    so this returns None there just as it does for a nested call. The write
    itself is not lost — `_record_plain_assignments` records it as an
    `UNKNOWN` definition, since a compound assignment's right-hand side never
    reaches this function's caller as a recognized-call binding.
    """
    parent = _enclosing_binding(call)
    if parent is None:
        return None
    if parent.type == "assignment_expression" and _is_compound_assignment(parent, source):
        return None
    field = "declarator" if parent.type == "init_declarator" else "left"
    return _first_identifier(node_text(parent.child_by_field_name(field), source))


def _enclosing_result_lvalue(call: Node, source: bytes) -> str | None:
    """Assignment target as written, subscript kept, whitespace normalized.

    `_enclosing_result_var` reduces `dd[0]` to `dd` because a variable is
    what `redefined_between` tracks. A rule asking "did these writes go to
    the same place" needs the other answer, and getting `dd` there merges
    `dd[0]` and `dd[1]` into one target they are not. See `_enclosing_binding`
    for what counts as a direct binding.

    None for a compound assignment for the same reason `_enclosing_result_var`
    is: `dd[0] += call(...)` does not bind the call's result to `dd[0]`
    either.
    """
    parent = _enclosing_binding(call)
    if parent is None:
        return None
    if parent.type == "assignment_expression" and _is_compound_assignment(parent, source):
        return None
    field = "declarator" if parent.type == "init_declarator" else "left"
    target = parent.child_by_field_name(field)
    if target is None:
        return None
    return re.sub(r"\s+", "", node_text(target, source))


def _binding_end_node(call: Node) -> Node:
    """The initializer or assignment whose end binds this call's result.

    The value exists only after the whole right-hand side has been evaluated,
    so this node's end is what `available_after_byte` records --
    `Coordinates.end_of` reads it off directly.
    """
    parent = call.parent
    while parent is not None:
        if parent.type in ("init_declarator", "assignment_expression"):
            return parent
        if parent.type in ("call_expression", "function_definition"):
            break
        parent = parent.parent
    return call


def _iter_function_definitions(root: Node) -> Iterator[Node]:
    yield from iter_nodes(root, "function_definition")


def _unwrap_transparent(node: Node) -> Node:
    """Strip transparent wrappers so the inner expression can be classified.

    `(__m128i)_mm_setr_epi8(...)` is a `cast_expression` at the top level and
    `(_mm_setr_epi8(...))` a `parenthesized_expression`, neither of them a
    `call_expression`; without stripping them, `_record_plain_assignments`
    fails to recognize the call underneath and treats the whole right-hand
    side as opaque.

    The wrappers stripped here are exactly the ones `_enclosing_binding`
    crosses -- see `_TRANSPARENT_BINDING_WRAPPERS` for why the two must
    agree.
    """
    while node is not None and node.type in _TRANSPARENT_BINDING_WRAPPERS:
        if node.type == "cast_expression":
            inner = node.child_by_field_name("value")
        else:
            inner = next((c for c in node.named_children), None)
        if inner is None:
            break
        node = inner
    return node


def _call_is_recognized_intrinsic(
    node: Node, source: bytes, aliases: AliasMap, knowledge: Knowledge
) -> bool:
    raw_name = node_text(node.child_by_field_name("function"), source)
    resolved = knowledge.normalize(aliases.targets.get(raw_name, raw_name))
    return _is_intrinsic(resolved)


def extract_units(path: str, source: bytes, knowledge: Knowledge) -> list[AnalysisUnit]:
    """Units only. Callers that need to know whether the parse was clean use
    `extract_units_and_diagnostics`; this wrapper keeps the older signature
    for the many call sites that do not."""
    return extract_units_and_diagnostics(path, source, knowledge)[0]


def _extract_calls(
    scope: Node, coords: Coordinates, aliases: AliasMap, knowledge: Knowledge
) -> tuple[list[IntrinsicCall], list[Definition]]:
    """Recognized-intrinsic calls in `scope`, and the definitions they bind.

    Shared by the function-unit and macro-unit extraction paths; `coords`
    supplies the text and positions to read `scope` through -- the file's
    own tree via `Coordinates.of_file`, or a macro's synthetic reparse via
    `Coordinates.of_macro`. Every other decision (which calls are recognized
    intrinsics, which bind a variable, when a bound value's lanes are known)
    is identical either way.
    """
    call_nodes = [c for c in iter_nodes(scope, "call_expression")]
    call_nodes.sort(key=lambda n: n.start_byte)
    call_ids = {node.start_byte: index for index, node in enumerate(call_nodes)}

    calls: list[IntrinsicCall] = []
    definitions: list[Definition] = []
    for node in call_nodes:
        raw_name = node_text(node.child_by_field_name("function"), coords.text)
        resolved = knowledge.normalize(aliases.targets.get(raw_name, raw_name))
        if not _is_intrinsic(resolved):
            continue
        arguments = node.child_by_field_name("arguments")
        args = tuple(
            _value_ref(child, coords.text, call_ids)
            for child in (arguments.named_children if arguments else [])
        )
        # Two answers to two questions, deliberately kept apart. `result_var`
        # names the variable `redefined_between` tracks, so it reduces `dd[0]`
        # to `dd`; `result_lvalue` keeps the subscript, because a rule asking
        # whether writes landed in the same place needs to see that `dd[0]`
        # and `dd[1]` are different places. Widening `result_var` to the
        # lvalue would change what rules F, P and W match, so it stays narrow.
        result_var = _enclosing_result_var(node, coords.text)
        result_lvalue = _enclosing_result_lvalue(node, coords.text)
        line, column, start_byte = coords.place(node)
        call = IntrinsicCall(
            id=call_ids[node.start_byte],
            name=resolved,
            raw_name=raw_name,
            args=args,
            line=line,
            column=column,
            start_byte=start_byte,
            result_var=result_var,
            result_lvalue=result_lvalue,
            is_macro_alias=raw_name in aliases.targets,
        )
        calls.append(call)
        if result_var:
            # A variable assigned a byte literal constructor is a local
            # constant, and rules should see its lanes rather than an
            # opaque call result: `const __m128i m = _mm_setr_epi8(...)`
            # is as knowable as the same literal written inline.
            lanes = _literal_lanes(node, coords.text) if resolved.startswith(_SET_PREFIXES) else None
            # `call_id` is carried either way. Rules F, W and M reach a
            # definition's producing call through it, and knowing the lanes
            # must not cost them that link.
            value = ValueRef(
                ValueKind.LITERAL_VECTOR if lanes is not None else ValueKind.CALL_RESULT,
                raw_name,
                lanes=lanes,
                call_id=call.id,
            )
            definitions.append(
                Definition(
                    result_var,
                    call.line,
                    start_byte=call.start_byte,
                    available_after_byte=coords.end_of(_binding_end_node(node)),
                    value=value,
                )
            )
    return calls, definitions


def extract_units_and_diagnostics(
    path: str, source: bytes, knowledge: Knowledge
) -> tuple[list[AnalysisUnit], list[tuple[int, int]]]:
    """Units, plus the line spans tree-sitter could not parse.

    The two come from one parse rather than two: a sweep that reparsed every
    file to collect diagnostics would pay for them twice."""
    root = parse_source(source).root_node
    regions = unparsed_regions(root)
    macros = reparse_macros(root, source)
    aliases = build_alias_map(root, source, macros, knowledge)

    units: list[AnalysisUnit] = []
    for definition in _iter_function_definitions(root):
        declarator = definition.child_by_field_name("declarator")
        name = _first_identifier(node_text(declarator, source)) or "<anonymous>"
        unit = FunctionUnit(
            name=name,
            file=path,
            start_line=definition.start_point[0] + 1,
            end_line=definition.end_point[0] + 1,
        )

        coords = Coordinates.of_file(source)
        calls, definitions = _extract_calls(definition, coords, aliases, knowledge)
        unit.calls = calls
        for call_definition in definitions:
            unit.add_definition(call_definition)
        _record_plain_assignments(definition, coords, unit, aliases, knowledge)
        units.append(unit)

    for macro in macros:
        if not macro.ok:
            continue
        if macro.start_byte in aliases.definitions:
            # A confirmed forwarding alias's use sites are already covered by
            # normalization (its callee resolves to the intrinsic it forwards
            # to). Building a unit for it too would report the same call
            # twice: once as the alias's normalized use, once as a call
            # inside the macro body.
            #
            # Keyed by this specific definition's `start_byte` (the
            # `#define` construct's own position — see `ReparsedMacro`), not
            # by `macro.name` and not by `macro.body_start_byte`: a name can
            # have several definitions in this file (different `#if`
            # branches), and only the ones that actually agreed with each
            # other and were registered by `build_alias_map` belong to
            # `aliases.definitions` — a same-named sibling that disagreed
            # still needs its own unit built below. `start_byte` identifies
            # a definition uniquely within one file (unlike
            # `body_start_byte`, which an empty-bodied sibling definition
            # would not even have), which is the scope `aliases` is built
            # at; if that scope ever widens to span multiple files, this key
            # must be paired with a file identifier too, since byte offsets
            # alone would then collide across files.
            continue
        unit = _extract_macro_unit(macro, source, path, aliases, knowledge)
        if unit is not None:
            units.append(unit)
    return units, regions


def _extract_macro_unit(
    macro: ReparsedMacro,
    source: bytes,
    path: str,
    aliases: AliasMap,
    knowledge: Knowledge,
) -> MacroUnit | None:
    """Build a `MacroUnit` from one reparsed macro body.

    Walks the macro's synthetic parse tree through `Coordinates.of_macro`,
    which maps every resulting position back to the original file — nothing
    here is read from the synthetic wrapper's own coordinates, so a finding
    never points into text that does not exist in the file. Returns None
    when no call in the body normalizes to a recognized intrinsic; a unit
    built from a body that contains none would have nothing for a rule to
    match.
    """
    coords = Coordinates.of_macro(macro, source)
    calls, definitions = _extract_calls(macro.root, coords, aliases, knowledge)
    if not calls:
        return None

    unit = MacroUnit(name=macro.name, file=path)
    unit.calls = calls
    for definition in definitions:
        unit.add_definition(definition)
    _record_plain_assignments(macro.root, coords, unit, aliases, knowledge)
    return unit


def _record_plain_assignments(
    scope: Node, coords: Coordinates, unit: MutableAnalysisUnit, aliases: AliasMap, knowledge: Knowledge
) -> None:
    """Record assignments whose right side is not a recognized intrinsic call.

    Recording only call results would leave `mask = other;` invisible, and a
    rule asking `redefined_between` would then believe a value survived when it
    had been overwritten. The replacement value is unknown to us, which is
    exactly what callers need to know.

    A right-hand side that *is* a recognized intrinsic call (optionally
    wrapped in a cast) is skipped here only for a *plain* assignment:
    `_extract_calls` already recorded it there, with its actual kind
    (literal vector or call result) rather than UNKNOWN. Recording it again
    here would double-count the definition. A call to something that is not
    a recognized intrinsic — `helper_load(c)`, cast-wrapped or not — falls
    through and is recorded as UNKNOWN, because today's only alternative is
    to not record it at all, which is the bug this function exists to avoid
    for non-call right-hand sides.

    A *compound* assignment (`x += call(...)`) is never skipped here, even
    when its right-hand side is a recognized intrinsic call:
    `_enclosing_result_var` returns None for it, so `_extract_calls` records
    no definition for the write at all. Falling through to UNKNOWN here is
    what keeps `redefined_between` seeing the reassignment — dropping it
    would trade a wrong direct-result link for a missing definition, which is
    exactly the failure mode this function exists to avoid.

    Shared by both extraction paths through `coords` — see `Coordinates`.
    """
    for node in iter_nodes(scope, "assignment_expression"):
        right = node.child_by_field_name("right")
        if right is None:
            continue
        unwrapped = _unwrap_transparent(right)
        if (
            not _is_compound_assignment(node, coords.text)
            and unwrapped.type == "call_expression"
            and _call_is_recognized_intrinsic(unwrapped, coords.text, aliases, knowledge)
        ):
            continue
        name = _first_identifier(node_text(node.child_by_field_name("left"), coords.text))
        if name:
            line, _column, start_byte = coords.place(node)
            unit.add_definition(
                Definition(
                    name,
                    line,
                    start_byte=start_byte,
                    available_after_byte=coords.end_of(node),
                    value=ValueRef(ValueKind.UNKNOWN, node_text(right, coords.text).strip()),
                )
            )
    for node in iter_nodes(scope, "init_declarator"):
        value = node.child_by_field_name("value")
        if value is None or value.type == "initializer_list":
            continue
        unwrapped = _unwrap_transparent(value)
        if unwrapped.type == "call_expression" and _call_is_recognized_intrinsic(
            unwrapped, coords.text, aliases, knowledge
        ):
            continue
        name = _first_identifier(node_text(node.child_by_field_name("declarator"), coords.text))
        if name:
            line, _column, start_byte = coords.place(node)
            unit.add_definition(
                Definition(
                    name,
                    line,
                    start_byte=start_byte,
                    available_after_byte=coords.end_of(node),
                    value=ValueRef(ValueKind.UNKNOWN, node_text(value, coords.text).strip()),
                )
            )
