"""Type P: a compare result consumed by the immediately following call.

On Neoverse V1 a compare result consumed back to back carries a use-to-use
latency penalty. Source order is an explicit approximation of scheduling
order, not a claim about what the compiler emits, which is why every finding
is marked diagnostic.
"""

from __future__ import annotations

from typing import Iterator

from ..finding import Evidence, Finding, Impact
from ..ir import FunctionUnit, ValueKind
from .base import Context

_COMPARES = {
    "_mm_cmpgt_epi64",
    "_mm_cmpgt_epi32",
    "_mm_cmpgt_epi16",
    "_mm_cmpgt_epi8",
    "_mm_cmpeq_epi64",
    "_mm_cmpeq_epi32",
    "_mm256_cmpgt_epi64",
    "_mm256_cmpgt_epi32",
}


class PipelineRule:
    type = "P"
    rule_id = "P.cmp_immediate_use"
    mechanism = "compare consumed by the next call"

    def match(self, unit: FunctionUnit, ctx: Context) -> Iterator[Finding]:
        cost = ctx.knowledge.cost(self.rule_id)
        ordered = sorted(unit.calls, key=lambda c: (c.line, c.column))
        for current, following in zip(ordered, ordered[1:]):
            if current.name not in _COMPARES or not current.result_var:
                continue
            consumed = any(
                arg.kind is ValueKind.VARIABLE and arg.text == current.result_var
                for arg in following.args
            )
            if not consumed:
                continue
            yield Finding(
                type=self.type,
                rule=self.rule_id,
                rule_mechanism=self.mechanism,
                evidence=Evidence.A,
                impact=Impact.DIAGNOSTIC,
                file=unit.file,
                line=current.line,
                function=unit.name,
                intrinsic=current.name,
                rationale=(
                    f"{current.name} at line {current.line} is consumed by "
                    f"{following.name} at line {following.line} with no independent "
                    f"work between them; source order approximates scheduling order "
                    f"({cost.source})"
                ),
                simde_insns=cost.simde_insns,
                native_insns=cost.native_insns,
                suggestion=cost.suggestion,
            )
