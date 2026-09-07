"""Type R: SIMDe emits a zero-initialization a native NEON load does not need."""

from __future__ import annotations

from typing import Iterator

from ..finding import Evidence, Finding, Reason
from ..ir import AnalysisUnit
from .base import Context, location_fields, raw_name_if_aliased


class RedundantRule:
    type = "R"
    rule_id = "R.zero_init_partial_load"
    mechanism = "zero-init before partial load"
    options = ()

    def match(self, unit: AnalysisUnit, ctx: Context) -> Iterator[Finding]:
        for call in unit.calls:
            info = ctx.knowledge.redundant.get(call.name)
            if info is None:
                continue
            yield Finding(
                type=self.type,
                rule=self.rule_id,
                rule_mechanism=self.mechanism,
                # C, not A: the rationale below says the transform is safe only
                # when the unused lanes are dead in the consumer, and this rule
                # never looks at the consumer. Grading A said the opposite of
                # the sentence it shipped alongside.
                #
                # TRANSFORM_REQUIRES_CONTEXT rather than GUARD_REQUIRED, per the
                # definitions in `finding.py`: GUARD_REQUIRED is for a guard the
                # rule examined and found load-bearing, as rule S does with a
                # mask lane provably out of range. Here the call was seen
                # clearly and a condition was not checked, which is the other
                # one -- and the vocabulary exists so the two are not
                # interchangeable.
                evidence=Evidence.C,
                reason=Reason.TRANSFORM_REQUIRES_CONTEXT,
                file=unit.file,
                line=call.line,
                **location_fields(unit),
                intrinsic=call.name,
                rationale=(
                    f"SIMDe {ctx.knowledge.simde_version} implements {call.name} "
                    f"as follows: "
                    f"{info.note or 'a zero-initialized vector plus a partial load'} "
                    f"({info.source}). That explicitly constructs the zero-valued "
                    "lanes the intrinsic is defined to produce; removing the work "
                    "may be lower-cost where those lanes are dead in the consuming "
                    "code, but this rule does not analyse the consumer and so "
                    "offers no replacement"
                ),
                simde_insns=info.simde_insns,
                native_insns=info.native_insns,
                suggestion=info.suggestion,
                raw_name=raw_name_if_aliased(call),
            )
