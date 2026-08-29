"""tree-sitter-cpp wrapper.

This module and extract.py are the only places that touch the tree-sitter
Node API. Everything downstream consumes the IR instead.
"""

from __future__ import annotations

from typing import Iterator

import tree_sitter_cpp
from tree_sitter import Language, Node, Parser, Tree

_LANGUAGE = Language(tree_sitter_cpp.language())


def parse_source(source: bytes) -> Tree:
    """Parse C/C++ source. Never raises on malformed input."""
    return Parser(_LANGUAGE).parse(source)


def unparsed_regions(root: Node) -> list[tuple[int, int]]:
    """Line spans tree-sitter could not parse, outermost only.

    tree-sitter always returns a tree. When it cannot parse a construct it
    recovers, which means a file with an ERROR node still yields findings —
    just not necessarily all of them, and with no signal that any were lost.
    Preprocessor-heavy C++ headers hit this often: at the pinned revisions,
    362 of SVT-AV1's 561 files and 11 of VVenC's 47 x86 files contain an
    ERROR node, and recovery cost nothing measurable there. On VVdeC's
    `InterpolationFilterX86.h` it cost eleven call sites — every registered
    intrinsic past line 3034 in a 3398-line file.

    So the count cannot be trusted silently. Reporting the spans lets a
    reader see which files carry the risk instead of discovering it by
    grepping. Nested errors are not reported separately: an outer ERROR
    already covers its children, and listing both would double-count the
    same damage.
    """
    regions: list[tuple[int, int]] = []

    def walk(node: Node) -> None:
        if node.type == "ERROR" or node.is_missing:
            regions.append((node.start_point[0] + 1, node.end_point[0] + 1))
            return
        for child in node.children:
            walk(child)

    walk(root)
    return regions


def iter_nodes(node: Node, type_name: str) -> Iterator[Node]:
    """Yield every descendant of `node` (inclusive) with the given type."""
    if node.type == type_name:
        yield node
    for child in node.children:
        yield from iter_nodes(child, type_name)


def node_text(node: Node | None, source: bytes) -> str:
    if node is None:
        return ""
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")
