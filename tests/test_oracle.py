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
_RATIONALE = ("rationale_includes", "rationale_excludes")
_ALLOWED_IN_A_FINDING = frozenset(_CHECKED) | frozenset(_RATIONALE)
_ALLOWED_IN_A_CASE = frozenset({"why", "findings"})


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
def test_an_expectation_only_uses_fields_this_runner_checks(case):
    """An unrecognised key was skipped, so a typo passed as agreement.

    The comparison below reads the fields it knows and ignores the rest, which
    made `evidance: A` indistinguishable from a satisfied `evidence`. Four such
    typos left the whole corpus green. That failure mode is silence, which is
    what every defect this corpus exists to catch has looked like -- and it
    applied to the only test pinning the portable-fallback rationale.

    Checked in its own test rather than inside the comparison: a malformed
    expectation is a defect in the expectation, and saying so separately keeps
    it from reading as a disagreement with the tool.
    """
    expectation = _expected()[case]
    unknown = set(expectation) - _ALLOWED_IN_A_CASE
    assert not unknown, f"{case}: unrecognised key(s) {sorted(unknown)}"
    for want in expectation["findings"]:
        unknown = set(want) - _ALLOWED_IN_A_FINDING
        assert not unknown, (
            f"{case}: unrecognised key(s) {sorted(unknown)} in an expected "
            "finding -- nothing would check them"
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

    # Both sides sort on the same key, and a `line`-less expectation is
    # matched by position among the findings rather than forced to the front.
    # Sorting expectations by `line` with a 0 default put such an entry first
    # whatever its mechanism anchors at, so a case passed only because its
    # chain happened to be the earliest of three findings.
    keyed = [w for w in wanted if "line" in w]
    unkeyed = [w for w in wanted if "line" not in w]
    order = sorted(keyed, key=lambda w: (w["line"], w.get("type", ""), w.get("intrinsic", "")))
    if unkeyed:
        # Place each in the gap its neighbours leave: with keys present the
        # ordering is total, so an unkeyed entry can only take a remaining
        # slot. Zip below pairs them in finding order.
        remaining = [f for f in findings if not any(w.get("line") == f.line for w in keyed)]
        assert len(remaining) == len(unkeyed), (
            f"{case}: {len(unkeyed)} expectation(s) without a line, but "
            f"{len(remaining)} finding(s) unaccounted for"
        )
        order = sorted(
            order + unkeyed,
            key=lambda w: w.get("line", remaining[unkeyed.index(w)].line)
            if w in unkeyed else w["line"],
        )
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
    cases = {
        path.name
        for path in CASES.iterdir()
        if path.suffix in {".c", ".cc", ".cpp", ".h", ".hpp"}
    }
    assert cases == set(_expected())
