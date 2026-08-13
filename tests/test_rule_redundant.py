from simde_lint.finding import Evidence, Impact
from simde_lint.rules.redundant import RedundantRule


def test_reports_every_registered_redundant_intrinsic(run_rule):
    findings = run_rule(RedundantRule(), "redundant_positive.c")
    assert {f.intrinsic for f in findings} == {"_mm_loadu_si32", "_mm_cvtsi32_si128"}


def test_grades_every_finding_a_and_marks_it_diagnostic(run_rule):
    for finding in run_rule(RedundantRule(), "redundant_positive.c"):
        assert finding.evidence is Evidence.A
        assert finding.impact is Impact.DIAGNOSTIC
        assert finding.type == "R"
        assert finding.rule_mechanism


def test_reports_nothing_for_a_plain_full_width_load(run_rule):
    assert run_rule(RedundantRule(), "redundant_negative.c") == []
