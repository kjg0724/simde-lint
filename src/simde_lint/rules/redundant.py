"""Type R: SIMDe emits a zero-initialization a native NEON load does not need."""

from __future__ import annotations

from typing import Iterator

from ..finding import Evidence, Finding, Impact
from ..ir import FunctionUnit
from .base import Context


class RedundantRule:
    type = "R"
    rule_id = "R.zero_init_partial_load"
    mechanism = "zero-init before partial load"

    def match(self, unit: FunctionUnit, ctx: Context) -> Iterator[Finding]:
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
                function=unit.name,
                intrinsic=call.name,
                rationale=(
                    f"SIMDe {ctx.knowledge.simde_version} expands {call.name} to "
                    f"{info.note or 'a zero-initialized vector plus a partial load'} "
                    f"({info.source})"
                ),
                simde_insns=info.simde_insns,
                native_insns=info.native_insns,
                suggestion=info.suggestion,
            )
