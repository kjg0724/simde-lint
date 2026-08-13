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
