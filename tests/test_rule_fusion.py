from dataclasses import replace

from simde_lint.finding import Evidence, Reason
from simde_lint.knowledge import CostInfo, TransformStatus, load_knowledge
from simde_lint.rules.fusion import FusionRule


def _grade_for(cost: CostInfo) -> Evidence:
    """The evidence rule F would cap this cost at, ignoring the def-use path."""
    return FusionRule().cap_for(cost)[0]


def test_grades_a_direct_mul_to_add_path_a(run_rule):
    findings = sorted(
        (f for f in run_rule(FusionRule(), "fusion_positive.c") if f.function == "kernel"),
        key=lambda f: f.line,
    )
    assert findings[0].intrinsic == "_mm_mullo_epi32"
    assert findings[0].evidence is Evidence.A


def test_grades_a_path_through_a_widening_conversion_b(run_rule):
    findings = [
        f
        for f in run_rule(FusionRule(), "fusion_positive.c")
        if f.function == "widening_known_cost"
    ]
    assert len(findings) == 1
    assert findings[0].intrinsic == "_mm_mullo_epi32"
    assert findings[0].evidence is Evidence.B


def test_a_conditional_transform_caps_at_c_with_its_own_reason():
    """Grade alone cannot distinguish conditional from unknown.

    Both cap at C, so a test asserting only the grade would pass with the
    two statuses swapped. The reason is the whole point: one says the tool
    could not judge, the other says a transform exists under a condition the
    rule did not check.
    """
    knowledge = load_knowledge()
    cost = knowledge.patterns["F.mul_add_no_fuse"]["_mm_madd_epi16"]
    assert cost.transform_status is TransformStatus.CONDITIONAL

    evidence, reason = FusionRule().cap_for(cost)

    assert evidence is Evidence.C
    assert reason is Reason.TRANSFORM_REQUIRES_CONTEXT


def test_an_unknown_transform_caps_at_c_with_the_unresolved_reason():
    cost = CostInfo(
        key="_mm_fake",
        simde_insns=2,
        native_insns=None,
        suggestion=None,
        source="x86/fake.h:1",
        transform_status=TransformStatus.UNKNOWN,
    )

    evidence, reason = FusionRule().cap_for(cost)

    assert evidence is Evidence.C
    assert reason is Reason.UNRESOLVED


def test_an_unestablished_fused_form_caps_the_grade_at_c(run_rule):
    """The def-use path being clean does not make the transform unconditional.

    madd_epi16's pairwise reduction has no unconditional AArch64 fused form:
    vmlal_s16 / vmlal_high_s16 applies only for a horizontal-reduction
    consumer this rule does not check. Grading it A or B on the strength of
    the def-use link alone would report a conditional transform as
    established.
    """
    findings = sorted(
        (f for f in run_rule(FusionRule(), "fusion_positive.c") if f.function == "kernel"),
        key=lambda f: f.line,
    )
    assert findings[1].intrinsic == "_mm_madd_epi16"
    assert findings[1].evidence is Evidence.C
    assert findings[1].reason is Reason.TRANSFORM_REQUIRES_CONTEXT
    assert findings[1].suggestion == "vmlal_s16 / vmlal_high_s16"


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


def test_madd_epi16_names_its_conditional_fused_instruction(run_rule):
    # AArch64 has no unconditional pairwise 16-to-32 multiply-accumulate for
    # madd_epi16, but vmlal_s16 / vmlal_high_s16 applies when the consumer is
    # a horizontal reduction (I2) -- a shape this rule does not check, so the
    # rationale must name it as conditional, not as the replacement. Whether
    # a count is knowable is a separate fact from whether a transform is
    # established: native_insns stays unknown even though the suggestion is
    # now recorded.
    findings = [
        f for f in run_rule(FusionRule(), "fusion_positive.c")
        if f.function == "kernel" and f.intrinsic == "_mm_madd_epi16"
    ]
    assert len(findings) == 1
    finding = findings[0]
    assert finding.suggestion == "vmlal_s16 / vmlal_high_s16"
    assert finding.native_insns is None
    assert finding.simde_insns == 4
    assert "vmlal_s16 / vmlal_high_s16 applies only when the consumer is a horizontal reduction" in finding.rationale
    assert "which this rule does not check" in finding.rationale
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


