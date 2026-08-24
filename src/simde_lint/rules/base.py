"""Shared rule interface.

A rule sees only the IR plus the knowledge tables and the symbol index. Rules
never import each other, and the registry never merges their output: one
source location may legitimately produce several findings of different types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, Protocol

from ..finding import Finding
from ..ir import AnalysisUnit, IntrinsicCall
from ..knowledge import Knowledge
from ..symbols import SymbolIndex


def location_fields(unit: AnalysisUnit) -> dict[str, str | None]:
    """The three `Finding` fields every rule must copy from its unit, together.

    `CONTRIBUTING.md`'s enumeration of what a rule reads from `AnalysisUnit`
    once omitted `function_name`/`macro_name` — the two members every rule
    actually needs, because every `Finding` construction site hand-writes
    `function=unit.function_name, scope=unit.scope, macro=unit.macro_name`.
    A rule that instead reached for `unit.name` (following the shorter list
    literally) silently produced `scope='function', function=<macro name>,
    macro=None` on a macro unit — indistinguishable from a real function
    finding in the text report, and `Finding.__post_init__` does not catch
    it (it enforces internal consistency between `scope`/`function`/`macro`,
    not correspondence with the unit that produced them).

    Splatting this into every `Finding(...)` call makes the omission
    structurally impossible instead of merely undocumented: there is no
    "unit.name" to reach for by mistake once these three always travel
    together.
    """
    return {
        "function": unit.function_name,
        "scope": unit.scope,
        "macro": unit.macro_name,
    }


@dataclass
class Context:
    symbols: SymbolIndex
    knowledge: Knowledge
    config: dict[str, Any] = field(default_factory=dict)


class Rule(Protocol):
    type: str
    rule_id: str
    mechanism: str

    def match(self, unit: AnalysisUnit, ctx: Context) -> Iterator[Finding]: ...


def own_availability(unit: AnalysisUnit, call: IntrinsicCall) -> int:
    """Byte offset after which `call`'s own bound result becomes available.

    A rule asking `redefined_between(call.result_var, call.start_byte, ...)`
    means "did something else overwrite this after `call` produced it" — but
    `call.start_byte` is where the call begins, not where its result becomes
    available, and the binding `Definition` it creates always has a later
    `available_after_byte`. Anchoring at `call.start_byte` therefore makes
    that same definition look like a redefinition of itself. The producing
    call and its binding definition share `start_byte` (extraction sets the
    definition's `start_byte` from the call's), so that identity finds the
    right definition and its `available_after_byte` is the correct anchor.
    """
    for definition in unit.definitions.get(call.result_var, ()):
        if definition.start_byte == call.start_byte:
            return definition.available_after_byte
    return call.start_byte


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
