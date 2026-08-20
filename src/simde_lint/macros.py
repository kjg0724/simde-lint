"""Reparse function-like macro bodies.

tree-sitter leaves a macro body as an opaque `preproc_arg` with no children,
so nothing downstream can see the calls inside it. Each body is reparsed
inside a synthetic function wrapper, and every position maps back to the
original file by one constant offset.
"""

from __future__ import annotations

from dataclasses import dataclass

from tree_sitter import Node

from .parser import iter_nodes, node_text, parse_source

_PREFIX = b"void __simde_lint_macro_body(void){\n"
_SUFFIX = b"\n;}\n"


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
        body = source[value.start_byte : value.end_byte]
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