def test_reports_nothing_when_the_consuming_alias_dropped_the_producers_result(run_rule):
    """P1: a dropped parameter on the *consumer* side, not the producer's.

    `DROP_FIRST_MUL(a, b)` never uses `a` -- it forwards only `b` (twice) to
    `_mm_add_epi32`. Before `is_forwarding_alias` rejected this shape,
    `DROP_FIRST_MUL(prod, acc)` resolved to `_mm_add_epi32` with args
    `(prod, acc)` -- the call site's own args, in macro-parameter order --
    so `prod` still looked consumed even though the real
    `_mm_add_epi32(acc, acc)` never receives it. `DROP_FIRST_MUL` must not be
    registered as an alias at all, so this call site is not recognized as an
    intrinsic call and F's `adds` list never includes it.
    """
    findings = [f for f in run_rule(FusionRule(), "fusion_positive.c") if f.function == "dropped_parameter"]
    assert findings == []


def test_abstains_when_the_consumer_call_drops_a_parameters_value(run_rule):
    """P1 round 3: the registration predicate alone is not sound.

    `DROP_VALUE_MUL(a, b)`'s body is `_mm_add_epi32(((void)(a), (b)), (b))`
    -- `a` (bound to `prod`) appears in the argument subtree, inside a
    `(void)`-cast comma operand, so a text-appearance registration check
    still confirms this as an alias. The real fix is that F declines to
    read `sum`'s args at all once `sum`'s call was resolved through a
    file-local macro alias (`FusionRule._path`'s `add.is_macro_alias`
    check) -- it does not matter whether registration would have accepted
    or rejected this shape.
    """
    findings = [f for f in run_rule(FusionRule(), "fusion_positive.c") if f.function == "drop_value_consumer"]
    assert findings == []


def test_abstains_when_the_consumer_call_combines_a_parameter_with_itself(run_rule):
    """P1 round 3: the `(a) ^ (a)` residual the registration predicate cannot close.

    No syntactic rule distinguishes "combined with itself losslessly" from
    "genuinely used" -- `XOR_SELF_MUL`'s `a` is confirmed as used by every
    identifier-appearance check. F's abstention on an aliased consumer call
    does not depend on that distinction, which is why it catches this case
    too.
    """
    findings = [f for f in run_rule(FusionRule(), "fusion_positive.c") if f.function == "xor_self_consumer"]
    assert findings == []


def test_reports_when_the_consumer_is_a_direct_simde_spelled_call(run_rule):
    """P2: `raw_name != name` is not the same as "resolved through a macro".

    `simde_mm_add_epi32` is a direct call under its `simde_`-prefixed
    spelling, normalized through `knowledge/aliases.yaml` to
    `_mm_add_epi32` -- with the identical signature by SIMDe's own naming
    convention, no macro body, no possibility of a dropped, duplicated or
    discarded parameter. `FusionRule._path` guards on `add.is_macro_alias`,
    which extraction sets only for a file-local `#define` forwarding alias,
    not for this. Identical code shape to `drop_value_consumer`, opposite
    verdict, because the provenance differs.
    """
    findings = [
        f for f in run_rule(FusionRule(), "fusion_positive.c") if f.function == "simde_spelled_consumer"
    ]
    assert len(findings) == 1
    assert findings[0].intrinsic == "_mm_mullo_epi32"
    assert findings[0].evidence is Evidence.A


