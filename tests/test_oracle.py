"""The tool against expectations decided independently of it.

Every other test in this suite, and `docs/precision/verify.py` too, compares
the tool against a second reading built from the same inference. Both have
missed defects that shared their blind spot: `verify.py` could not see rule
F's nested multiply-add because its own predicate also required a named
product, and had to be extended alongside the rule.

`tests/oracle/expected.yaml` is written by hand from the rule descriptions
and the source, before the tool is run. It does not copy the tool's output and
can fail independently of it, which is the property nothing else here has. It
is not immune to sharing the implementation's assumptions: one person reading
one rule description twice can reach the same wrong answer twice.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from simde_lint import strictyaml
from simde_lint.analyze import analyze
from simde_lint.finding import Evidence, Reason

ORACLE = Path(__file__).parent / "oracle"
CASES = ORACLE / "cases"

_CHECKED = (
    "line",
    "type",
    "rule",
    "rule_mechanism",
    "evidence",
    "reason",
    "intrinsic",
    "suggestion",
    "simde_insns",
    "native_insns",
    "scope",
    "macro",
    "raw_name",
)
_RATIONALE = ("rationale_includes", "rationale_excludes")
# Whether the tool reports instruction counts at all, which is decidable from
# the SIMDe source without reading the tool's own table of numbers: a NEON
# branch exists for this intrinsic, or it does not. Most numbers themselves
# stay unasserted -- see README.md.
#
# Three values, not two. `partial` -- one count known, the other not -- is a
# state the reporter renders on purpose and `Finding` allows, so reading only
# `simde_insns` would file every partial finding under whichever of the other
# two happened to match, and a rule that started dropping one count would look
# unchanged.
_COSTS = ("reported", "withheld", "partial")
_ALLOWED_IN_A_FINDING = frozenset(_CHECKED) | frozenset(_RATIONALE) | {"costs"}
_ALLOWED_IN_A_CASE = frozenset({"why", "findings", "covers"})

_NULLABLE = frozenset(
    {"reason", "suggestion", "simde_insns", "native_insns", "macro", "raw_name"}
)
_INTEGER = frozenset({"line", "simde_insns", "native_insns"})
_VOCABULARY = {
    "type": frozenset("RSWFMP"),
    "evidence": frozenset(grade.value for grade in Evidence),
    "reason": frozenset(reason.value for reason in Reason),
    "scope": frozenset({"function", "macro"}),
}


def _expected(path: Path | None = None) -> dict:
    path = path or ORACLE / "expected.yaml"
    return strictyaml.require(strictyaml.load(path.read_text()), str(path))


def _actual(path: Path) -> list:
    findings, _, _ = analyze([path])
    return sorted(findings, key=lambda f: (f.line, f.type, f.intrinsic))


def _describe(finding) -> str:
    return (
        f"line {finding.line} {finding.type} {finding.evidence.value} "
        f"{finding.intrinsic}"
    )


def test_the_loader_refuses_a_repeated_key():
    # Verified here rather than trusted: PyYAML's default is to keep the last
    # value silently, and a subclass that forgot to register the constructor
    # would inherit exactly that behaviour while looking strict.
    with pytest.raises(yaml.constructor.ConstructorError):
        strictyaml.load("a:\n  x: 1\n  x: 2\n")


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


def _satisfies(finding, want: dict) -> str | None:
    """Why `finding` does not meet `want`, or None when it does.

    Membership decides whether a field is checked, so `suggestion: null`
    asserts that the tool reports no suggestion, while omitting the key
    asserts nothing. The two have to stay distinguishable: "no suggestion,
    on purpose" is a claim rule W and rule F both make, and a runner that
    read null as absent would let a withdrawn suggestion come back unseen.
    """
    for field in _CHECKED:
        if field not in want:
            continue
        actual = getattr(finding, field)
        if hasattr(actual, "value"):
            actual = actual.value
        if actual != want[field]:
            return f"{field} is {actual!r}, expected {want[field]!r}"
    if "costs" in want:
        known = (finding.simde_insns is not None, finding.native_insns is not None)
        got = {(True, True): "reported", (False, False): "withheld"}.get(known, "partial")
        if got != want["costs"]:
            return f"costs are {got}, expected {want['costs']}"
    if "rationale_includes" in want and want["rationale_includes"] not in finding.rationale:
        return f"rationale does not say {want['rationale_includes']!r}"
    if "rationale_excludes" in want and want["rationale_excludes"] in finding.rationale:
        return f"rationale still says {want['rationale_excludes']!r}"
    return None


def _match(findings: list, wanted: list[dict]) -> tuple[list, list, list[dict]]:
    """Pair each expectation with a distinct finding it fully describes.

    A matching, not a sort. Pairing by sorted order needed a key both sides
    could compute, which `line` is not -- it is optional, and where a
    mechanism anchors is not always something the contract fixes. One case
    passed only because its chain happened to anchor earliest of three.

    Maximum-cardinality by augmenting paths rather than greedy. Greedy over
    the most constrained expectation first is right on today's corpus and
    would report a spurious disagreement the first time two expectations
    overlapped without one being strictly narrower -- a failure that reads as
    the tool being wrong when it is the pairing that is. `shared_producers.c`
    already has two findings at one line differing only in `suggestion`, so
    that shape is one asserted field away.
    """
    candidates = [
        [i for i, finding in enumerate(findings) if _satisfies(finding, want) is None]
        for want in wanted
    ]
    taken: dict[int, int] = {}

    def assign(want: int, seen: set[int]) -> bool:
        for finding in candidates[want]:
            if finding in seen:
                continue
            seen.add(finding)
            if finding not in taken or assign(taken[finding], seen):
                taken[finding] = want
                return True
        return False

    for want in range(len(wanted)):
        assign(want, set())

    matched = {want: finding for finding, want in taken.items()}
    paired = [(wanted[w], findings[f]) for w, f in sorted(matched.items())]
    extra = [f for i, f in enumerate(findings) if i not in taken]
    missing = [w for i, w in enumerate(wanted) if i not in matched]
    return paired, extra, missing


def test_a_broad_expectation_does_not_starve_a_narrow_one():
    """The reason the pairing is a matching and not a first-fit.

    Two findings differ in one field. The broad expectation names neither
    finding uniquely; the narrow one names the first. Taken in order, the
    broad one claims the first finding and the narrow one is left with
    nothing -- a reported disagreement with the tool that is really an
    artefact of which expectation was written first. `shared_producers.c` has
    two findings at one line differing only in `suggestion`, so this is one
    asserted field away from being a real case rather than a constructed one.
    """
    from simde_lint.finding import Evidence, Finding

    def finding(suggestion):
        return Finding(
            type="W", rule="W.round_trip", rule_mechanism="round-trip",
            evidence=Evidence.A, file="a.c", line=8, function="f",
            intrinsic="_mm_mullo_epi16", rationale="why",
            simde_insns=5, native_insns=1, suggestion=suggestion,
        )

    findings = [finding("vmull_s16"), finding("vmull_high_s16")]
    broad = {"line": 8, "type": "W"}
    narrow = {"line": 8, "type": "W", "suggestion": "vmull_s16"}

    paired, extra, missing = _match(findings, [broad, narrow])
    assert not extra and not missing, "a perfect pairing exists and was not found"
    assert dict(
        (want["suggestion"], f.suggestion) for want, f in paired if "suggestion" in want
    ) == {"vmull_s16": "vmull_s16"}


@pytest.mark.parametrize("case", sorted(_expected()))
def test_the_tool_agrees_with_the_hand_decided_expectation(case):
    expectation = _expected()[case]
    assert expectation.get("why"), f"{case}: an expectation needs its reasoning"
    findings = _actual(CASES / case)
    wanted = expectation["findings"]

    _, extra, missing = _match(findings, wanted)

    if missing:
        detail = []
        for want in missing:
            near = sorted(
                ((_satisfies(f, want) or "", f) for f in findings),
                key=lambda pair: len(pair[0]),
            )
            reason = near[0][0] if near else "no findings at all"
            detail.append(f"{want} -- closest finding: {reason}")
        raise AssertionError(f"{case}: expected but not found:\n  " + "\n  ".join(detail))
    assert not extra, (
        f"{case}: findings nothing expected:\n  "
        + "\n  ".join(_describe(f) for f in extra)
    )


@pytest.mark.parametrize("case", sorted(_expected()))
def test_an_expected_value_is_of_the_kind_its_field_takes(case):
    """A well-spelled key holding a wrong-kind value asserts nothing useful.

    `evidence: AB` or `reason: guard-required` (hyphen, not underscore) name
    a field the runner checks, so the key test above passes them, and the
    comparison then reports a disagreement with the tool that is really a
    typo in the expectation. Worse in the other direction: `line: "12"`
    compares a string against an int and can never hold, so it would fail
    forever for a reason nobody would read as "the expectation is malformed".
    """
    for want in _expected()[case]["findings"]:
        for field, value in want.items():
            if field == "costs":
                assert value in _COSTS, (
                    f"{case}: costs must be one of {list(_COSTS)}, got {value!r}"
                )
                continue
            if field in _RATIONALE:
                assert isinstance(value, str) and value, (
                    f"{case}: {field} must be a non-empty string, got {value!r}"
                )
                continue
            if value is None:
                assert field in _NULLABLE, (
                    f"{case}: {field} has no null meaning -- the tool always sets it"
                )
                continue
            if field in _INTEGER:
                assert isinstance(value, int) and not isinstance(value, bool), (
                    f"{case}: {field} must be an integer, got {value!r}"
                )
            else:
                assert isinstance(value, str), (
                    f"{case}: {field} must be a string, got {value!r}"
                )
            if field in _VOCABULARY:
                assert value in _VOCABULARY[field], (
                    f"{case}: {field} {value!r} is not one of "
                    f"{sorted(_VOCABULARY[field])}"
                )


def _corruptions(want: dict, finding) -> list[tuple[str, dict]]:
    """Every single-field change to `want` that its paired finding refutes."""
    out = []
    for field, value in want.items():
        if field == "costs":
            broken = next(other for other in _COSTS if other != value)
        elif field == "rationale_includes":
            broken = "a phrase no rationale contains"
        elif field == "rationale_excludes":
            broken = finding.rationale
        elif value is None:
            broken = 0 if field in _INTEGER else "something"
        elif field in _INTEGER:
            broken = value + 1
        elif field in _VOCABULARY:
            other = sorted(_VOCABULARY[field] - {value})
            broken = other[0]
        else:
            broken = value + "_not"
        out.append((field, {**want, field: broken}))
    return out


@pytest.mark.parametrize("case", sorted(_expected()))
def test_every_asserted_field_is_load_bearing(case):
    """Each field in each expectation, falsified one at a time, must fail.

    Six assertions have shipped here that could not fail -- an ordering guard
    that went inert twice, and four expectation keys misspelled past a runner
    that ignored what it did not recognise. Both were invisible because a
    passing test and a vacuous one look identical. This corrupts every field
    the corpus asserts and requires the comparison to notice, which is the
    only evidence that the corpus is checking what it claims to check.

    It corrupts the expectation rather than the tool, so it says nothing
    about whether the tool is right -- `tests/faults.yaml` does that. What it
    establishes is narrower and was missing: that no assertion here is inert.
    """
    findings = _actual(CASES / case)
    wanted = _expected()[case]["findings"]
    paired, extra, missing = _match(findings, wanted)
    assert not extra and not missing, f"{case}: fix the expectation before mutating it"

    for want, finding in paired:
        for field, broken in _corruptions(want, finding):
            assert _satisfies(finding, broken) is not None, (
                f"{case}: {field}={want.get(field)!r} is not load-bearing -- "
                f"its paired finding satisfies the corrupted expectation too"
            )
            others = [w for w in wanted if w is not want] + [broken]
            _, still_extra, still_missing = _match(findings, others)
            assert still_extra or still_missing, (
                f"{case}: corrupting {field} left the case passing -- some "
                "other finding absorbed the corrupted expectation"
            )


@pytest.mark.parametrize("case", sorted(_expected()))
def test_a_dropped_or_invented_expectation_fails(case):
    """The count is asserted, not just the content of what was listed.

    A rule that starts reporting one extra finding per call site is the
    failure mode this corpus was built for, and a runner that only checked
    the findings it was told about would not see it. Nor would it see an
    expectation quietly deleted to make a red case green.
    """
    findings = _actual(CASES / case)
    wanted = _expected()[case]["findings"]

    for dropped in range(len(wanted)):
        shorter = [w for i, w in enumerate(wanted) if i != dropped]
        _, extra, _ = _match(findings, shorter)
        assert extra, f"{case}: dropping expectation {dropped} went unnoticed"

    invented = {"type": "R", "line": max((f.line for f in findings), default=0) + 1000}
    _, _, missing = _match(findings, [*wanted, invented])
    assert missing, f"{case}: an invented expectation was matched by something"


def _is_attributed_to(finding, path: Path) -> bool:
    """Whether `finding` was recorded against `path`.

    One function, called by the check below and by the counterexample that
    proves the check is the strict one. Written separately first, the two
    shared no code: reverting this comparison to `Path(...).name` left both
    green, because the counterexample was re-deriving two facts about `Path`
    instead of exercising what the corpus runs.
    """
    return Path(finding.file).resolve() == path.resolve()


@pytest.mark.parametrize("case", sorted(_expected()))
def test_every_finding_is_attributed_to_the_file_scanned(case):
    """`file` is in the tuple #48 names and nothing was comparing it.

    Each case is one file and the runner scans exactly that file, so the
    attribution looked true by construction -- which is a reason to check it,
    not to skip it. A finding is a chain of call sites, and the rule decides
    which one it anchors at; nothing in the rules forces that anchor to be in
    the file the scan started from once headers are involved. An expectation
    cannot state this, because the expectation is keyed by the file, so it
    goes here instead of in `_CHECKED`. The whole path is compared, not the
    basename: a different tree holding a file of the same name is exactly the
    attribution this is meant to catch.
    """
    for finding in _actual(CASES / case):
        assert _is_attributed_to(finding, CASES / case), (
            f"{case}: a finding is attributed to {finding.file}"
        )


def test_the_attribution_check_reads_the_path_and_not_the_name():
    """A same-named file in another tree must not count as attributed.

    Calls `_is_attributed_to`, which is the point: the first version of this
    test re-derived the `Path` comparison itself, so reverting the check to a
    basename comparison left it passing. That is the ninth inert guard in this
    repository, and it was added in the commit that fixed the eighth.
    """
    import dataclasses

    case = CASES / "shuffle_guard.c"
    findings = _actual(case)
    assert findings, "the fixture must produce something to move"
    moved = dataclasses.replace(findings[0], file="/wrong/tree/shuffle_guard.c")
    assert Path(moved.file).name == case.name, "the counterexample must share the name"
    assert not _is_attributed_to(moved, case)


def test_every_case_file_has_an_expectation():
    # A .c file with no entry would be scanned by nothing and look like
    # coverage. The oracle is only as good as its completeness.
    cases = {
        path.name
        for path in CASES.iterdir()
        if path.suffix in {".c", ".cc", ".cpp", ".h", ".hpp"}
    }
    assert cases == set(_expected())


# Only the collections a check quantifies over *positively*. `known_gaps` and
# `unasserted_fields` are deliberately excluded: they are exception lists,
# subtracted from what the checks demand, so emptying one makes the suite
# stricter rather than vacuous -- and an empty one is the goal state, every
# gap closed. Requiring them non-empty would forbid ever finishing.
MANIFEST_COLLECTIONS = ("dimensions", "mandatory_combinations")


def _manifest(path: Path | None = None) -> dict:
    path = path or ORACLE / "coverage.yaml"
    manifest = strictyaml.load(path.read_text())
    for key in MANIFEST_COLLECTIONS:
        strictyaml.require(manifest.get(key), f"{path.name}: {key}")
    for name, dimension in manifest["dimensions"].items():
        strictyaml.require(dimension.get("values"), f"{path.name}: {name}.values")
    for index, combination in enumerate(manifest["mandatory_combinations"]):
        # An empty combination is `set() <= cells`, true for every case, so it
        # would report itself met without naming anything.
        strictyaml.require(combination, f"{path.name}: mandatory_combinations[{index}]")
    return manifest


def _all_cells(path: Path | None = None) -> set[str]:
    # No `require` here: `_manifest` already refuses an empty `dimensions` and
    # any dimension with no values, and those two together make this set
    # non-empty. A guard with no reachable scenario reports coverage it does
    # not have, and the one that was here was credited to a failure raised by
    # a different call site.
    manifest = _manifest(path)
    return {
        f"{name}.{value}"
        for name, dimension in manifest["dimensions"].items()
        for value in dimension["values"]
    }


def _covered(path: Path | None = None) -> set[str]:
    # Quantified over by two tests that compare it against the manifest. If
    # every `covers:` key vanished, both would compare empty against empty.
    return strictyaml.require(
        {cell for case in _expected(path).values() for cell in case.get("covers", ())},
        "the cells cases declare",
    )


def _manifest_text(**emptied) -> str:
    """The real manifest with some collections replaced by empty ones."""
    manifest = strictyaml.load((ORACLE / "coverage.yaml").read_text())
    manifest.update(emptied)
    return yaml.safe_dump(manifest)


@pytest.mark.parametrize("key", MANIFEST_COLLECTIONS)
def test_an_emptied_manifest_collection_is_refused(tmp_path, key):
    """Each collection the checks quantify over, emptied, must be refused.

    Without these the guards were unreachable. `coverage.yaml` on disk is not
    empty, so nothing exercised them, and neutralising `require` entirely left
    504 tests passing -- the guards were present, unfalsifiable, and counted as
    covered. That is the tenth inert assertion in this repository, and it
    shipped in the commit whose changelog documents the ninth.
    """
    path = tmp_path / "coverage.yaml"
    path.write_text(_manifest_text(**{key: {} if key != "mandatory_combinations" else []}))
    with pytest.raises(strictyaml.EmptyCollection, match=key):
        _manifest(path)


def test_an_emptied_dimension_is_refused(tmp_path):
    # A dimension with no values contributes no cells, so the coverage checks
    # stop asking about that whole axis while the manifest still lists it.
    manifest = strictyaml.load((ORACLE / "coverage.yaml").read_text())
    name = sorted(manifest["dimensions"])[0]
    manifest["dimensions"][name]["values"] = {}
    path = tmp_path / "coverage.yaml"
    path.write_text(yaml.safe_dump(manifest))
    with pytest.raises(strictyaml.EmptyCollection, match=f"{name}.values"):
        _manifest(path)


def test_an_empty_mandatory_combination_is_refused(tmp_path):
    # `set() <= cells` holds for every case, so an empty combination reports
    # itself met by all of them without naming a single cell.
    manifest = strictyaml.load((ORACLE / "coverage.yaml").read_text())
    manifest["mandatory_combinations"].append([])
    path = tmp_path / "coverage.yaml"
    path.write_text(yaml.safe_dump(manifest))
    with pytest.raises(strictyaml.EmptyCollection, match=r"mandatory_combinations\[\d+\]"):
        _manifest(path)


def test_emptied_expectations_are_refused(tmp_path):
    # Every per-case test is parametrized over this mapping, so emptying it
    # removes the tests rather than failing them -- pytest reports success on
    # a suite that no longer contains them.
    path = tmp_path / "expected.yaml"
    path.write_text("{}\n")
    with pytest.raises(strictyaml.EmptyCollection):
        _expected(path)


def test_a_minimal_manifest_still_produces_cells(tmp_path):
    # Named for what it checks. It was `..._with_no_cells_is_refused`, back
    # when `_all_cells` carried its own emptiness guard -- but that guard had
    # no reachable scenario, since `_manifest` already refuses an empty
    # `dimensions` and any dimension with no values, and those two together
    # make this set non-empty. The guard is gone; this pins the implication.
    manifest = strictyaml.load((ORACLE / "coverage.yaml").read_text())
    manifest["dimensions"] = {"d": {"applies_to": ["R"], "why": "x", "values": {"v": "y"}}}
    path = tmp_path / "coverage.yaml"
    path.write_text(yaml.safe_dump(manifest))
    assert _all_cells(path) == {"d.v"}, "the fixture must still produce cells"


def test_cases_that_declare_no_cells_are_refused(tmp_path):
    # `_covered()` is compared against the manifest by two tests. With every
    # `covers:` key gone they compare empty against empty and both pass.
    expected = strictyaml.load((ORACLE / "expected.yaml").read_text())
    for case in expected.values():
        case.pop("covers", None)
    path = tmp_path / "expected.yaml"
    path.write_text(yaml.safe_dump(expected))
    with pytest.raises(strictyaml.EmptyCollection):
        _covered(path)


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


def _asserted_fields() -> set[str]:
    return strictyaml.require({
        field
        for case in _expected().values()
        for want in case["findings"]
        for field in want
    }, "the fields cases assert")


def test_every_checked_field_is_asserted_by_a_case_or_declared_open():
    """A field the runner checks that nothing uses is a checked field in name.

    Four of these were added at once when the runner grew to cover the whole
    output contract #48 names. Adding the capability is not the same as
    exercising it, and the difference is invisible: the runner reports no
    error for a field no expectation mentions.
    """
    declared = set(_manifest()["unasserted_fields"])
    idle = (set(_CHECKED) | set(_RATIONALE)) - _asserted_fields() - declared
    assert not idle, (
        "field(s) the runner checks that no case asserts and nothing explains: "
        + ", ".join(sorted(idle))
    )


def test_no_field_declared_unasserted_is_already_asserted():
    # The mirror of the stale-gap test: an entry left behind once a case
    # starts asserting the field suppresses the failure that would demand the
    # next one.
    stale = set(_manifest()["unasserted_fields"]) & _asserted_fields()
    assert not stale, f"stale unasserted_fields entry: {sorted(stale)}"


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
