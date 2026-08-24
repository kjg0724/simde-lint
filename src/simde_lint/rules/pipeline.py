"""Type P: a compare result consumed by the immediately following call.

On Neoverse V1 a compare result consumed back to back carries a use-to-use
latency penalty. Source order is an explicit approximation of scheduling
order, not a claim about what the compiler emits, which is why every finding
is marked diagnostic.
"""

from __future__ import annotations

from typing import Iterator

from ..finding import Evidence, Finding, Impact
from ..ir import AnalysisUnit, ValueKind
from .base import Context, location_fields, own_availability, raw_name_if_aliased

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

    def match(self, unit: AnalysisUnit, ctx: Context) -> Iterator[Finding]:
        ordered = sorted(unit.calls, key=lambda c: c.start_byte)
        for current, following in zip(ordered, ordered[1:]):
            if current.name not in _COMPARES or not current.result_var:
                continue
            if following.is_macro_alias:
                # P1: `following` was resolved through a file-local `#define`
                # forwarding alias. Its recorded args are the call site's own
                # -- built from the macro's parameter positions, with no
                # mapping back to which of the body's operands each
                # parameter actually reached (a body can drop, duplicate, or
                # discard a parameter's value in a comma expression, a
                # (void) cast, either branch of a ternary, and more that no
                # syntactic check can enumerate). Membership here would be a
                # claim about the *forwarded* call's operands that
                # extraction cannot support, so P makes no claim at all
                # rather than approximate one.
                #
                # This is deliberately narrower than `following.raw_name !=
                # following.name`: a `simde_`-prefixed direct call (P2) also
                # changes spelling on resolution, through
                # `knowledge/aliases.yaml`, not a macro body -- SIMDe's own
                # naming convention keeps that correspondence exact (same
                # arity, same argument order), so it carries none of the
                # above risk and must not abstain here.
                continue
            cost = ctx.knowledge.cost(self.rule_id, current.name)
            consumed = any(
                arg.kind is ValueKind.VARIABLE and arg.text == current.result_var
                for arg in following.args
            )
            if not consumed:
                continue
            if unit.redefined_between(
                current.result_var, own_availability(unit, current), following.start_byte
            ):
                # The name still matches but the value does not: something
                # overwrote it in between, so the compare's result never
                # reaches this call and there is no back-to-back use.
                continue
            yield Finding(
                type=self.type,
                rule=self.rule_id,
                rule_mechanism=self.mechanism,
                evidence=Evidence.A,
                impact=Impact.DIAGNOSTIC,
                file=unit.file,
                line=current.line,
                **location_fields(unit),
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
                raw_name=raw_name_if_aliased(current),
            )
