import re
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


def test_a_widening_hop_is_found_but_outruns_the_recorded_fused_form(run_rule):
    """The hop is what grade B is for, and no B survives the width check.

    A widening hop moves the product to a width the recorded fused form does
    not accumulate at, by definition of widening: `vmlaq_s32` writes 32-bit
    lanes and the add after a `_mm_cvtepi32_epi64` is 64. That is a gap in
    the knowledge table -- it records no fused form for multiply-then-widen-
    then-accumulate -- not a defect in the check, and `vmlal_s32` is not the
    missing entry: it computes the full 64-bit product where `mullo_epi32`
    truncates to 32 first, so the two disagree exactly when the product
    overflows.

    Rule F emitted no B on either reference corpus before this check existed
    either, so nothing observed was lost.
    """
    findings = [
        f
        for f in run_rule(FusionRule(), "fusion_positive.c")
        if f.function == "widening_known_cost"
    ]
    assert len(findings) == 1
    assert findings[0].intrinsic == "_mm_mullo_epi32"
    # The path is still found and still named -- only the replacement is
    # withdrawn.
    assert "through _mm_cvtepi32_epi64" in findings[0].rationale
    assert findings[0].evidence is Evidence.C
    assert findings[0].reason is Reason.TRANSFORM_WIDTH_MISMATCH
    assert findings[0].suggestion is None


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
    # This one reaches a 64-bit add through a widening hop, so the width
    # check answers before the conditional cap does: `vmlal_s16` accumulates
    # into 32-bit lanes. `madd_accumulated_at_its_own_width` carries the
    # conditional case now.
    assert findings[1].reason is Reason.TRANSFORM_WIDTH_MISMATCH
    assert findings[1].suggestion is None


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
        if f.function == "madd_accumulated_at_its_own_width"
    ]
    assert len(findings) == 1
    finding = findings[0]
    assert finding.reason is Reason.TRANSFORM_REQUIRES_CONTEXT
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
    """The guard at `fusion.py`'s ordering check, on a shape that reaches it.

    This assertion used to run against `reused_name`, which has one add: the
    first multiply claims it and the second never gets as far as the ordering
    comparison, so neutralising the guard changed that function's output not
    at all. A count of 1 held for a reason unrelated to what the test named.

    `widening_hop_precedes_the_multiply` gives the second multiply an add of
    its own. Without the guard it claims the widening hop at line 8 -- which
    ran before it -- and the function reports two findings instead of one.
    """
    by_function: dict[str, list] = {}
    for f in run_rule(FusionRule(), "fusion_positive.c"):
        by_function.setdefault(f.function, []).append(f)

    guarded = by_function["widening_hop_precedes_the_multiply"]
    assert len(guarded) == 1
    # The survivor is the multiply that precedes the hop, not the one after
    # it. Asserted by relative position rather than a line number, which
    # would break whenever anything is added to the fixture above it.
    hop_line = int(re.search(r"_mm_cvtepi32_epi64 at line (\d+)", guarded[0].rationale).group(1))
    assert guarded[0].line < hop_line

    findings = by_function["reused_name"]
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


def test_a_binary_transform_target_is_not_read_as_a_direct_result(run_rule):
    """Issue #15, shape 1: `x = mullo(...) ^ c` must not grade as a direct link.

    Extraction pins that `result_var` is None for this shape
    (test_extract.py::test_a_call_under_a_binary_expression_binds_no_result);
    this is the downstream consequence -- F reads `result_var` to decide
    membership, so if that pin were wrong, or F ignored it, this would still
    report an Evidence-A finding.
    """
    findings = [
        f
        for f in run_rule(FusionRule(), "fusion_negative.c")
        if f.function == "binary_transform_not_direct_result"
    ]
    assert findings == []


def test_a_conditional_transform_target_is_not_read_as_a_direct_result(run_rule):
    """Issue #15, shape 2: `x = t ? mullo(...) : c` must not grade as a direct link."""
    findings = [
        f
        for f in run_rule(FusionRule(), "fusion_negative.c")
        if f.function == "conditional_transform_not_direct_result"
    ]
    assert findings == []


