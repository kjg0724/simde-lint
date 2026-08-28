from simde_lint.finding import Evidence
from simde_lint.rules.widening import WideningRule


def test_reports_the_mullo_mulhi_unpack_round_trip(run_rule):
    findings = [f for f in run_rule(WideningRule(), "widening_positive.c") if f.function == "kernel"]
    assert len(findings) == 1
    assert findings[0].type == "W"
    assert findings[0].evidence is Evidence.A
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


def test_reports_nothing_when_the_mullo_result_is_overwritten_before_the_unpack(run_rule):
    # I6: `lo` is reassigned to an unrelated load between the multiply and the
    # unpack that names it. The unpack still names `lo`, but the value it
    # reads is no longer the multiply's product, so this is not a round trip
    # and must not be reported.
    findings = [
        f for f in run_rule(WideningRule(), "widening_positive.c")
        if f.function == "overwritten"
    ]
    assert findings == []


def test_picks_the_consumer_that_runs_after_the_multiplies_on_a_shared_line(run_rule):
    # `same_line_decoy` puts a decoy unpack, both multiplies, and the real
    # consuming unpack on one physical line. The decoy names the same `lo`/
    # `hi` variables but runs before either multiply, so it cannot be their
    # consumer. Line-only comparison cannot tell the decoy and the real
    # unpack apart — both share `.line` with the multiplies — and a boundary
    # check of `unpack.line < after_line` never excludes the decoy, since it
    # sits on the same line rather than strictly before it. Byte offsets
    # distinguish them: the decoy's `start_byte` precedes the multiplies',
    # the real unpack's follows.
    findings = [
        f for f in run_rule(WideningRule(), "widening_positive.c")
        if f.function == "same_line_decoy"
    ]
    assert len(findings) == 1
    assert "_mm_unpacklo_epi16" in findings[0].rationale
    assert "_mm_unpackhi_epi16" not in findings[0].rationale
