from simde_lint.finding import Evidence, Impact
from simde_lint.rules.redundant import RedundantRule


def test_reports_every_registered_redundant_intrinsic(run_rule):
    findings = run_rule(RedundantRule(), "redundant_positive.c")
    assert {f.intrinsic for f in findings} == {
        "_mm_loadu_si32",
        "_mm_cvtsi32_si128",
        "_mm_loadl_epi64",
        "_mm_loadu_si64",
    }


def test_reports_loadl_epi64_with_its_own_suggestion_and_cost(run_rule):
    findings = [
        f for f in run_rule(RedundantRule(), "redundant_positive.c")
        if f.intrinsic == "_mm_loadl_epi64"
    ]
    assert len(findings) == 1
    finding = findings[0]
    assert finding.suggestion == "vld1q_lane_s64"
    assert (finding.simde_insns, finding.native_insns) == (2, 1)


def test_reports_loadu_si64_with_the_cost_it_inherits_from_cvtsi64_si128(run_rule):
    # sse2.h:5844 is a plain delegation to simde_mm_cvtsi64_si128; the
    # zero-init happens one level down (sse2.h:3652), so the rationale must
    # not read as if the zero-init lives at 5844 itself.
    findings = [
        f for f in run_rule(RedundantRule(), "redundant_positive.c")
        if f.intrinsic == "_mm_loadu_si64"
    ]
    assert len(findings) == 1
    finding = findings[0]
    assert finding.suggestion == "vsetq_lane_s64"
    assert (finding.simde_insns, finding.native_insns) == (2, 1)
    assert "simde_mm_cvtsi64_si128" in finding.rationale
    assert "sse2.h:5844" in finding.rationale
    assert "sse2.h:3652" in finding.rationale


def test_grades_every_finding_a_and_marks_it_diagnostic(run_rule):
    for finding in run_rule(RedundantRule(), "redundant_positive.c"):
        assert finding.evidence is Evidence.A
        assert finding.impact is Impact.DIAGNOSTIC
        assert finding.type == "R"
        assert finding.rule_mechanism


def test_reports_nothing_for_a_plain_full_width_load(run_rule):
    assert run_rule(RedundantRule(), "redundant_negative.c") == []


def test_rationale_states_the_dead_lane_condition_the_rule_does_not_establish(run_rule):
    # I3: R always grades A (evidence is purely structural), but the
    # transform is only actually safe when the upper/unused lanes turn out
    # to be dead afterward — a fact this rule cannot see. The suggestion
    # stays (it is still the right transform if that condition holds), but
    # the rationale must say so rather than imply the removal is unconditionally
    # safe.
    for finding in run_rule(RedundantRule(), "redundant_positive.c"):
        assert finding.suggestion
        assert finding.simde_insns is not None
        assert finding.native_insns is not None
        assert "dead" in finding.rationale
        assert "does not establish" in finding.rationale
