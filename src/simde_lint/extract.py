"""Lower a tree-sitter CST into the IR.

This module and parser.py are the only places that touch the tree-sitter Node
API. Replacing the parser backend means rewriting this module; the IR is the
stable contract for everything downstream.
"""

from __future__ import annotations

import re
from typing import Iterator

from tree_sitter import Node

from .ir import AnalysisUnit, Definition, FunctionUnit, IntrinsicCall, MacroUnit, ValueKind, ValueRef
from .knowledge import Knowledge
from .macros import ReparsedMacro, _is_intrinsic, build_alias_map, line_column, original_byte, reparse_macros
from .parser import iter_nodes, node_text, parse_source
from .symbols import parse_int_literal

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _first_identifier(text: str) -> str | None:
    match = _IDENTIFIER.search(text)
    return match.group(0) if match else None


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


def _enclosing_result_var(call: Node, source: bytes) -> str | None:
    """Variable this call's result is bound to, when the binding is direct.

    A call nested in another call's argument list binds nothing of its own:
    its value flows into the enclosing call, not into that statement's target.
    Walking past an intervening call_expression would attribute the outer
    assignment to the inner call and record a second, wrong definition on the
    same line — and `definition_before` would then name the inner call as the
    producer.
    """
    parent = call.parent
    while parent is not None:
        if parent.type == "call_expression":
            return None
        if parent.type in ("init_declarator", "assignment_expression"):
            field = "declarator" if parent.type == "init_declarator" else "left"
            return _first_identifier(node_text(parent.child_by_field_name(field), source))
        if parent.type == "function_definition":
            return None
        parent = parent.parent
    return None


def _binding_end_byte(call: Node) -> int:
    """End of the initializer or assignment that binds this call's result.

    The value exists only after the whole right-hand side has been evaluated,
    so this is what `available_after_byte` records.
    """
    parent = call.parent
    while parent is not None:
        if parent.type in ("init_declarator", "assignment_expression"):
            return parent.end_byte
        if parent.type in ("call_expression", "function_definition"):
            break
        parent = parent.parent
    return call.end_byte


def _iter_function_definitions(root: Node) -> Iterator[Node]:
    yield from iter_nodes(root, "function_definition")


def _unwrap_cast(node: Node) -> Node:
    """Strip a leading cast so its inner expression can be classified.

    `(__m128i)_mm_setr_epi8(...)` is a `cast_expression` at the top level, not
    a `call_expression`; without unwrapping it, `_record_plain_assignments`
    fails to recognize the call underneath and treats the whole cast as an
    opaque right-hand side.
    """
    while node is not None and node.type == "cast_expression":
        value = node.child_by_field_name("value")
        if value is None:
            break
        node = value
    return node


def _call_is_recognized_intrinsic(
    node: Node, source: bytes, aliases: dict[str, str], knowledge: Knowledge
) -> bool:
    raw_name = node_text(node.child_by_field_name("function"), source)
    resolved = knowledge.normalize(aliases.get(raw_name, raw_name))
    return _is_intrinsic(resolved)


