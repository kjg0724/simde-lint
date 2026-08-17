"""Type M: a vector assembled from scalars instead of a structured load.

Two mechanisms live here. `MemoryRule` catches a chain of scalar inserts:
SIMDe has no counterpart for ARM's structured and lane-wise loads, so strided
reads become a chain of scalar inserts, each needing the value in a
general-purpose register first, where a NEON lane load reads straight into
the vector register. `ScalarSetBuildRule` catches a vector built in one call
from runtime scalars (`_mm_set_epi64x`/`_mm_set_epi32`/`_mm_set_epi16`):
SIMDe's NEON path spills each scalar to a stack array and reloads the whole
vector, the same store-to-load round trip a lane insert or structured load
avoids.

This rule has the highest false-positive risk of the six; the chain length
threshold is configurable through `ctx.config["memory_chain_threshold"]`.
"""

from __future__ import annotations

from typing import Iterator

from ..finding import Evidence, Finding, Impact
from ..ir import FunctionUnit, IntrinsicCall, ValueKind
from ..symbols import parse_int_literal
from .base import Context, raw_name_if_aliased

_INSERTS = {"_mm_insert_epi16", "_mm_insert_epi32", "_mm_insert_epi64", "_mm256_insert_epi16"}
_DEFAULT_THRESHOLD = 3
_SCALAR_SETS = {"_mm_set_epi64x", "_mm_set_epi32", "_mm_set_epi16"}


def _is_integer_literal(text: str) -> bool:
    return parse_int_literal(text) is not None


class MemoryRule:
    type = "M"
    rule_id = "M.scalar_insert_chain"
    mechanism = "scalar insert chain"

    def match(self, unit: FunctionUnit, ctx: Context) -> Iterator[Finding]:
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
                yield self._finding(unit, ctx, target, chain)

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
        self, unit: FunctionUnit, ctx: Context, target: str, calls: list[IntrinsicCall]
    ) -> Finding:
        direct = all(
            call.args and call.args[0].kind is ValueKind.VARIABLE and call.args[0].text == target
            for call in calls
        )
        first = calls[0]
        last = calls[-1]
        first_cost = ctx.knowledge.cost(self.rule_id, first.name)
        simde_total, native_total = self._sum_costs(ctx, calls)
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
                f"the general-purpose to vector register transfers ({first_cost.source})"
            ),
            simde_insns=simde_total,
            native_insns=native_total,
            # Representative: chains observed so far are one insert intrinsic
            # throughout, so the first call's suggestion stands for the whole
            # chain. If the first element's own cost is unknown, no fused
            # instruction is offered for the chain either.
            suggestion=first_cost.suggestion,
            raw_name=raw_name_if_aliased(first),
        )

    def _sum_costs(
        self, ctx: Context, calls: list[IntrinsicCall]
    ) -> tuple[int | None, int | None]:
        simde_total = 0
        native_total = 0
        for call in calls:
            cost = ctx.knowledge.cost(self.rule_id, call.name)
            if cost.simde_insns is None or cost.native_insns is None:
                # One unknown element makes the chain total unknown: there is
                # no honest number to add it to.
                return None, None
            simde_total += cost.simde_insns
            native_total += cost.native_insns
        return simde_total, native_total


class ScalarSetBuildRule:
    """Type M, second mechanism: a vector assembled from runtime scalars.

    On NEON, SIMDe's set constructors write each scalar into a stack array and
    reload the whole vector, so values already in general-purpose registers
    make a round trip through memory. VVenC's LoopFilter reads strided pixel
    rows this way, which is where the paper's LoopFilter Type M instances come
    from.
    """

    type = "M"
    rule_id = "M.scalar_set_build"
    mechanism = "vector built from runtime scalars"

    def match(self, unit: FunctionUnit, ctx: Context) -> Iterator[Finding]:
        for call in unit.calls:
            if call.name not in _SCALAR_SETS or not call.args:
                continue
            if all(_is_integer_literal(arg.text) for arg in call.args):
                # A constant vector, not a scalar assembly.
                continue
            cost = ctx.knowledge.cost(self.rule_id, call.name)
            direct = all(arg.kind is ValueKind.VARIABLE for arg in call.args)
            simde_total = cost.simde_insns * len(call.args) if cost.simde_insns is not None else None
            native_total = (
                cost.native_insns * len(call.args) if cost.native_insns is not None else None
            )
            yield Finding(
                type=self.type,
                rule=self.rule_id,
                rule_mechanism=self.mechanism,
                evidence=Evidence.A if direct else Evidence.B,
                impact=Impact.DIAGNOSTIC,
                file=unit.file,
                line=call.line,
                function=unit.name,
                intrinsic=call.name,
                rationale=(
                    f"{call.name} assembles {len(call.args)} runtime scalars into a "
                    f"vector; SIMDe spills them to a stack array and reloads it, a "
                    f"round trip a lane insert or structured load avoids "
                    f"({cost.source})"
                ),
                simde_insns=simde_total,
                native_insns=native_total,
                suggestion=cost.suggestion,
                raw_name=raw_name_if_aliased(call),
            )
