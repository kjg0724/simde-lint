"""Project-wide index of named constant arrays.

Shuffle masks are frequently declared in one file, defined in a second behind
a declaration macro, and used in a third. A single pre-pass over every input
file collects those definitions so value resolution can reach them.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from typing import Collection, Iterable

from tree_sitter import Node

from .diagnostics import Diagnostic
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

# The individual words above, which is the granularity a `#define` works at,
# plus `const`, whose presence is what makes a declaration's initializer
# readable as its runtime bytes. `volatile` is not here: the collectors accept
# only a declaration spelled `const` and not `volatile`, and no definition of
# `volatile` adds a qualifier to such a declaration, so a definition of it can
# only cost recall.
_BYTE_WORDS = frozenset(word for spelling in _BYTE_ELEMENTS for word in spelling.split())
_SHADOWABLE = _BYTE_WORDS | {"const"}


def _shadowed_words(root: Node, source: bytes) -> set[str]:
    """Words this file redefines with `#define` that a declaration's meaning rests on.

    The collectors read the spelling as written, before preprocessing.
    `#define uint8_t uint8_t *` leaves `static const uint8_t m[16]` looking
    like an array of bytes while it declares an array of addresses, and
    `#define const` leaves the same declaration looking immutable while its
    storage is writable. Both produced grade-A evidence for bytes no rule had
    established.

    Resolving a definition rather than rejecting the spelling means
    preprocessing the translation unit, which this tool does not do. The scan
    also ignores preprocessor state and ordering, so an `#undef`, a definition
    inside an inactive `#if`, or one written after the declaration it would
    affect all reject conservatively, and a definition in a file outside the
    scan remains invisible: this closes a reachable hole, not the general
    question of what the preprocessor does to a spelling.
    """
    shadowed = set()
    for kind in ("preproc_def", "preproc_function_def"):
        for definition in iter_nodes(root, kind):
            name = node_text(definition.child_by_field_name("name"), source)
            if name in _SHADOWABLE:
                shadowed.add(name)
    return shadowed


def _byte_sized(decl: Node, source: bytes, shadowed: Collection[str]) -> bool:
    kind = decl.child_by_field_name("type")
    if kind is None:
        return False
    words = node_text(kind, source).split()
    if any(word in shadowed for word in words):
        return False
    return " ".join(words) in _BYTE_ELEMENTS


def _is_const(decl: Node, source: bytes, shadowed: Collection[str]) -> bool:
    """Whether the declaration says the storage does not change.

    An initializer is not a value. `unsigned char mask[16] = {0}` followed by
    `mask[0] = 16` is read by a shuffle as 16, and taking the initializer for
    the runtime bytes graded that mask A with the guard dropped -- measured,
    pshufb returns lane 0 of the source where unguarded tbl returns zero.
    Writes are not tracked here, so `const` is the only claim available, and
    `volatile` withdraws it: the storage may change without a write this file
    contains. A `#define` of either qualifier withdraws the claim too: the
    spelling this reads is not what the compiler sees.
    """
    if "const" in shadowed:
        return False
    text = node_text(decl, source)
    head = text.split("=", 1)[0]
    return "const" in head.split() and "volatile" not in head.split()


def _declares_a_pointer(declarator: Node) -> bool:
    """Whether the declarator puts a pointer between the type and the element.

    `_byte_sized` reads the declaration's type field, and in
    `static const unsigned char *m[16] = {0, 1, 2, 3}` that field is
    `unsigned char` while the elements are pointers. Those four values are
    four addresses, not four mask lanes, and reading them as lanes resolved a
    mask whose bytes the rule never saw. Any pointer under the declarator
    disqualifies it; whether the pointee is byte-sized is a different
    question from what the array holds.
    """
    # iter_nodes is inclusive of its argument, so a declarator that is itself
    # a pointer is caught by the same walk.
    return any(
        next(iter_nodes(declarator, kind), None) is not None
        for kind in ("pointer_declarator", "abstract_pointer_declarator")
    )


def _collect_plain_declarations(
    root: Node, source: bytes, path: str, index: SymbolIndex, shadowed: Collection[str]
) -> None:
    for decl in iter_nodes(root, "declaration"):
        if not _is_const(decl, source, shadowed) or not _byte_sized(decl, source, shadowed):
            continue
        for child in decl.named_children:
            if child.type != "init_declarator":
                continue
            value = child.child_by_field_name("value")
            if value is None or value.type != "initializer_list":
                continue
            declarator = child.child_by_field_name("declarator")
            if declarator is None or _declares_a_pointer(declarator):
                continue
            name = _declarator_name(node_text(declarator, source))
            rows = _rows_from_initializer(value, source)
            if name and rows:
                index.add(ConstantArray(name, f"{path}:{decl.start_point[0] + 1}", rows))


def _wrapper_declarator(
    arguments: Node, arg_index: int, source: bytes, shadowed: Collection[str]
) -> str | None:
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
    three requirements the plain path makes: byte-sized elements, no pointer
    between the type and the element, and `const` without `volatile`. Without
    the const requirement an initializer plus a wrapper registration was
    enough for grade A. Measured on
    `DECLARE_ALIGNED(16, uint8_t, m[16]) = {0..15}; m[0] = 16;` -- pshufb
    returns 42 at lane 0 where the suggested unguarded `vqtbl1q_u8` returns 0.

    A `*` anywhere in either argument rejects the declaration rather than
    being read past: `DECLARE_ALIGNED(16, const uint8_t *, m[16]) = {0, 1, 2,
    3}` holds four addresses, and taking them for four mask lanes resolved a
    mask the rule never read.
    """
    if arg_index < 1:
        return None
    text = node_text(arguments, source).strip()
    if not text.startswith("(") or not text.endswith(")"):
        return None
    parts = [part.strip() for part in text[1:-1].split(",")]
    if arg_index >= len(parts):
        return None
    declarator, kind = parts[arg_index], parts[arg_index - 1]
    if "*" in kind or "*" in declarator:
        return None
    words = kind.split()
    # No separate qualifier check: a type argument that reaches the const
    # requirement below contains the word, so a shadowed `const` is caught
    # here. Measured -- a second check on the same case cannot be killed.
    if any(word in shadowed for word in words):
        return None
    if "const" not in words or "volatile" in words:
        return None
    if " ".join(word for word in words if word != "const") not in _BYTE_ELEMENTS:
        return None
    return declarator