def extract_units(path: str, source: bytes, knowledge: Knowledge) -> list[AnalysisUnit]:
    root = parse_source(source).root_node
    macros = reparse_macros(root, source)
    aliases = build_alias_map(macros, knowledge)

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

        call_nodes = [c for c in iter_nodes(definition, "call_expression")]
        call_nodes.sort(key=lambda n: n.start_byte)
        call_ids = {node.start_byte: index for index, node in enumerate(call_nodes)}

        for node in call_nodes:
            raw_name = node_text(node.child_by_field_name("function"), source)
            resolved = knowledge.normalize(aliases.get(raw_name, raw_name))
            if not _is_intrinsic(resolved):
                continue
            arguments = node.child_by_field_name("arguments")
            args = tuple(
                _value_ref(child, source, call_ids)
                for child in (arguments.named_children if arguments else [])
            )
            result_var = _enclosing_result_var(node, source)
            call = IntrinsicCall(
                id=call_ids[node.start_byte],
                name=resolved,
                raw_name=raw_name,
                args=args,
                line=node.start_point[0] + 1,
                column=node.start_point[1] + 1,
                start_byte=node.start_byte,
                result_var=result_var,
            )
            unit.calls.append(call)
            if result_var:
                # A variable assigned a byte literal constructor is a local
                # constant, and rules should see its lanes rather than an
                # opaque call result: `const __m128i m = _mm_setr_epi8(...)`
                # is as knowable as the same literal written inline.
                lanes = _literal_lanes(node, source) if resolved.startswith(_SET_PREFIXES) else None
                # `call_id` is carried either way. Rules F, W and M reach a
                # definition's producing call through it, and knowing the lanes
                # must not cost them that link.
                value = ValueRef(
                    ValueKind.LITERAL_VECTOR if lanes is not None else ValueKind.CALL_RESULT,
                    raw_name,
                    lanes=lanes,
                    call_id=call.id,
                )
                unit.add_definition(
                    Definition(
                        result_var,
                        call.line,
                        start_byte=call.start_byte,
                        available_after_byte=_binding_end_byte(node),
                        value=value,
                    )
                )
        _record_plain_assignments(definition, source, unit, aliases, knowledge)
        units.append(unit)

    for macro in macros:
        if not macro.ok:
            continue
        if macro.name in aliases:
            # A confirmed forwarding alias's use sites are already covered by
            # normalization (its callee resolves to the intrinsic it forwards
            # to). Building a unit for it too would report the same call
            # twice: once as the alias's normalized use, once as a call
            # inside the macro body.
            continue
        unit = _extract_macro_unit(macro, source, path, aliases, knowledge)
        if unit is not None:
            units.append(unit)
    return units


def _extract_macro_unit(
    macro: ReparsedMacro,
    source: bytes,
    path: str,
    aliases: dict[str, str],
    knowledge: Knowledge,
) -> MacroUnit | None:
    """Build a `MacroUnit` from one reparsed macro body.

    Mirrors the function-unit call loop above, over the macro's synthetic
    parse tree instead of the file's own. Every position on a resulting call
    or definition is mapped back to the original file through `original_byte`
    and `line_column` before it is stored — nothing here is read from the
    synthetic wrapper's own coordinates, so a finding never points into text
    that does not exist in the file. Returns None when no call in the body
    normalizes to a recognized intrinsic; a unit built from a body that
    contains none would have nothing for a rule to match.
    """
    call_nodes = [c for c in iter_nodes(macro.root, "call_expression")]
    call_nodes.sort(key=lambda n: n.start_byte)
    call_ids = {node.start_byte: index for index, node in enumerate(call_nodes)}

    calls: list[IntrinsicCall] = []
    definitions: list[Definition] = []
    for node in call_nodes:
        raw_name = node_text(node.child_by_field_name("function"), macro.source)
        resolved = knowledge.normalize(aliases.get(raw_name, raw_name))
        if not _is_intrinsic(resolved):
            continue
        arguments = node.child_by_field_name("arguments")
        args = tuple(
            _value_ref(child, macro.source, call_ids)
            for child in (arguments.named_children if arguments else [])
        )
        result_var = _enclosing_result_var(node, macro.source)
        start_byte = original_byte(macro, node.start_byte)
        line, column = line_column(source, start_byte)
        call = IntrinsicCall(
            id=call_ids[node.start_byte],
            name=resolved,
            raw_name=raw_name,
            args=args,
            line=line,
            column=column,
            start_byte=start_byte,
            result_var=result_var,
        )
        calls.append(call)
        if result_var:
            lanes = _literal_lanes(node, macro.source) if resolved.startswith(_SET_PREFIXES) else None
            value = ValueRef(
                ValueKind.LITERAL_VECTOR if lanes is not None else ValueKind.CALL_RESULT,
                raw_name,
                lanes=lanes,
                call_id=call.id,
            )
            definitions.append(
                Definition(
                    result_var,
                    line,
                    start_byte=start_byte,
                    available_after_byte=original_byte(macro, _binding_end_byte(node)),
                    value=value,
                )
            )

    if not calls:
        return None

    unit = MacroUnit(name=macro.name, file=path, macro_name=macro.name)
    unit.calls = calls
    for definition in definitions:
        unit.add_definition(definition)
    _record_macro_plain_assignments(macro, source, unit, aliases, knowledge)
    return unit


