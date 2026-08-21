"""Reparse function-like macro bodies.

tree-sitter leaves a macro body as an opaque `preproc_arg` with no children,
so nothing downstream can see the calls inside it. Each body is reparsed
inside a synthetic function wrapper, and every position maps back to the
original file by one constant offset.
"""

from __future__ import annotations

from dataclasses import dataclass

from tree_sitter import Node

from .knowledge import Knowledge
from .parser import iter_nodes, node_text, parse_source

_PREFIX = b"void __simde_lint_macro_body(void){\n"
_SUFFIX = b"\n;}\n"

_INTRINSIC_PREFIXES = ("_mm_", "_mm256_", "_mm512_")


def _is_intrinsic(name: str) -> bool:
    return name.startswith(_INTRINSIC_PREFIXES)


@dataclass(frozen=True)
class ReparsedMacro:
    name: str
    params: tuple[str, ...]
    body_start_byte: int
    root: Node
    source: bytes
    ok: bool


def original_byte(macro: ReparsedMacro, parsed_byte: int) -> int:
    """Map a byte offset in the reparsed body back to the original file."""
    return macro.body_start_byte + parsed_byte - len(_PREFIX)


def line_column(source: bytes, byte: int) -> tuple[int, int]:
    """1-based line and column of a byte offset in the original source."""
    line = source.count(b"\n", 0, byte) + 1
    column = byte - (source.rfind(b"\n", 0, byte) + 1) + 1
    return line, column


def _body_range(source: bytes, value: Node) -> tuple[int, int]:
    """Source range of a macro body, following backslash continuations.

    tree-sitter's `preproc_arg` sometimes stops at the first physical line of
    a continued macro, which would hand the parser a fragment — `do {` with no
    closing brace — and fail on input that is merely truncated.
    """
    end = value.end_byte
    while source[value.start_byte:end].rstrip().endswith(b"\\"):
        newline = source.find(b"\n", end)
        if newline < 0:
            return value.start_byte, len(source)
        end = newline + 1
    return value.start_byte, end


def reparse_macros(root: Node, source: bytes) -> list[ReparsedMacro]:
    """Reparse every function-like macro body in one file.

    A body that does not parse is returned with `ok=False` and is not guessed
    at from its text; callers treat it as neither an alias nor a unit.
    """
    macros: list[ReparsedMacro] = []
    for define in iter_nodes(root, "preproc_function_def"):
        name = node_text(define.child_by_field_name("name"), source)
        value = define.child_by_field_name("value")
        if not name or value is None:
            continue
        params = tuple(
            node_text(child, source)
            for child in (define.child_by_field_name("parameters") or define).named_children
            if child.type == "identifier"
        )
        body_start, body_end = _body_range(source, value)
        body = source[body_start:body_end]
        synthetic = _PREFIX + body + _SUFFIX
        tree = parse_source(synthetic)
        macros.append(
            ReparsedMacro(
                name=name,
                params=params,
                body_start_byte=value.start_byte,
                root=tree.root_node,
                source=synthetic,
                ok=not tree.root_node.has_error,
            )
        )
    return macros


_TRANSPARENT = {"parenthesized_expression", "cast_expression"}


def _unwrap(node: Node) -> Node:
    """Strip parentheses and casts, which do not change what a body computes."""
    while node.type in _TRANSPARENT:
        inner = [c for c in node.named_children if c.type != "type_descriptor"]
        if len(inner) != 1:
            return node
        node = inner[0]
    return node


def is_forwarding_alias(macro: ReparsedMacro) -> str | None:
    """The single callee a body forwards to, or None if it does anything else.

    Only the written name is returned; resolving it through the knowledge
    tables and through other macros is `build_alias_map`'s job.
    """
    if not macro.ok:
        return None
    body = [
        child
        for child in _statements(macro.root)
        if child.type not in ("comment",)
    ]
    if len(body) != 1:
        return None
    expression = _unwrap(body[0])
    if expression.type != "call_expression":
        return None
    if len(list(iter_nodes(expression, "call_expression"))) != 1:
        return None
    callee = expression.child_by_field_name("function")
    if callee is None or callee.type != "identifier":
        return None
    return macro.source[callee.start_byte : callee.end_byte].decode()


def _statements(root: Node) -> list[Node]:
    """The reparsed body's top-level expressions, minus the synthetic tail."""
    for function in iter_nodes(root, "function_definition"):
        body = function.child_by_field_name("body")
        if body is None:
            continue
        return [
            child.named_children[0] if child.type == "expression_statement" and child.named_children else child
            for child in body.named_children
        ]
    return []


def build_alias_map(macros: list[ReparsedMacro], knowledge: Knowledge) -> dict[str, str]:
    """Resolve forwarding aliases to the intrinsic at the end of their chain.

    Pass 1 collects single-call bodies as candidates; each candidate's callee
    is then followed through the knowledge aliases and through other
    candidates. A chain that revisits a name is abandoned — a self-referential
    macro is legal C — and only chains ending at a recognized intrinsic are
    confirmed.
    """
    candidates = {}
    for macro in macros:
        callee = is_forwarding_alias(macro)
        if callee is not None:
            candidates[macro.name] = callee

    resolved: dict[str, str] = {}
    for name in candidates:
        seen = {name}
        current = candidates[name]
        while True:
            normalized = knowledge.normalize(current)
            if _is_intrinsic(normalized):
                resolved[name] = normalized
                break
            if current in seen or current not in candidates:
                break
            seen.add(current)
            current = candidates[current]
    return resolved
