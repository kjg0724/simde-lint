"""M4: an isolated rule/unit failure must not abort the sweep or hide behind a clean exit.

Before this test existed, `extract_units` was guarded against a bad file but
`rule.match` was not: `Finding.__post_init__` (added alongside `scope`/
`macro` in v1.2) gave a rule a new way to raise partway through producing its
findings, and nothing caught it. A single malformed `Finding` from one rule
on one unit would have killed the entire sweep — every other rule, every
other unit, every other file — with no signal beyond an uncaught traceback.

These tests inject a rule that always raises this way and confirm three
things: the rest of the sweep still runs to completion, `analyze()`'s third
return value names exactly which rule failed on which unit and why, and the
CLI reports the run as incomplete rather than as a clean success.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import simde_lint.analyze as analyze_module
from simde_lint import cli
from simde_lint.analyze import analyze
from simde_lint.finding import Evidence, Finding, Impact
from simde_lint.ir import AnalysisUnit
from simde_lint.rules.base import Context
from simde_lint.rules.redundant import RedundantRule

FIXTURE_A = Path(__file__).parent / "fixtures" / "analyze" / "error_isolation_a.c"
FIXTURE_B = Path(__file__).parent / "fixtures" / "analyze" / "error_isolation_b.c"
FIXTURE_DUPLICATE_MACRO = (
    Path(__file__).parent / "fixtures" / "analyze" / "error_isolation_duplicate_macro.c"
)


class _AlwaysMalformedRule:
    """Constructs a `Finding` that violates the scope/function/macro invariant.

    Every real rule sets exactly one of `function`/`macro`, matching `scope`
    (see `rules/base.py`'s `location_fields`). This one sets both, always,
    regardless of the unit's actual scope: `Finding.__post_init__` raises on
    a function-scoped finding whenever `macro` is also set, and on a
    macro-scoped one whenever `function` is also set, so setting both
    unconditionally raises `ValueError` mid-materialization on either kind
    of unit -- the exact failure shape Task 5 introduced, reproduced on both
    scopes rather than only the function-scoped one.
    """

    type = "R"
    rule_id = "R.broken_for_test"
    mechanism = "deliberately malformed for the M4 regression test"

    def match(self, unit: AnalysisUnit, ctx: Context) -> Iterator[Finding]:
        for call in unit.calls:
            if call.name != "_mm_loadl_epi64":
                continue
            yield Finding(
                type=self.type,
                rule=self.rule_id,
                rule_mechanism=self.mechanism,
                evidence=Evidence.A,
                impact=Impact.DIAGNOSTIC,
                file=unit.file,
                line=call.line,
                function="deliberately set alongside macro to break __post_init__",
                scope=unit.scope,
                macro="deliberately set alongside function to break __post_init__",
                intrinsic=call.name,
                rationale="unreachable -- __post_init__ raises before this Finding exists",
                simde_insns=None,
                native_insns=None,
                suggestion=None,
            )


def test_a_malformed_finding_in_one_rule_does_not_abort_other_rules_or_files(monkeypatch):
    # The broken rule runs first, so a real regression to "the whole unit's
    # results are dropped" or "the sweep stops at the first failure" would
    # both be caught: RedundantRule must still fire on both files.
    monkeypatch.setattr(analyze_module, "ALL_RULES", [_AlwaysMalformedRule(), RedundantRule()])

    findings, _, errors = analyze([FIXTURE_A, FIXTURE_B])

    # Both files' _mm_loadl_epi64 still produced a real R finding from the
    # rule that runs cleanly -- the broken rule cost nothing outside itself.
    good_findings = [f for f in findings if f.rule == "R.zero_init_partial_load"]
    assert {f.file for f in good_findings} == {str(FIXTURE_A), str(FIXTURE_B)}
    assert len(good_findings) == 2

    # And the broken rule really did fail on both units -- not silently
    # skipped, not silently degraded to zero findings without a trace.
    assert len(errors) == 2
    assert all(f.rule != "R.broken_for_test" for f in findings)


def test_error_messages_name_the_rule_unit_and_file_and_the_run_is_not_a_clean_success(monkeypatch):
    monkeypatch.setattr(analyze_module, "ALL_RULES", [_AlwaysMalformedRule()])

    findings, _, errors = analyze([FIXTURE_A])

    assert findings == []
    assert len(errors) == 1
    message = errors[0]
    assert str(FIXTURE_A) in message
    assert "R.broken_for_test" in message
    assert "loads_in_a" in message  # the function the rule failed on
    assert "line 1" in message  # the function's own start line
    assert "ValueError" in message or "must set function" in message  # the exception itself


def test_error_messages_distinguish_two_same_named_units_by_position(monkeypatch):
    # I2's own docs (docs/verification.md) describe exactly this shape:
    # VVenC's RdCostX86.h defines UNPACKX twice, once per #ifdef branch, and
    # both are read. Two macro-scoped units share scope AND name here -- if
    # the warning dropped position, the two error messages would be
    # byte-for-byte identical and there would be no way to tell which #if
    # branch actually failed.
    monkeypatch.setattr(analyze_module, "ALL_RULES", [_AlwaysMalformedRule()])

    _, _, errors = analyze([FIXTURE_DUPLICATE_MACRO])

    assert len(errors) == 2
    assert all("macro 'UNPACKX'" in message for message in errors)
    assert all("R.broken_for_test" in message for message in errors)
    # Same scope, same name -- the messages must still differ, and they can
    # only differ by position (macro units carry no other identifying data
    # here; both come from the same file).
    assert errors[0] != errors[1]
    assert "line 3" in errors[0] and "line 3" not in errors[1]
    assert "line 6" in errors[1] and "line 6" not in errors[0]


def test_cli_exit_code_distinguishes_an_incomplete_run_from_success(monkeypatch, capsys):
    monkeypatch.setattr(analyze_module, "ALL_RULES", [_AlwaysMalformedRule(), RedundantRule()])

    code = cli.main([str(FIXTURE_A)])

    assert code != 0
    captured = capsys.readouterr()
    assert "R.broken_for_test" in captured.err
    # The findings a healthy rule produced are still on stdout -- an
    # incomplete run still reports everything it did manage to find.
    assert "_mm_loadl_epi64" in captured.out


def test_cli_exit_code_is_zero_on_a_clean_run():
    # Sanity check for the two tests above: a run with no injected failure
    # must not regress to a nonzero exit on its own.
    code = cli.main([str(FIXTURE_A)])
    assert code == 0
