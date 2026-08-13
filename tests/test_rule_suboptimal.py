from simde_lint.finding import Evidence, Impact
from simde_lint.rules.suboptimal import SuboptimalRule


def _by_line(findings):
    return {f.line: f for f in findings}


def test_reports_one_finding_per_shuffle_call_site(run_rule):
    findings = run_rule(SuboptimalRule(), "suboptimal_positive.c")
    assert len(findings) == 4
    assert all(f.type == "S" and f.intrinsic == "_mm_shuffle_epi8" for f in findings)


def test_grades_inline_literal_mask_a(run_rule):
    findings = sorted(run_rule(SuboptimalRule(), "suboptimal_positive.c"), key=lambda f: f.line)
    assert findings[0].evidence is Evidence.A
    assert findings[0].impact is Impact.CONFIRMED


def test_grades_mask_derived_through_an_intermediate_operation_b(run_rule):
    findings = sorted(run_rule(SuboptimalRule(), "suboptimal_positive.c"), key=lambda f: f.line)
    assert findings[1].evidence is Evidence.B


def test_grades_symbol_table_a_when_every_row_is_safe(run_rule):
    findings = sorted(run_rule(SuboptimalRule(), "suboptimal_positive.c"), key=lambda f: f.line)
    assert findings[2].evidence is Evidence.A
    assert findings[2].mask_source["symbol"] == "table_mask"
    assert findings[2].mask_source["resolution"] == "all_rows"


def test_grades_unresolvable_mask_c(run_rule):
    findings = sorted(run_rule(SuboptimalRule(), "suboptimal_positive.c"), key=lambda f: f.line)
    assert findings[3].evidence is Evidence.C


def test_reports_nothing_for_shuffle_epi32(run_rule):
    assert run_rule(SuboptimalRule(), "suboptimal_negative.c") == []
