from simde_lint.finding import Evidence, Reason
from simde_lint.report.text import render_text
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


def test_grades_every_finding_c_for_the_condition_it_does_not_check(run_rule):
    """Grade and reason together, because the grade alone does not pin this.

    R graded A until this change, with the dead-lane caveat carried in the
    rationale instead. The two contradicted each other: A asserts the rule
    resolved everything it depends on, and the sentence beside it said the
    condition the transform needs is not established.

    The reason is as load-bearing as the grade. `GUARD_REQUIRED` would say
    this rule examined a guard and found it load-bearing, which is rule S's
    case, not this one; `UNRESOLVED` would say it could not see far enough,
    when in fact it saw the call clearly and did not look at the consumer.
    Asserting only `Evidence.C` would pass under either wrong reason.
    """
    for finding in run_rule(RedundantRule(), "redundant_positive.c"):
        assert finding.evidence is Evidence.C
        assert finding.reason is Reason.TRANSFORM_REQUIRES_CONTEXT
        assert finding.type == "R"
        assert finding.rule_mechanism


def test_reports_nothing_for_a_plain_full_width_load(run_rule):
    assert run_rule(RedundantRule(), "redundant_negative.c") == []


def test_a_call_inside_a_macro_body_is_attributed_to_the_macro_not_a_function(run_rule):
    # I2: nothing else drives a MacroUnit through a rule end to end. Every
    # other test in this file uses a fixture that is a plain function, so a
    # rule that regressed to `function=unit.name,` (the pre-Task-5 shape,
    # dropping `scope=`/`macro=`) would still pass every one of them — the
    # macro-body call site is the only place the defect is observable.
    findings = run_rule(RedundantRule(), "redundant_macro.c")
    assert findings, "expected at least one finding from the macro body"
    for finding in findings:
        assert finding.scope == "macro"
        assert finding.function is None
        assert finding.macro == "LOAD_PAIR"
    assert "(macro)" in render_text([findings[0]])


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
