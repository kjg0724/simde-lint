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
        definitions are not a collision -- the answer is the same either way.
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

    def names(self) -> list[str]:
        """Names that resolve through lookup(), for tools that list them.

        An ambiguous name still occupies a slot in `_arrays` (the first
        definition seen, kept only so a later identical one is recognised as
        a repeat rather than a fresh collision), but `lookup` refuses to
        return it. Including it here would hand a caller a name it cannot
        then look up.
        """
        return sorted(name for name in self._arrays if name not in self._ambiguous)

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


# Element types whose storage is one byte, so an initializer value is the byte
# a shuffle reads. Anything else -- a wider type, or a typedef this does not
# resolve -- leaves the mask unresolved rather than truncated: `0x1000` in a
# `short` array is byte 0x00 at lane 0 and 0x10 at lane 1, and reading it as a
# single lane value of 0x00 called an unsafe mask safe.
_BYTE_ELEMENTS = frozenset(
    {
        "char", "signed char", "unsigned char",
        "int8_t", "uint8_t",
    }
)


def _byte_sized(decl: Node, source: bytes) -> bool:
    kind = decl.child_by_field_name("type")
    if kind is None:
        return False
    return " ".join(node_text(kind, source).split()) in _BYTE_ELEMENTS


def _is_const(decl: Node, source: bytes) -> bool:
    """Whether the declaration says the storage does not change.

    An initializer is not a value. `unsigned char mask[16] = {0}` followed by
    `mask[0] = 16` is read by a shuffle as 16, and taking the initializer for
    the runtime bytes graded that mask A with the guard dropped -- measured,
    pshufb returns lane 0 of the source where unguarded tbl returns zero.
    Writes are not tracked here, so `const` is the only claim available, and
    `volatile` withdraws it: the storage may change without a write this file
    contains.
    """
    text = node_text(decl, source)
    head = text.split("=", 1)[0]
    return "const" in head.split() and "volatile" not in head.split()


def _collect_plain_declarations(root: Node, source: bytes, path: str, index: SymbolIndex) -> None:
    for decl in iter_nodes(root, "declaration"):
        if not _is_const(decl, source) or not _byte_sized(decl, source):
            continue
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


def _wrapper_declarator(arguments: Node, arg_index: int, source: bytes) -> str | None:
    """The declarator text of a wrapper macro call, if its type is a const byte.

    `_collect_plain_declarations` can ask tree-sitter for a declaration's type
    and qualifiers. Here it cannot: a type inside an argument list does not
    parse as a type, and the resulting node shape shifts with the qualifier.
    `DECLARE_ALIGNED(16, uint8_t, m[16])` yields a number, one `ERROR` node
    covering `uint8_t,`, and the declarator; adding `const` yields a number,
    an identifier, an `ERROR`, and the declarator. So the arguments are split
    on commas instead, which is the reading `declarator_arg` in
    wrapper_macros.yaml already documents. Array dimensions are bracketed and
    the initializer is outside this node, so no argument of a registered
    wrapper contains a comma.

    The type is the argument before the declarator and has to satisfy the same
    two requirements the plain path makes: byte-sized elements, and `const`
    without `volatile`. Without the const requirement an initializer plus a
    wrapper registration was enough for grade A. Measured on
    `DECLARE_ALIGNED(16, uint8_t, m[16]) = {0..15}; m[0] = 16;` -- pshufb
    returns 42 at lane 0 where the suggested unguarded `vqtbl1q_u8` returns 0.
    """
    if arg_index < 1:
        return None
    text = node_text(arguments, source).strip()
    if not text.startswith("(") or not text.endswith(")"):
        return None
    parts = [part.strip() for part in text[1:-1].split(",")]
    if arg_index >= len(parts):
        return None
    words = parts[arg_index - 1].replace("*", " ").split()
    if "const" not in words or "volatile" in words:
        return None
    if " ".join(word for word in words if word != "const") not in _BYTE_ELEMENTS:
        return None
    return parts[arg_index]


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
        declarator = _wrapper_declarator(arguments, arg_index, source)
        if declarator is None:
            continue
        name = _declarator_name(declarator)
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