def test_widening_hop_abstains_only_for_a_macro_resolved_intermediate(run_rule):
    """P2: the widening-hop guard (`fusion.py:125`) must use provenance too.

    Easy to overlook because it guards the intermediate widening call, not
    the add itself. `WRAP_WIDEN` is a real file-local macro alias for
    `_mm_cvtepi32_epi64` -- faithful or not does not matter, since the
    abstention is unconditional on any macro-resolved consumer -- so F must
    not claim the widening path through `widening_wrapper_intermediate`.
    `simde_mm_cvtepi32_epi64` in `widening_simde_intermediate` changes
    spelling the same way but not through a macro, so F must still claim it.
    """
    findings = {
        f.function: f
        for f in run_rule(FusionRule(), "fusion_positive.c")
        if f.function in ("widening_wrapper_intermediate", "widening_simde_intermediate")
    }
    assert set(findings) == {"widening_simde_intermediate"}
    finding = findings["widening_simde_intermediate"]
    # This fixture's multiply is madd, which caps at C (see
    # test_an_unestablished_fused_form_caps_the_grade_at_c); what this test
    # pins is that the hop was claimed here and abstained on the macro case.
    assert finding.evidence is Evidence.C
    assert "_mm_cvtepi32_epi64" in finding.rationale


def test_an_intermediate_cannot_belong_to_a_later_multiply(run_rule):
    # The widening conversion runs before the second multiply, so only the
    # first can own it. Attributing it to the second would invert the interval
    # handed to redefined_between and pass the guard vacuously.
    findings = [
        f for f in run_rule(FusionRule(), "fusion_positive.c") if f.function == "reused_name"
    ]
    assert len(findings) == 1
    # madd caps at C (see test_an_unestablished_fused_form_caps_the_grade_at_c);
    # what this test pins is that the widening hop was claimed at all.
    assert findings[0].evidence is Evidence.C
    assert "_mm_cvtepi32_epi64" in findings[0].rationale


def test_a_compound_assignment_target_is_not_read_as_a_direct_result(run_rule):
    """Issue #13, shape 1: `x += mullo(...)` must not grade as a direct link.

    Extraction pins that `result_var` is None for this shape
    (test_extract.py::test_a_compound_assignment_target_is_not_recorded_as_a_direct_result);
    this is the downstream consequence -- F reads `result_var` to decide
    membership, so if that pin were wrong, or F ignored it, this would still
    report an Evidence-A finding.
    """
    findings = [
        f
        for f in run_rule(FusionRule(), "fusion_negative.c")
        if f.function == "compound_assignment_not_direct_result"
    ]
    assert findings == []


def test_a_compound_assignments_write_stays_visible_to_fusion(run_rule):
    """Issue #13, shape 2: the compound write must still count as a redefinition.

    Extraction pins that the second, compound-assigned multiply still
    records an UNKNOWN definition for its write
    (test_extract.py::test_a_compound_assignment_still_records_an_unknown_definition);
    this is the downstream consequence -- without it, F's
    `redefined_between` check would miss the reassignment and link the
    first, direct multiply through a value the second one actually
    overwrote.
    """
    findings = [
        f
        for f in run_rule(FusionRule(), "fusion_negative.c")
        if f.function == "compound_assignment_overwrites_result"
    ]
    assert findings == []


def test_changing_only_the_suggestion_cannot_change_the_evidence():
    """The invariant this whole change exists for.

    Before v2.1 rule F read `suggestion is None` for grading, so filling in
    an informative suggestion for an entry with no established fused form
    silently promoted its findings from C to A. Presentation must not move
    the grade. This is a synthetic entry, not `_mm_madd_epi16` -- that
    intrinsic is now `conditional` in the real knowledge table, so no
    `unknown` entry remains under `F.mul_add_no_fuse` to read this off of.
    """
    cost = CostInfo(
        key="_mm_fake",
        simde_insns=4,
        native_insns=None,
        suggestion=None,
        source="x86/fake.h:1",
        transform_status=TransformStatus.UNKNOWN,
    )

    with_suggestion = replace(cost, suggestion="smlal_s16")
    graded = _grade_for(with_suggestion)

    assert graded is Evidence.C
