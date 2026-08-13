"""Shared rule interface.

A rule sees only the IR plus the knowledge tables and the symbol index. Rules
never import each other, and the registry never merges their output: one
source location may legitimately produce several findings of different types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, Protocol

from ..finding import Finding
from ..ir import FunctionUnit
from ..knowledge import Knowledge
from ..symbols import SymbolIndex


@dataclass
class Context:
    symbols: SymbolIndex
    knowledge: Knowledge
    config: dict[str, Any] = field(default_factory=dict)


class Rule(Protocol):
    type: str
    rule_id: str
    mechanism: str

    def match(self, unit: FunctionUnit, ctx: Context) -> Iterator[Finding]: ...
