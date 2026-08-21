"""Type R: SIMDe emits a zero-initialization a native NEON load does not need."""

from __future__ import annotations

from typing import Iterator

from ..finding import Evidence, Finding, Impact
from ..ir import AnalysisUnit
from .base import Context, raw_name_if_aliased


class RedundantRule:
    type = "R"
    rule_id = "R.zero_init_partial_load"
    mechanism = "zero-init before partial load"

    def match(self, unit: AnalysisUnit, ctx: Context) -> Iterator[Finding]:
        for call in unit.calls:
            info = ctx.knowledge.redundant.get(call.name)
            if info is None:
                continue
            yield Finding(
                type=self.type,
                rule=self.rule_id,
                rule_mechanism=self.mechanism,
                evidence=Evidence.A,
                impact=Impact.DIAGNOSTIC,
                file=unit.file,
                line=call.line,
                function=unit.function_name,
                scope=unit.scope,
                macro=unit.macro_name,
                intrinsic=call.name,
                rationale=(
                    f"SIMDe {ctx.knowledge.simde_version} expands {call.name} to "
                    f"{info.note or 'a zero-initialized vector plus a partial load'} "
                    f"({info.source}); removing the zero-init is safe only if the "
                    "vector's unused lanes are dead in the code that consumes the "
                    "result, which this rule does not establish"
                ),
                simde_insns=info.simde_insns,
                native_insns=info.native_insns,
                suggestion=info.suggestion,
                raw_name=raw_name_if_aliased(call),
            )
