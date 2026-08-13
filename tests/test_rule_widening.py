from simde_lint.finding import Evidence, Impact
from simde_lint.rules.widening import WideningRule


def test_reports_the_mullo_mulhi_unpack_round_trip(run_rule):
    findings = run_rule(WideningRule(), "widening_positive.c")
    assert len(findings) == 1
    assert findings[0].type == "W"
    assert findings[0].evidence is Evidence.A
    assert findings[0].impact is Impact.CONFIRMED
    assert findings[0].suggestion == "vmull_s16"


def test_reports_nothing_when_the_multiplies_use_different_operands(run_rule):
    assert run_rule(WideningRule(), "widening_negative.c") == []
