from simde_lint.finding import Evidence
from simde_lint.rules.memory import MemoryRule, ScalarSetBuildRule


def test_reports_one_finding_for_a_chain_at_or_above_the_threshold(run_rule):
    findings = [f for f in run_rule(MemoryRule(), "memory_positive.c") if f.function == "kernel"]
    assert len(findings) == 1
    assert findings[0].type == "M"
    assert findings[0].evidence is Evidence.A
    assert "4" in findings[0].rationale


def test_reports_nothing_below_the_threshold(run_rule):
    assert run_rule(MemoryRule(), "memory_negative.c") == []


def test_separate_chains_reusing_the_same_variable_name_are_not_merged(run_rule):
    # The variable "v" is reset and rebuilt twice in one function. Grouping
    # inserts by result_var alone (ignoring the reset in between) would merge
    # a 4-element chain and a 3-element chain into one 7-element chain spanning
    # unrelated code, instead of reporting the two real chains that exist.
    findings = [
        f for f in run_rule(MemoryRule(), "memory_positive.c") if f.function == "reused_name"
    ]
    assert len(findings) == 2
    lengths = sorted(int(f.rationale.split()[0]) for f in findings)
    assert lengths == [3, 4]


def test_grades_a_chain_that_does_not_trace_every_step_back_to_the_target_b(run_rule):
    findings = [
        f for f in run_rule(MemoryRule(), "memory_positive.c") if f.function == "through_temp"
    ]
    assert len(findings) == 1
    assert findings[0].evidence is Evidence.B


def test_reports_a_vector_assembled_from_runtime_scalars(run_rule):
    findings = sorted(
        (f for f in run_rule(ScalarSetBuildRule(), "memory_positive.c") if f.function == "strided_rows"),
        key=lambda f: f.line,
    )
    assert [f.intrinsic for f in findings] == ["_mm_set_epi64x", "_mm_set_epi32"]
    assert all(f.evidence is Evidence.A for f in findings)
    assert findings[0].rule_mechanism == "vector built from runtime scalars"


def test_ignores_a_set_whose_arguments_are_all_literals(run_rule):
    # A constant vector is not a scalar assembly, so nothing is spilled.
    findings = [
        f for f in run_rule(ScalarSetBuildRule(), "memory_positive.c")
        if f.function == "strided_rows"
    ]
    assert len(findings) == 2


def test_grades_b_when_not_every_argument_is_a_direct_variable(run_rule):
    # A literal mixed among variables is still a scalar assembly — something
    # is spilled — but the call is not fully resolved to variable references,
    # so the grade drops. This is the rule's only path to B.
    findings = [
        f for f in run_rule(ScalarSetBuildRule(), "memory_positive.c")
        if f.function == "mixed_scalars"
    ]
    assert len(findings) == 2
    assert all(f.evidence is Evidence.B for f in findings)
