"""Lower a tree-sitter CST into the IR.

This module and parser.py are the only places that touch the tree-sitter Node
API. Replacing the parser backend means rewriting this module; the IR is the
stable contract for everything downstream.
"""

from __future__ import annotations

import re
from typing import Iterator

from tree_sitter import Node

from .ir import Definition, FunctionUnit, IntrinsicCall, ValueKind, ValueRef
from .knowledge import Knowledge
from .parser import iter_nodes, node_text, parse_source
from .symbols import parse_int_literal

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_INTRINSIC_PREFIXES = ("_mm_", "_mm256_", "_mm512_")


def _is_intrinsic(name: str) -> bool:
    return name.startswith(_INTRINSIC_PREFIXES)


def _file_macro_aliases(root: Node, source: bytes) -> dict[str, str]:
    """Map function-like #define wrappers onto the intrinsic they forward to.

    VVenC declares `#define _my_cmpgt_epi64(a, b) simde_mm_cmpgt_epi64(a, b)`;
    without this the call site would be invisible to every rule.
    """
    aliases: dict[str, str] = {}
    for define in iter_nodes(root, "preproc_function_def"):
        name = node_text(define.child_by_field_name("name"), source)
        body = node_text(define.child_by_field_name("value"), source)
        match = _IDENTIFIER.search(body)
        if name and match:
            aliases[name] = match.group(0)
    return aliases


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


def _iter_function_definitions(root: Node) -> Iterator[Node]:
    yield from iter_nodes(root, "function_definition")


def extract_units(path: str, source: bytes, knowledge: Knowledge) -> list[FunctionUnit]:
    root = parse_source(source).root_node
    aliases = _file_macro_aliases(root, source)

    units: list[FunctionUnit] = []
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
                result_var=result_var,
            )
            unit.calls.append(call)
            if result_var:
                unit.add_definition(
                    Definition(
                        result_var,
                        call.line,
                        ValueRef(ValueKind.CALL_RESULT, raw_name, call_id=call.id),
                    )
                )
        units.append(unit)
    return units
