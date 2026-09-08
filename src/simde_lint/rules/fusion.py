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
    "_mm256_mullo_epi16",
    "_mm256_madd_epi16",
    "_mm256_mul_epi32",
    # Single-precision float. The taxonomy defines type F by mechanism --
    # SIMDe translating one intrinsic at a time and missing a fusion -- and
    # `_mm_mul_ps` expands to `vmulq_f32` alone with `vfmaq_f32` sitting
    # unused, which is that mechanism exactly. The substitution is not
    # result-preserving, which the entry's `transform_status` records rather
    # than this set.
    "_mm_mul_ps",
    "_mm256_mul_ps",
}
# The accumulator's lane width, which is what a suggested multiply-accumulate
# has to accumulate into. Keyed by the add rather than the multiply because
# the multiply does not decide it: `_mm_mul_epi32` produces 64-bit products
# and can still be accumulated 32 bits at a time, and was.
_ADD_LANES = {
    # 16-lane adds. Without these `vmlaq_s16` could never be printed -- every
    # 16-bit multiply would meet a wider add and be withdrawn as a width
    # mismatch -- and SVT-AV1's CDEF filters, which accumulate
    # `_mm256_add_epi16(acc, _mm256_mullo_epi16(tap, x))` throughout, reported
    # no rule F finding at all.
    "_mm_add_epi16": ("i", 16),
    "_mm256_add_epi16": ("i", 16),
    "_mm_add_epi32": ("i", 32),
    "_mm256_add_epi32": ("i", 32),
    "_mm_add_epi64": ("i", 64),
    "_mm256_add_epi64": ("i", 64),
    # f32 lanes are 32 bits wide, the same as `epi32`, so width alone cannot
    # tell them apart. The element kind is carried beside it rather than
    # relying on the C type system to keep them apart: this rule has no type
    # model, and a translation unit pairing an integer product with
    # `_mm_add_ps` does compile under the lax vector conversions clang
    # applies by default -- the configuration SIMDe-on-NEON is built with.
    "_mm_add_ps": ("f", 32),
    "_mm256_add_ps": ("f", 32),
}
_ADDS = set(_ADD_LANES)
# The element kind each registered multiply produces, paired with the lane
# width the knowledge table records. Width alone does not separate `epi32`
# from `ps`, and the rule cannot fall back on the C type system: it reads
# names, not types.
_ELEMENT_KIND = {name: ("f" if name.endswith("_ps") else "i") for name in _MULTIPLIES}
_WIDENING = {
    "_mm_cvtepi32_epi64",
    "_mm_cvtepi16_epi32",
    "_mm256_cvtepi32_epi64",
    "_mm256_cvtepi16_epi32",
}


# Two absences that must never collapse into one: "written as a direct operand
# of the add" and "not an operand of the add at all". `None` means the first,
# so the second needs a value of its own.
_NOT_AN_OPERAND = object()


