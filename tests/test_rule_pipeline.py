from simde_lint.finding import Evidence, Impact
from simde_lint.rules.pipeline import PipelineRule


def test_reports_a_compare_consumed_by_the_next_call(run_rule):
    findings = run_rule(PipelineRule(), "pipeline_positive.c")
    assert len(findings) == 1
    assert findings[0].type == "P"
    assert findings[0].evidence is Evidence.A
    assert findings[0].impact is Impact.DIAGNOSTIC
    assert findings[0].intrinsic == "_mm_cmpgt_epi64"


def test_reports_nothing_when_an_independent_call_separates_them(run_rule):
    assert run_rule(PipelineRule(), "pipeline_negative.c") == []
