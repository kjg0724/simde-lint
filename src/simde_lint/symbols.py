"""Project-wide index of named constant arrays.

Shuffle masks are frequently declared in one file, defined in a second behind
a declaration macro, and used in a third. A single pre-pass over every input
file collects those definitions so value resolution can reach them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from tree_sitter import Node

from .knowledge import Knowledge
from .parser import iter_nodes, node_text, parse_source

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass(frozen=True)
class ConstantArray:
    name: str
    defined_at: str
    rows: tuple[tuple[int, ...], ...]


@dataclass
class SymbolIndex:
    _arrays: dict[str, ConstantArray] = field(default_factory=dict)
    _ambiguous: set[str] = field(default_factory=set)

    def add(self, array: ConstantArray) -> None:
        """Record a definition, refusing to resolve a contested name.

        Names collide legitimately: `static const` tables have internal
        linkage, so two unrelated files may define different tables under one
        name. This index is flat and file-unaware, so it cannot tell a rule
        which definition applies at a given use site. Handing back the wrong
        file's table would be the same false-confidence failure as recording a
        partially-known one, so a collision with different contents marks the
        name ambiguous and `lookup` stops resolving it. Identical repeat
        definitions are not a collision — the answer is the same either way.
        """
        existing = self._arrays.get(array.name)
        if existing is None:
            self._arrays[array.name] = array
        elif existing.rows != array.rows:
            self._ambiguous.add(array.name)

    def lookup(self, name: str) -> ConstantArray | None:
        if name in self._ambiguous:
            return None
        return self._arrays.get(name)

    def __len__(self) -> int:
        return len(self._arrays)


def parse_int_literal(text: str) -> int | None:
    """Parse a C integer literal. Public because extract.py needs it too."""
    text = text.strip().rstrip("uUlL")
    if not text:
        return None
    try:
        return int(text, 0)
    except ValueError:
        return None


def _rows_from_initializer(node: Node, source: bytes) -> tuple[tuple[int, ...], ...] | None:
    """Read an initializer_list as one or more rows of integers.

    Returns None when any element is not an integer literal, which keeps
    partially-known tables out of the index rather than reporting them as known.
    """
    inner = [c for c in node.named_children if c.type == "initializer_list"]
    if inner:
        rows = []
        for child in inner:
            row = _rows_from_initializer(child, source)
            if row is None or len(row) != 1:
                return None
            rows.append(row[0])
        return tuple(rows)

    values = []
    for child in node.named_children:
        value = parse_int_literal(node_text(child, source))
        if value is None:
            return None
        values.append(value)
    return (tuple(values),) if values else None


def _declarator_name(text: str) -> str | None:
    match = _IDENTIFIER.search(text)
    return match.group(0) if match else None


def _collect_plain_declarations(root: Node, source: bytes, path: str, index: SymbolIndex) -> None:
    for decl in iter_nodes(root, "declaration"):
        for child in decl.named_children:
            if child.type != "init_declarator":
                continue
            value = child.child_by_field_name("value")
            if value is None or value.type != "initializer_list":
                continue
            name = _declarator_name(node_text(child.child_by_field_name("declarator"), source))
            rows = _rows_from_initializer(value, source)
            if name and rows:
                index.add(ConstantArray(name, f"{path}:{decl.start_point[0] + 1}", rows))


def _collect_wrapper_macro_declarations(
    root: Node, source: bytes, path: str, index: SymbolIndex, knowledge: Knowledge
) -> None:
    """Reinterpret registered macro calls as declarations.

    Only names listed in knowledge/wrapper_macros.yaml are treated this way.
    """
    for assignment in iter_nodes(root, "assignment_expression"):
        left = assignment.child_by_field_name("left")
        right = assignment.child_by_field_name("right")
        if left is None or right is None or left.type != "call_expression":
            continue
        if right.type != "initializer_list":
            continue
        macro = node_text(left.child_by_field_name("function"), source)
        arg_index = knowledge.wrapper_macros.get(macro)
        if arg_index is None:
            continue
        arguments = left.child_by_field_name("arguments")
        if arguments is None:
            continue
        args = [a for a in arguments.named_children]
        if arg_index >= len(args):
            continue
        name = _declarator_name(node_text(args[arg_index], source))
        rows = _rows_from_initializer(right, source)
        if name and rows:
            index.add(ConstantArray(name, f"{path}:{left.start_point[0] + 1}", rows))


def build_symbol_index(
    files: Iterable[tuple[str, bytes]], knowledge: Knowledge
) -> SymbolIndex:
    index = SymbolIndex()
    for path, source in files:
        root = parse_source(source).root_node
        _collect_plain_declarations(root, source, path, index)
        _collect_wrapper_macro_declarations(root, source, path, index, knowledge)
    return index
