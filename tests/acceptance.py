"""Decide, by script, whether the oracle suite meets its stated condition.

The condition was proposed in these terms, and is quoted here because what
"done" means should not be adjustable by whoever runs the script:

    For the versioned seven-mechanism contract and committed coverage
    manifest, every mandatory case exists; every expected output field is
    checked; every mandatory relation passes; every named fault mutation is
    detected; and every discrepancy has a recorded resolution. The results
    establish conformance on this finite suite, not corpus-wide recall or
    freedom from shared assumptions.

Two of those clauses are narrower here than as written, because what the
suite actually decides is narrower, and the gap between them is where a green
run would start meaning more than it should:

- "every expected output field is checked" holds for the fields and for
  whether the counts exist, but not for the count values, which are asserted
  in one case only. `CLAUSES` and the printed exclusions say which.
- "every discrepancy has a recorded resolution" is not mechanically decidable.
  What is decided is that no discrepancy remains and that every case carries
  a `why`; nothing checks that a past disagreement and its settlement were
  written down.

The last sentence of the quotation is part of the condition rather than a
disclaimer attached to it. A green run says the corpus agrees with the tool on
the cases it contains and that no assertion in it is inert. It says nothing
about how many instances either of them misses in code neither has seen.

Each clause names the assertion that decides it, so a clause cannot pass by
some other test happening to be green -- the same reason `faults.yaml` names
the assertion each fault must die to.

    uv run python tests/acceptance.py

Runs the fault replay, which rewrites source files. Not part of the default
suite.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# clause -> what decides it. A pytest node id, or the fault replay.
CLAUSES = [
    (
        "every mandatory case exists",
        [
            "tests/test_oracle.py::test_every_cell_is_covered_or_a_named_gap",
            "tests/test_oracle.py::test_no_known_gap_is_already_covered",
            "tests/test_oracle.py::test_every_case_file_has_an_expectation",
        ],
    ),
    (
        "every expected output field is checked, except the counts named below",
        [
            "tests/test_oracle.py::test_an_expectation_only_uses_fields_this_runner_checks",
            "tests/test_oracle.py::test_an_expected_value_is_of_the_kind_its_field_takes",
            "tests/test_oracle.py::test_every_checked_field_is_asserted_by_a_case_or_declared_open",
            "tests/test_oracle.py::test_no_field_declared_unasserted_is_already_asserted",
            "tests/test_oracle.py::test_the_loader_refuses_a_repeated_key",
            "tests/test_oracle.py::test_every_asserted_field_is_load_bearing",
            "tests/test_oracle.py::test_a_dropped_or_invented_expectation_fails",
            "tests/test_oracle.py::test_every_finding_is_attributed_to_the_file_scanned",
        ],
    ),
    (
        "every mandatory relation passes",
        [
            "tests/test_oracle.py::test_every_mandatory_combination_is_met_by_one_case",
            "tests/test_oracle.py::test_every_declared_cell_is_a_cell_the_manifest_defines",
        ],
    ),
    (
        # Stated as what is actually decided. The agreement test being green
        # means nothing is open; the `why` assertion means every case has
        # reasoning. Neither checks that a past discrepancy and how it was
        # settled were written down, so the clause must not claim it.
        "no discrepancy remains, and every case carries its reasoning",
        [
            "tests/test_oracle.py::test_the_tool_agrees_with_the_hand_decided_expectation",
            "tests/test_oracle.py::test_a_broad_expectation_does_not_starve_a_narrow_one",
        ],
    ),
    ("every named fault mutation is detected", ["tests/run_faults.py"]),
]


def _check(target: str) -> bool:
    if target.endswith("run_faults.py"):
        command = [sys.executable, str(ROOT / target)]
    else:
        command = [sys.executable, "-m", "pytest", "-q", "--no-header", target]
    return subprocess.run(command, cwd=ROOT, capture_output=True).returncode == 0


def main() -> int:
    failed = []
    for clause, targets in CLAUSES:
        results = {target: _check(target) for target in targets}
        mark = "pass" if all(results.values()) else "FAIL"
        print(f"  {mark}  {clause}")
        for target, ok in results.items():
            print(f"          {'ok ' if ok else 'NO '} {target}")
        failed += [t for t, ok in results.items() if not ok]

    print()
    if failed:
        print(f"{len(failed)} check(s) failed: " + ", ".join(failed))
        return 1
    print("The acceptance condition holds on this suite, as narrowed below.")
    print()
    print("Excluded, and not closed by a green run here:")
    print("  - the instruction counts themselves, except `_mm_shuffle_epi8`,")
    print("    the one idiom short enough to count off the header. Rule M's")
    print("    entries are per chain element and turn on a modelling choice")
    print("    about the call site; see tests/oracle/README.md.")
    print("  - corpus-wide recall, and freedom from assumptions the corpus")
    print("    and the tool may share.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
