"""Type M: a vector assembled from separate scalar inserts.

SIMDe has no counterpart for ARM's structured and lane-wise loads, so strided
reads become a chain of scalar inserts, each needing the value in a
general-purpose register first. A NEON lane load reads straight into the
vector register.

This rule has the highest false-positive risk of the six; the chain length
threshold is configurable through `ctx.config["memory_chain_threshold"]`.
"""

from __future__ import annotations

from typing import Iterator

from ..finding import Evidence, Finding, Impact
from ..ir import FunctionUnit, IntrinsicCall, ValueKind
from .base import Context

_INSERTS = {"_mm_insert_epi16", "_mm_insert_epi32", "_mm_insert_epi64", "_mm256_insert_epi16"}
_DEFAULT_THRESHOLD = 3


class MemoryRule:
    type = "M"
    rule_id = "M.scalar_insert_chain"
    mechanism = "scalar insert chain"

    def match(self, unit: FunctionUnit, ctx: Context) -> Iterator[Finding]:
        cost = ctx.knowledge.cost(self.rule_id)
        threshold = int(ctx.config.get("memory_chain_threshold", _DEFAULT_THRESHOLD))

        by_var: dict[str, list[IntrinsicCall]] = {}
        for call in sorted(unit.calls, key=lambda c: c.line):
            if call.name not in _INSERTS or not call.result_var:
                continue
            by_var.setdefault(call.result_var, []).append(call)

        for target, calls in by_var.items():
            for chain in self._split_chains(unit, target, calls):
                if len(chain) < threshold:
                    continue
                yield self._finding(unit, cost, target, chain)

    @staticmethod
    def _split_chains(
        unit: FunctionUnit, target: str, calls: list[IntrinsicCall]
    ) -> Iterator[list[IntrinsicCall]]:
        """Split same-variable inserts into runs unbroken by an intervening write.

        Source reuses a vector variable name across unrelated blocks — a reset
        and rebuild later in the same function, for instance. Grouping by
        result_var alone would merge those into one oversized chain spanning
        code that has nothing to do with the first. A write to `target`
        between two inserts (any definition strictly between their lines)
        means the later insert cannot be extending the earlier one's result,
        so it starts a new chain instead.
        """
        chain: list[IntrinsicCall] = []
        for call in calls:
            if chain and unit.redefined_between(target, chain[-1].line, call.line):
                yield chain
                chain = []
            chain.append(call)
        if chain:
            yield chain

    def _finding(
        self, unit: FunctionUnit, cost, target: str, calls: list[IntrinsicCall]
    ) -> Finding:
        direct = all(
            call.args and call.args[0].kind is ValueKind.VARIABLE and call.args[0].text == target
            for call in calls
        )
        first = calls[0]
        last = calls[-1]
        return Finding(
            type=self.type,
            rule=self.rule_id,
            rule_mechanism=self.mechanism,
            evidence=Evidence.A if direct else Evidence.B,
            impact=Impact.DIAGNOSTIC,
            file=unit.file,
            line=first.line,
            function=unit.name,
            intrinsic=first.name,
            rationale=(
                f"{len(calls)} scalar inserts assemble {target} between lines "
                f"{first.line} and {last.line}; a NEON lane load chain avoids "
                f"the general-purpose to vector register transfers ({cost.source})"
            ),
            simde_insns=cost.simde_insns * len(calls),
            native_insns=cost.native_insns * len(calls),
            suggestion=cost.suggestion,
        )
