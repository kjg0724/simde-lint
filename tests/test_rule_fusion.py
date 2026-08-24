from simde_lint.finding import Evidence
from simde_lint.rules.fusion import FusionRule


def test_grades_a_direct_mul_to_add_path_a(run_rule):
    findings = sorted(
        (f for f in run_rule(FusionRule(), "fusion_positive.c") if f.function == "kernel"),
        key=lambda f: f.line,
    )
    assert findings[0].intrinsic == "_mm_mullo_epi32"
    assert findings[0].evidence is Evidence.A


def test_grades_a_path_through_a_widening_conversion_b(run_rule):
    findings = sorted(
        (f for f in run_rule(FusionRule(), "fusion_positive.c") if f.function == "kernel"),
        key=lambda f: f.line,
    )
    assert findings[1].intrinsic == "_mm_madd_epi16"
    assert findings[1].evidence is Evidence.B


def test_covers_the_256_bit_form(run_rule):
    findings = run_rule(FusionRule(), "fusion_positive.c")
    assert any(f.intrinsic == "_mm256_madd_epi16" for f in findings)


def test_reports_nothing_when_the_product_is_redefined_before_the_add(run_rule):
    assert run_rule(FusionRule(), "fusion_negative.c") == []


def test_one_add_is_one_fusion_opportunity(run_rule):
    # Two products reach the same add. Reporting both would double-count one
    # opportunity, and because each finding sits at its own multiply's line no
    # repeated-line check would show it.
    findings = [
        f for f in run_rule(FusionRule(), "fusion_positive.c") if f.function == "two_products"
    ]
    assert len(findings) == 1


def test_madd_epi16_names_no_fused_instruction(run_rule):
    # AArch64 has no pairwise 16-to-32 multiply-accumulate for madd_epi16;
    # naming smlal here would be wrong for the dominant, non-reduction case
    # (I2). Cost data backs this: native_insns is unknown for this intrinsic.
    findings = [
        f for f in run_rule(FusionRule(), "fusion_positive.c")
        if f.function == "kernel" and f.intrinsic == "_mm_madd_epi16"
    ]
    assert len(findings) == 1
    finding = findings[0]
    assert finding.suggestion is None
    assert finding.native_insns is None
    assert finding.simde_insns == 4
    assert "smlal" not in finding.rationale
    assert "vmlal" not in finding.rationale
    assert "no fused multiply-accumulate form is established" in finding.rationale
    assert "emitted as separate instructions" in finding.rationale


def test_mullo_epi32_names_its_fused_instruction(run_rule):
    # A non-widening multiply-accumulate exists for mullo_epi32 (mla), so the
    # rationale may name it when the native cost is established (I2).
    findings = sorted(
        (f for f in run_rule(FusionRule(), "fusion_positive.c") if f.function == "kernel"),
        key=lambda f: f.line,
    )
    finding = findings[0]
    assert finding.intrinsic == "_mm_mullo_epi32"
    assert finding.suggestion is not None
    assert finding.native_insns is not None


def test_verdict_is_invariant_to_how_the_alias_forwards_its_operands(run_rule):
    """C1: F reads only operand membership, never the multiply's own args.

    `_my_mullo_epi32` in the fixture hands its parameters to the real
    intrinsic in the opposite order from how the call site wrote them, but
    the call site still records its own args in macro-parameter order either
    way -- `is_forwarding_alias` discards the body's internal argument
    mapping entirely, keeping only the target name. F's verdict must be
    identical between a directly-called multiply and one reached through
    such an unfaithful alias, because `FusionRule.match`/`_path` never read
    the multiply's own args: they only check whether `mul.result_var` is a
    *member* of the following add's args, which an operand reversal inside
    the macro body cannot change.
    """
    findings = {
        f.function: f
        for f in run_rule(FusionRule(), "fusion_positive.c")
        if f.function in ("kernel", "unfaithful_forward") and f.intrinsic == "_mm_mullo_epi32"
    }
    assert set(findings) == {"kernel", "unfaithful_forward"}
    faithful, unfaithful = findings["kernel"], findings["unfaithful_forward"]
    assert faithful.intrinsic == unfaithful.intrinsic == "_mm_mullo_epi32"
    assert faithful.evidence == unfaithful.evidence == Evidence.A
    assert unfaithful.raw_name == "_my_mullo_epi32"


def test_an_intermediate_cannot_belong_to_a_later_multiply(run_rule):
    # The widening conversion runs before the second multiply, so only the
    # first can own it. Attributing it to the second would invert the interval
    # handed to redefined_between and pass the guard vacuously.
    findings = [
        f for f in run_rule(FusionRule(), "fusion_positive.c") if f.function == "reused_name"
    ]
    assert len(findings) == 1
    assert findings[0].evidence is Evidence.B
    assert "_mm_cvtepi32_epi64" in findings[0].rationale
