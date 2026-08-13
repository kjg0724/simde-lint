from simde_lint.finding import Evidence, Impact
from simde_lint.rules.widening import WideningRule


def test_reports_the_mullo_mulhi_unpack_round_trip(run_rule):
    findings = [f for f in run_rule(WideningRule(), "widening_positive.c") if f.function == "kernel"]
    assert len(findings) == 1
    assert findings[0].type == "W"
    assert findings[0].evidence is Evidence.A
    assert findings[0].impact is Impact.CONFIRMED
    assert findings[0].suggestion == "vmull_s16"


def test_reports_nothing_when_the_multiplies_use_different_operands(run_rule):
    assert run_rule(WideningRule(), "widening_negative.c") == []


def test_reports_one_finding_per_round_trip_not_per_matching_pair(run_rule):
    # Two round-trips reusing the same variable names. Pairing every multiply
    # with every other would report four findings for two round-trips, which is
    # what VVenC's DeQuant turns into sixteen for four.
    findings = [f for f in run_rule(WideningRule(), "widening_positive.c") if f.function == "repeated"]
    assert len(findings) == 2
    assert len({f.line for f in findings}) == 2
