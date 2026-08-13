from simde_lint.finding import Evidence, Impact
from simde_lint.rules.suboptimal import SuboptimalRule


def _graded(run_rule):
    findings = run_rule(SuboptimalRule(), "suboptimal_positive.c")
    return sorted((f for f in findings if f.function == "kernel"), key=lambda f: f.line)


def test_reports_one_finding_per_shuffle_call_site(run_rule):
    findings = _graded(run_rule)
    assert len(findings) == 6
    assert all(f.type == "S" and f.intrinsic == "_mm_shuffle_epi8" for f in findings)


def test_grades_every_mask_form_in_fixture_order(run_rule):
    # inline literal, local constant, two-hop derivation, one-hop derivation,
    # runtime-indexed table, unresolvable.
    assert [f.evidence.value for f in _graded(run_rule)] == ["A", "A", "B", "B", "A", "C"]


def test_inline_literal_mask_is_confirmed_impact(run_rule):
    assert _graded(run_rule)[0].impact is Impact.CONFIRMED


def test_grades_a_local_constant_like_an_inline_literal(run_rule):
    # `const __m128i local_mask = _mm_setr_epi8(...)` is as knowable as the
    # same literal written into the call.
    assert _graded(run_rule)[1].evidence is Evidence.A


def test_traces_a_literal_through_more_than_one_operation(run_rule):
    # VVenC derives masks in several steps, so a single hop back would miss
    # the literal and grade this C.
    assert _graded(run_rule)[2].evidence is Evidence.B


def test_grades_symbol_table_a_when_every_row_is_safe(run_rule):
    finding = _graded(run_rule)[4]
    assert finding.evidence is Evidence.A
    assert finding.mask_source["symbol"] == "table_mask"
    assert finding.mask_source["resolution"] == "all_rows"


def test_grades_unresolvable_mask_c(run_rule):
    assert _graded(run_rule)[5].evidence is Evidence.C


def test_reports_nothing_for_shuffle_epi32(run_rule):
    assert run_rule(SuboptimalRule(), "suboptimal_negative.c") == []


def test_a_mask_reassigned_later_in_the_function_is_not_graded_a(run_rule):
    # Line order is not execution order: in a loop, the write below the use
    # reaches it on the next iteration. Since no control flow is modelled, a
    # second assignment anywhere in the function costs the A grade. Pinned so
    # nobody narrows the count to prior definitions as an optimization.
    findings = [
        f for f in run_rule(SuboptimalRule(), "suboptimal_positive.c")
        if f.function == "reassigned_after_use"
    ]
    assert len(findings) == 1
    assert findings[0].evidence is Evidence.B
