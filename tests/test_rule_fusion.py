from simde_lint.finding import Evidence
from simde_lint.rules.fusion import FusionRule


def test_grades_a_direct_mul_to_add_path_a(run_rule):
    findings = sorted(run_rule(FusionRule(), "fusion_positive.c"), key=lambda f: f.line)
    assert findings[0].intrinsic == "_mm_mullo_epi32"
    assert findings[0].evidence is Evidence.A


def test_grades_a_path_through_a_widening_conversion_b(run_rule):
    findings = sorted(run_rule(FusionRule(), "fusion_positive.c"), key=lambda f: f.line)
    assert findings[1].intrinsic == "_mm_madd_epi16"
    assert findings[1].evidence is Evidence.B


def test_covers_the_256_bit_form(run_rule):
    findings = run_rule(FusionRule(), "fusion_positive.c")
    assert any(f.intrinsic == "_mm256_madd_epi16" for f in findings)


def test_reports_nothing_when_the_product_is_redefined_before_the_add(run_rule):
    assert run_rule(FusionRule(), "fusion_negative.c") == []
