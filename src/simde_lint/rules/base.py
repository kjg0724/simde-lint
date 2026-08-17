"""Shared rule interface.

A rule sees only the IR plus the knowledge tables and the symbol index. Rules
never import each other, and the registry never merges their output: one
source location may legitimately produce several findings of different types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, Protocol

from ..finding import Finding
from ..ir import FunctionUnit, IntrinsicCall
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


def raw_name_if_aliased(call: IntrinsicCall) -> str | None:
    """The call's original spelling, when the rule matched it under an alias.

    A finding's `intrinsic` field is always the resolved canonical name, so
    grepping the source for that exact spelling finds nothing at a
    macro-aliased call site (VVenC's `_my_cmpgt_epi64`, for instance, which
    resolves to `_mm_cmpgt_epi64`). Returns None when the raw spelling and
    the resolved name are the same, so an unaliased finding carries no
    redundant field.
    """
    return call.raw_name if call.raw_name != call.name else None