def _operand_hop(unit: AnalysisUnit, add: IntrinsicCall, mul: IntrinsicCall):
    """Where `mul` sits inside `add`, if it is written inside it at all.

    Returns `None` when the multiply is a direct operand, the widening call
    between them when it reaches the add through one, and `_NOT_AN_OPERAND`
    when it is not written inside the add.
    """
    for arg in add.args:
        if arg.kind is not ValueKind.CALL_RESULT or arg.call_id is None:
            continue
        if arg.call_id == mul.id:
            return None
        hop = unit.call_by_id(arg.call_id)
        if hop is None or hop.name not in _WIDENING or hop.is_macro_alias:
            continue
        if any(
            inner.kind is ValueKind.CALL_RESULT and inner.call_id == mul.id
            for inner in hop.args
        ):
            return hop
    return _NOT_AN_OPERAND


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
            if mul.name not in _MULTIPLIES:
                continue
            cost = ctx.knowledge.cost(self.rule_id, mul.name)
            for add in adds:
                if add.id in claimed_adds:
                    continue
                if not self._reaches_by_position(unit, mul, add):
                    continue
                path = self._path(unit, mul, add)
                if path is None:
                    continue
                evidence, via = path
                reason = None
                capped, cap_reason = self.cap_for(cost)
                if capped is not None:
                    evidence, reason = capped, cap_reason
                claim = self._fusion_claim(cost)
                suggestion = cost.suggestion
                native_insns = cost.native_insns
                mismatch = self._width_mismatch(cost, add)
                if mismatch is not None:
                    # The multiply-add is still there and still unfused. What
                    # is not there is the replacement, so the finding keeps
                    # the observation and drops the instruction rather than
                    # naming one that cannot be dropped in.
                    evidence, reason = Evidence.C, Reason.TRANSFORM_WIDTH_MISMATCH
                    claim, suggestion = mismatch, None
                    # The count goes with the instruction. Only the
                    # replacement side is withdrawn, so `simde_insns` stays
                    # and `native_insns` -- which counted the instruction the
                    # rationale has just called inapplicable -- does not.
                    # Leaving it made the report say "no replacement" and
                    # "the replacement is 3 instructions" in adjacent lines.
                    native_insns = None
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
                        f"{add.line}{via}; {claim} ({cost.source})"
                    ),
                    simde_insns=cost.simde_insns,
                    native_insns=native_insns,
                    suggestion=suggestion,
                    raw_name=raw_name_if_aliased(mul),
                )
                break

    @staticmethod
    def _width_mismatch(cost: CostInfo, add: IntrinsicCall) -> str | None:
        """The reason the recorded instruction does not fit this accumulator.

        Returns None when it fits, or when there is nothing to compare. The
        cost table maps a suggestion per intrinsic, so the multiply alone
        picks it; which add the product reaches is what decides whether it can
        be used, and nothing consulted that. `_mm_mul_epi32` reaching
        `_mm_add_epi32` is the case that shows it: `vmlal_s32` accumulates
        into 64-bit lanes and the accumulator here is 32.
        """
        wanted = cost.accumulator_lanes
        entry = _ADD_LANES.get(add.name)
        if wanted is None or entry is None:
            return None
        kind, actual = entry
        if kind == _ELEMENT_KIND[cost.key] and wanted == actual:
            return None
        described = f"{actual}-bit {'float' if kind == 'f' else 'integer'} lanes"
        return (
            "the multiply and the accumulate are emitted as separate "
            f"instructions; the recorded fused form {cost.suggestion} accumulates "
            f"into {wanted}-bit {'float' if _ELEMENT_KIND[cost.key] == 'f' else 'integer'} "
            f"lanes, but {add.name} accumulates into {described}, "
            "so it is not the replacement here"
        )

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
        if cost.transform_status is TransformStatus.CHANGES_RESULT:
            return Evidence.C, Reason.TRANSFORM_CHANGES_RESULT
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
        if cost.transform_status is TransformStatus.CHANGES_RESULT:
            return (
                f"{observed}; {cost.suggestion} fuses them but rounds once where the "
                "separate multiply and add round twice, so the results differ"
            )
        if cost.transform_status is not TransformStatus.ESTABLISHED:
            return f"{observed}; no fused multiply-accumulate form is established for this intrinsic"
        return (
            f"{observed}; NEON fuses this into {cost.suggestion} for some accumulator shapes"
        )

    @staticmethod
    def _reaches_by_position(
        unit: AnalysisUnit, mul: IntrinsicCall, add: IntrinsicCall
    ) -> bool:
        """Whether `add` can be consuming this multiply's product at all.

        Three things have to hold, and byte position alone settles none of
        them.

        A multiply written directly as an operand reaches the add that
        contains it, and there byte position says the opposite of the truth:
        the add's call expression opens first, so the add starts *before* a
        product it is waiting on. Containment settles that case.

        For a named product the add must come after the multiply -- but
        "after" has to mean after the whole binding statement, not after the
        multiply's opening byte. An add nested inside the multiply's own
        argument list also starts later while running first, feeding the
        multiply rather than consuming it, and the redefinition guard cannot
        catch it: the interval handed to `redefined_between` inverts and
        passes vacuously, the same inversion the widening-hop branch guards
        against.

        And both must be able to execute together. A multiply in one arm of
        an `if` and an add in the other are ordered by position and never run
        in the same pass, so there is no fusion opportunity to report -- the
        reason rule M carries `control_region`. Containment implies one
        region, so only the named branch has to ask.
        """
        if _operand_hop(unit, add, mul) is not _NOT_AN_OPERAND:
            return True
        if not mul.result_var or mul.control_region != add.control_region:
            return False
        return add.start_byte >= own_availability(unit, mul)

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
        hop = _operand_hop(unit, add, mul)
        if hop is not _NOT_AN_OPERAND:
            # The product is never named, so there is no window in which it
            # could be redefined and nothing for `redefined_between` to
            # answer. Written as an operand it reaches the add, or the
            # program does not compile.
            if hop is None:
                return Evidence.A, ""
            return Evidence.B, f" through {hop.name} at line {hop.line}"

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
