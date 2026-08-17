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
    findings = [f for f in run_rule(PipelineRule(), "pipeline_negative.c") if f.function == "kernel"]
    assert findings == []


def test_reports_nothing_when_the_compare_result_was_overwritten(run_rule):
    # A plain reassignment is not a call, so call adjacency alone still sees
    # these two as neighbours; only a redefinition check rejects it.
    findings = [
        f for f in run_rule(PipelineRule(), "pipeline_negative.c")
        if f.function == "overwritten"
    ]
    assert findings == []


def test_reports_nothing_when_the_compare_result_was_overwritten_by_a_call(run_rule):
    # I1: the overwrite is `mask = helper_load(c)`, a call to something that
    # isn't a recognized intrinsic. Extraction must still record it as a
    # definition so this redefinition is visible here, exactly as the plain
    # variable-to-variable overwrite above already is.
    findings = [
        f for f in run_rule(PipelineRule(), "pipeline_negative.c")
        if f.function == "overwritten_by_call"
    ]
    assert findings == []