def _record_plain_assignments(
    scope: Node, source: bytes, unit: FunctionUnit, aliases: dict[str, str], knowledge: Knowledge
) -> None:
    """Record assignments whose right side is not a recognized intrinsic call.

    Recording only call results would leave `mask = other;` invisible, and a
    rule asking `redefined_between` would then believe a value survived when it
    had been overwritten. The replacement value is unknown to us, which is
    exactly what callers need to know.

    A right-hand side that *is* a recognized intrinsic call (optionally
    wrapped in a cast) is skipped here: the intrinsic-call loop above already
    recorded it, with its actual kind (literal vector or call result) rather
    than UNKNOWN. Recording it again here would double-count the definition.
    A call to something that is not a recognized intrinsic — `helper_load(c)`,
    cast-wrapped or not — falls through and is recorded as UNKNOWN, because
    today's only alternative is to not record it at all, which is the bug
    this function exists to avoid for non-call right-hand sides.
    """
    for node in iter_nodes(scope, "assignment_expression"):
        right = node.child_by_field_name("right")
        if right is None:
            continue
        unwrapped = _unwrap_cast(right)
        if unwrapped.type == "call_expression" and _call_is_recognized_intrinsic(
            unwrapped, source, aliases, knowledge
        ):
            continue
        name = _first_identifier(node_text(node.child_by_field_name("left"), source))
        if name:
            unit.add_definition(
                Definition(
                    name,
                    node.start_point[0] + 1,
                    start_byte=node.start_byte,
                    available_after_byte=node.end_byte,
                    value=ValueRef(ValueKind.UNKNOWN, node_text(right, source).strip()),
                )
            )
    for node in iter_nodes(scope, "init_declarator"):
        value = node.child_by_field_name("value")
        if value is None or value.type == "initializer_list":
            continue
        unwrapped = _unwrap_cast(value)
        if unwrapped.type == "call_expression" and _call_is_recognized_intrinsic(
            unwrapped, source, aliases, knowledge
        ):
            continue
        name = _first_identifier(node_text(node.child_by_field_name("declarator"), source))
        if name:
            unit.add_definition(
                Definition(
                    name,
                    node.start_point[0] + 1,
                    start_byte=node.start_byte,
                    available_after_byte=node.end_byte,
                    value=ValueRef(ValueKind.UNKNOWN, node_text(value, source).strip()),
                )
            )


def _record_macro_plain_assignments(
    macro: ReparsedMacro,
    source: bytes,
    unit: MacroUnit,
    aliases: dict[str, str],
    knowledge: Knowledge,
) -> None:
    """Macro-body counterpart of `_record_plain_assignments`.

    Same rationale — an overwrite with a non-intrinsic or non-call right-hand
    side must still be visible to `redefined_between`, or a value would look
    like it survived when it had been overwritten. Every position here comes
    from the macro's synthetic parse tree, so it is mapped back to the
    original file through `original_byte`/`line_column` before being stored,
    exactly as `_extract_macro_unit` does for calls.
    """
    for node in iter_nodes(macro.root, "assignment_expression"):
        right = node.child_by_field_name("right")
        if right is None:
            continue
        unwrapped = _unwrap_cast(right)
        if unwrapped.type == "call_expression" and _call_is_recognized_intrinsic(
            unwrapped, macro.source, aliases, knowledge
        ):
            continue
        name = _first_identifier(node_text(node.child_by_field_name("left"), macro.source))
        if name:
            start_byte = original_byte(macro, node.start_byte)
            line, _ = line_column(source, start_byte)
            unit.add_definition(
                Definition(
                    name,
                    line,
                    start_byte=start_byte,
                    available_after_byte=original_byte(macro, node.end_byte),
                    value=ValueRef(ValueKind.UNKNOWN, node_text(right, macro.source).strip()),
                )
            )
    for node in iter_nodes(macro.root, "init_declarator"):
        value = node.child_by_field_name("value")
        if value is None or value.type == "initializer_list":
            continue
        unwrapped = _unwrap_cast(value)
        if unwrapped.type == "call_expression" and _call_is_recognized_intrinsic(
            unwrapped, macro.source, aliases, knowledge
        ):
            continue
        name = _first_identifier(node_text(node.child_by_field_name("declarator"), macro.source))
        if name:
            start_byte = original_byte(macro, node.start_byte)
            line, _ = line_column(source, start_byte)
            unit.add_definition(
                Definition(
                    name,
                    line,
                    start_byte=start_byte,
                    available_after_byte=original_byte(macro, node.end_byte),
                    value=ValueRef(ValueKind.UNKNOWN, node_text(value, macro.source).strip()),
                )
            )
