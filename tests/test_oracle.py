"""The tool against expectations decided independently of it.

Every other test in this suite, and `docs/precision/verify.py` too, compares
the tool against a second reading built from the same inference. Both have
missed defects that shared their blind spot: `verify.py` could not see rule
F's nested multiply-add because its own predicate also required a named
product, and had to be extended alongside the rule.

`tests/oracle/expected.yaml` is written by hand from the rule descriptions
and the source, before the tool is run. It can be wrong, but it is wrong
independently — which is the property nothing else here has.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from simde_lint.analyze import analyze

ORACLE = Path(__file__).parent / "oracle"
CASES = ORACLE / "cases"

_CHECKED = ("line", "type", "rule", "evidence", "reason", "intrinsic", "suggestion")


def _expected() -> dict:
    return yaml.safe_load((ORACLE / "expected.yaml").read_text())


def _actual(path: Path) -> list:
    findings, _, _ = analyze([path])
    return sorted(findings, key=lambda f: (f.line, f.type, f.intrinsic))


def _describe(finding) -> str:
    return (
        f"line {finding.line} {finding.type} {finding.evidence.value} "
        f"{finding.intrinsic}"
    )


@pytest.mark.parametrize("case", sorted(_expected()))
def test_the_tool_agrees_with_the_hand_decided_expectation(case):
    expectation = _expected()[case]
    assert expectation.get("why"), f"{case}: an expectation needs its reasoning"
    findings = _actual(CASES / case)
    wanted = expectation["findings"]

    assert len(findings) == len(wanted), (
        f"{case}: expected {len(wanted)} findings, got {len(findings)}: "
        + "; ".join(_describe(f) for f in findings)
    )

    # `line` is optional: where the rule description does not determine
    # which call site a multi-call mechanism anchors at, the expectation says
    # so in `why` rather than guessing and then "correcting" itself to match.
    order = sorted(wanted, key=lambda w: (w.get("line", 0), w.get("type", "")))
    for finding, want in zip(findings, order):
        for field in _CHECKED:
            if field not in want:
                continue
            actual = getattr(finding, field)
            if hasattr(actual, "value"):
                actual = actual.value
            assert actual == want[field], (
                f"{case} line {finding.line}: {field} is {actual!r}, "
                f"expected {want[field]!r}"
            )
        if "rationale_includes" in want:
            assert want["rationale_includes"] in finding.rationale, (
                f"{case} line {finding.line}: rationale does not say "
                f"{want['rationale_includes']!r} — {finding.rationale}"
            )
        if "rationale_excludes" in want:
            assert want["rationale_excludes"] not in finding.rationale, (
                f"{case} line {finding.line}: rationale still says "
                f"{want['rationale_excludes']!r} — {finding.rationale}"
            )


def test_every_case_file_has_an_expectation():
    # A .c file with no entry would be scanned by nothing and look like
    # coverage. The oracle is only as good as its completeness.
    cases = {path.name for path in CASES.glob("*.c")}
    assert cases == set(_expected())