def _collect_wrapper_macro_declarations(
    root: Node,
    source: bytes,
    path: str,
    index: SymbolIndex,
    knowledge: Knowledge,
    shadowed: Collection[str],
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
        declarator = _wrapper_declarator(arguments, arg_index, source, shadowed)
        if declarator is None:
            continue
        name = _declarator_name(declarator)
        rows = _rows_from_initializer(right, source)
        if name and rows:
            index.add(ConstantArray(name, f"{path}:{left.start_point[0] + 1}", rows))


def build_symbol_index(
    files: Iterable[tuple[str, bytes]],
    knowledge: Knowledge,
    warnings: list[str] | None = None,
) -> SymbolIndex:
    # A `#define` in one file can shadow a word a declaration in another file
    # rests on, and which header a file includes is not known here, so the
    # scan is pooled across every file rather than applied per file. The cost
    # is real: a CMake-generated `CMakeCCompilerId.c` left in a tree defines
    # both qualifiers, and scanning it withdraws every mask this index would
    # otherwise resolve. That is why each one is reported rather than applied
    # in silence -- a recall loss nothing announces reads as a clean run.
    parsed = [(path, source, parse_source(source).root_node) for path, source in files]
    shadowed: set[str] = set()
    for path, source, root in parsed:
        for word in sorted(_shadowed_words(root, source)):
            if word not in shadowed:
                message = (
                    f"{path}: #define of `{word}` withdraws every mask whose "
                    f"declaration is spelled with it; those grade C instead"
                )
                # Printed here rather than left for a caller to render, which
                # is how the parse and read warnings work: a list a caller may
                # or may not look at was reported as "on stderr" and was not.
                print(f"warning: {message}", file=sys.stderr)
                if warnings is not None:
                    warnings.append(Diagnostic(message, Diagnostic.SHADOWED))
            shadowed.add(word)

    index = SymbolIndex()
    for path, source, root in parsed:
        _collect_plain_declarations(root, source, path, index, shadowed)
        _collect_wrapper_macro_declarations(root, source, path, index, knowledge, shadowed)
    return index
