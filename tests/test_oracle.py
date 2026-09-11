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
_ALLOWED_IN_A_CASE = frozenset({"why", "findings", "covers"})


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


def _manifest() -> dict:
    return yaml.safe_load((ORACLE / "coverage.yaml").read_text())


def _all_cells() -> set[str]:
    manifest = _manifest()
    return {
        f"{name}.{value}"
        for name, dimension in manifest["dimensions"].items()
        for value in dimension["values"]
    }


def _covered() -> set[str]:
    return {cell for case in _expected().values() for cell in case.get("covers", ())}


def test_every_declared_cell_is_a_cell_the_manifest_defines():
    # A typo in a `covers:` entry would otherwise inflate coverage silently,
    # the same way a typo in an expectation key once made a falsified
    # assertion pass.
    unknown = _covered() - _all_cells()
    assert not unknown, f"undefined cell(s) in `covers:` {sorted(unknown)}"


def test_every_cell_is_covered_or_a_named_gap():
    """Coverage is computed, not claimed.

    "The corpus covers all seven rules" was true and useless: every defect
    since has been a shape nobody had written down. A cell that is neither
    exercised nor listed as a gap fails here, so adding a dimension value is
    how a shape gets recorded before it is forgotten.
    """
    gaps = set(_manifest()["known_gaps"])
    missing = _all_cells() - _covered() - gaps
    assert not missing, (
        "cell(s) neither covered nor declared a gap: " + ", ".join(sorted(missing))
    )


def test_no_known_gap_is_already_covered():
    # A gap that a case now exercises is a stale entry. Left in place it
    # suppresses the failure that would otherwise demand the next case.
    stale = set(_manifest()["known_gaps"]) & _covered()
    assert not stale, f"stale known_gaps entry: {sorted(stale)}"


def test_every_mandatory_combination_is_met_by_one_case():
    """Pairs a past defect implicated, which no single cell would require.

    A combination has to be exercised by one case, not by two cases that
    each have half of it: the defects in this repository have been
    interactions, and splitting them across files is how they stayed
    invisible.
    """
    cases = {name: set(case.get("covers", ())) for name, case in _expected().items()}
    for combination in _manifest()["mandatory_combinations"]:
        wanted = set(combination)
        assert any(wanted <= cells for cells in cases.values()), (
            f"no single case covers {sorted(wanted)}"
        )
