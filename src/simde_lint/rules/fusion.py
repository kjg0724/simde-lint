"""Type F: a multiply whose result is added separately instead of fused.

SIMDe translates one intrinsic at a time, so a multiply followed by an add
stays two instructions. NEON fuses them: smlal accumulates a widening product
in a single instruction.
"""

from __future__ import annotations

from typing import Iterator

from ..finding import Evidence, Finding, Reason
from ..ir import AnalysisUnit, IntrinsicCall, ValueKind
from ..knowledge import CostInfo, TransformStatus
from .base import Context, location_fields, own_availability, raw_name_if_aliased

_MULTIPLIES = {
    "_mm_mullo_epi32",
    "_mm_mullo_epi16",
    "_mm_madd_epi16",
    "_mm_mul_epi32",
    "_mm256_mullo_epi32",
    "_mm256_madd_epi16",
    "_mm256_mul_epi32",
}
_ADDS = {"_mm_add_epi32", "_mm_add_epi64", "_mm256_add_epi32", "_mm256_add_epi64"}
_WIDENING = {
    "_mm_cvtepi32_epi64",
    "_mm_cvtepi16_epi32",
    "_mm256_cvtepi32_epi64",
    "_mm256_cvtepi16_epi32",
}


class FusionRule:
    type = "F"
    rule_id = "F.mul_add_no_fuse"
    mechanism = "multiply-add not fused"
    options = ()

    def match(self, unit: AnalysisUnit, ctx: Context) -> Iterator[Finding]:
        adds = sorted((c for c in unit.calls if c.name in _ADDS), key=lambda c: c.start_byte)
        # An add is one fusion opportunity, so the first multiply reaching it
        # claims it. Without this, `sum = _mm_add_epi32(p1, p2)` over two
        # products reports twice — and since each finding is anchored at its
        # own multiply's line, no repeated-line check would reveal it.
        claimed_adds: set[int] = set()

        for mul in sorted(unit.calls, key=lambda c: c.start_byte):
            if mul.name not in _MULTIPLIES or not mul.result_var:
                continue
            cost = ctx.knowledge.cost(self.rule_id, mul.name)
            for add in adds:
                if add.id in claimed_adds or add.start_byte <= mul.start_byte:
                    continue
                path = self._path(unit, mul, add)
                if path is None:
                    continue
                evidence, via = path
                reason = None
                capped, cap_reason = self.cap_for(cost)
                if capped is not None:
                    evidence, reason = capped, cap_reason
                claimed_adds.add(add.id)
                yield Finding(
                    type=self.type,
                    rule=self.rule_id,
                    rule_mechanism=self.mechanism,
                    evidence=evidence,
                    reason=reason,
                    file=unit.file,
                    line=mul.line,
                    **location_fields(unit),
                    intrinsic=mul.name,
                    rationale=(
                        f"{mul.name} at line {mul.line} reaches {add.name} at line "
                        f"{add.line}{via}; {self._fusion_claim(cost)} ({cost.source})"
                    ),
                    simde_insns=cost.simde_insns,
                    native_insns=cost.native_insns,
                    suggestion=cost.suggestion,
                    raw_name=raw_name_if_aliased(mul),
                )
                break

    def cap_for(self, cost: CostInfo) -> tuple[Evidence | None, Reason | None]:
        """The grade ceiling this intrinsic's transform status imposes.

        Returns `(None, None)` when the status imposes none — the def-use
        path then decides. Reads `transform_status` and never `suggestion`:
        what the report shows a reader is not what the tool asserts.
        """
        if cost.transform_status is TransformStatus.ESTABLISHED:
            return None, None
        if cost.transform_status is TransformStatus.CONDITIONAL:
            return Evidence.C, Reason.TRANSFORM_REQUIRES_CONTEXT
        return Evidence.C, Reason.UNRESOLVED

    @staticmethod
    def _fusion_claim(cost) -> str:
        """What the rule can honestly claim about fusion for this intrinsic.

        The multiply and the add are always observed as separate SIMDe
        translations — that much is structural. Whether NEON has a fused
        multiply-accumulate that reaches them is a separate question the
        rule can only answer from the intrinsic's recorded `transform_status`:
        `unknown` means no fused form is recorded at all, so the rationale
        must not name an instruction that may not exist for this call site.
        `conditional` means one is recorded (madd_epi16's vmlal_s16 /
        vmlal_high_s16 pair, for a horizontal-reduction consumer) but the
        condition it needs is not something this rule checks, so the
        rationale names it without claiming it as the unconditional
        replacement. A recorded fused form with no instruction count still
        names the instruction — the count is reported separately, and is
        absent when SIMDe's expansion leaves it to the compiler.
        """
        observed = "the multiply and the accumulate are emitted as separate instructions"
        if cost.transform_status is TransformStatus.CONDITIONAL:
            return (
                f"{observed}; {cost.suggestion} applies only when the consumer is a "
                "horizontal reduction, which this rule does not check"
            )
        if cost.transform_status is not TransformStatus.ESTABLISHED:
            return f"{observed}; no fused multiply-accumulate form is established for this intrinsic"
        return (
            f"{observed}; NEON fuses this into {cost.suggestion} for some accumulator shapes"
        )

    def _path(
        self, unit: AnalysisUnit, mul: IntrinsicCall, add: IntrinsicCall
    ) -> tuple[Evidence, str] | None:
        """Direct identity grades A; one widening hop grades B."""
        if add.is_macro_alias:
            # P1: `add` was resolved through a file-local `#define`
            # forwarding alias. Its recorded args are the call site's own --
            # built from the macro's parameter positions, with no mapping
            # back to which of the body's operands each parameter actually
            # reached. Membership here would be a claim about the
            # *forwarded* call's operands that extraction cannot support, so
            # F makes no claim at all.
            #
            # Deliberately narrower than `add.raw_name != add.name` (P2): a
            # `simde_`-prefixed direct call also changes spelling on
            # resolution, through `knowledge/aliases.yaml`, not a macro
            # body -- that correspondence is exact by SIMDe's own naming
            # convention, so it must not abstain here.
            return None
        operands = {arg.text for arg in add.args if arg.kind is ValueKind.VARIABLE}

        if mul.result_var in operands:
            if unit.redefined_between(mul.result_var, own_availability(unit, mul), add.start_byte):
                return None
            return Evidence.A, ""

        for name in operands:
            definition = unit.definition_before(name, add.start_byte)
            if definition is None or definition.value.call_id is None:
                continue
            intermediate = unit.call_by_id(definition.value.call_id)
            if intermediate is None or intermediate.name not in _WIDENING:
                continue
            if intermediate.is_macro_alias:
                # Same reasoning as `add` above: the widening hop is also a
                # consumer whose args this rule checks membership against.
                continue
            if intermediate.start_byte <= mul.start_byte:
                # The intermediate ran before this multiply, so it cannot be
                # carrying this multiply's product. Without this test the
                # interval handed to redefined_between inverts, which makes the
                # redefinition guard pass vacuously and attributes the product
                # to a multiply that had not executed yet.
                continue
            if mul.result_var not in {a.text for a in intermediate.args}:
                continue
            if unit.redefined_between(
                mul.result_var, own_availability(unit, mul), intermediate.start_byte
            ):
                continue
            return Evidence.B, f" through {intermediate.name} at line {intermediate.line}"
        return None