def test_a_comma_transform_target_is_not_read_as_a_direct_result(run_rule):
    """Issue #15, shape 3: `x = (mullo(...), c)` must not grade as a direct link."""
    findings = [
        f
        for f in run_rule(FusionRule(), "fusion_negative.c")
        if f.function == "comma_transform_not_direct_result"
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


def test_a_multiply_written_as_the_adds_operand_is_reported(run_rule):
    # Rule F used to require a named product: `mul.result_var` gated the loop,
    # so the idiomatic `_mm_add_epi32(acc, _mm_mullo_epi32(a, b))` was never
    # looked at. Whether the author named the product is a spelling choice and
    # the emitted sequence is the same either way.
    findings = [
        f
        for f in run_rule(FusionRule(), "fusion_positive.c")
        if f.function == "nested_multiply_is_the_operand"
    ]
    assert len(findings) == 1
    assert findings[0].intrinsic == "_mm_mullo_epi32"
    # A, not B: with no name there is no window in which the product could be
    # redefined between producing it and consuming it.
    assert findings[0].evidence is Evidence.A


def test_a_nested_multiply_through_a_widening_hop_grades_b(run_rule):
    findings = [
        f
        for f in run_rule(FusionRule(), "fusion_positive.c")
        if f.function == "nested_multiply_through_a_widening_hop"
    ]
    assert len(findings) == 1
    # Same width story as `widening_known_cost`: the hop is found and named,
    # and the recorded form does not accumulate at the width it lands on.
    assert findings[0].evidence is Evidence.C
    assert findings[0].reason is Reason.TRANSFORM_WIDTH_MISMATCH
    assert "_mm_cvtepi32_epi64" in findings[0].rationale


def test_two_nested_multiplies_in_one_add_report_once(run_rule):
    # An add is one fusion opportunity. The claim that stops a flat pair of
    # products reporting twice has to hold for nested ones too, and each
    # finding is anchored at its own multiply -- here both are on the same
    # line, so a repeated-line check would not reveal a double report either.
    findings = [
        f
        for f in run_rule(FusionRule(), "fusion_positive.c")
        if f.function == "two_nested_multiplies_share_one_add"
    ]
    assert len(findings) == 1


def test_position_still_decides_for_a_named_product(run_rule):
    # Containment must not replace the byte-position test, only stand in for
    # it where there is no name. A named product still has to be produced
    # before the add that consumes it.
    findings = [
        f
        for f in run_rule(FusionRule(), "fusion_positive.c")
        if f.function == "widening_hop_precedes_the_multiply"
    ]
    assert len(findings) == 1


def test_a_nested_hop_that_is_not_a_widening_is_not_reported(run_rule):
    # Containment alone must not be enough. The product reaches the add, but
    # through a shuffle -- no fused multiply-accumulate covers that shape, and
    # reporting it would name a widening hop that is not one.
    findings = [
        f
        for f in run_rule(FusionRule(), "fusion_positive.c")
        if f.function == "nested_hop_is_not_a_widening"
    ]
    assert findings == []


def test_an_add_before_the_multiply_that_reuses_the_name_is_not_reported(run_rule):
    # The add consumed an earlier value bound to the same name. Without the
    # byte-position test the interval handed to the redefinition guard
    # inverts, the guard passes vacuously, and the add is credited to a
    # multiply that had not executed.
    findings = [
        f
        for f in run_rule(FusionRule(), "fusion_positive.c")
        if f.function == "the_add_precedes_the_multiply_that_reuses_the_name"
    ]
    assert findings == []


def _only(run_rule, function):
    findings = [
        f for f in run_rule(FusionRule(), "fusion_positive.c") if f.function == function
    ]
    assert len(findings) == 1
    return findings[0]


def test_a_suggestion_that_accumulates_at_another_width_is_not_named(run_rule):
    # The cost table maps a suggestion per intrinsic, so the multiply alone
    # picked it. `vmlal_s32` accumulates into 64-bit lanes; this accumulator
    # is 32, and naming it at grade A was the defect -- A is the layer
    # `--min-evidence A` exists to isolate.
    finding = _only(run_rule, "product_accumulated_at_the_wrong_width")
    assert finding.suggestion is None
    assert finding.evidence is Evidence.C
    assert finding.reason is Reason.TRANSFORM_WIDTH_MISMATCH
    # The observation survives: what is withdrawn is the replacement, not the
    # report that the multiply and the add are emitted separately.
    assert "emitted as separate instructions" in finding.rationale
    assert "vmlal_s32 accumulates into 64-bit lanes" in finding.rationale
    assert "_mm_add_epi32 accumulates into 32" in finding.rationale


def test_the_same_multiply_at_the_recorded_width_still_names_it(run_rule):
    # Without this the test above passes for a rule that dropped every
    # suggestion rule F has.
    finding = _only(run_rule, "product_accumulated_at_the_recorded_width")
    assert finding.suggestion == "vmlal_s32"
    assert finding.evidence is Evidence.A
    assert finding.reason is None


def test_every_recorded_fused_form_declares_what_it_accumulates_into():
    # The check above is only as good as the table behind it: an entry that
    # names an instruction without declaring its accumulator width would make
    # `_width_mismatch` return None and the call site go unchecked, silently.
    table = load_knowledge().patterns[FusionRule.rule_id]
    missing = [name for name, cost in table.items() if cost.accumulator_lanes is None]
    assert missing == []
