"""The mutation harness's own failure modes.

`run_faults.py` decides whether the assertions credited with catching past
defects still catch them. Every way it can report success without having
checked anything is a hole under the whole evidence base, and two of them are
not reachable by adding entries to a catalogue -- a catalogue cannot test the
code that reads catalogues.

The third, an anchor that does not match, is guarded inside `_apply` and
already has its own history: a YAML block scalar stripped indentation, the
mutation did not land, and the run reported success.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import strict_yaml
import yaml

ROOT = Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "run_faults.py"
CATALOGUES = ("tests/faults.yaml", "tests/runner_guards.yaml")


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HARNESS), *args], cwd=ROOT, capture_output=True, text=True
    )


def test_a_repeated_top_level_key_is_refused(tmp_path):
    """PyYAML keeps the last `faults:`, which would discard the earlier ones.

    This is the same defect a strict loader was written for in
    `test_oracle.py`, reopened by reading the new catalogue with `safe_load`
    -- which is why the loader is now shared rather than copied.

    The second list is non-empty on purpose. Written with `faults: []` as the
    duplicate, the emptiness guard below caught the file first and this test
    passed with the permissive loader restored -- pinning nothing. Here the
    surviving list is a real mutation, so only the loader can object, and the
    message is asserted rather than the exit code alone.
    """
    catalogue = tmp_path / "twice.yaml"
    catalogue.write_text(
        "faults:\n"
        "  - name: first\n    file: x\n    find: a\n    replace: b\n    kills: t\n"
        "faults:\n"
        "  - name: second\n    file: y\n    find: c\n    replace: d\n    kills: u\n"
    )
    surviving = yaml.safe_load(catalogue.read_text())["faults"]
    assert [f["name"] for f in surviving] == ["second"], (
        "the premise: the permissive loader keeps the last list and drops the first, "
        "leaving something non-empty so no other guard fires"
    )
    with pytest.raises(yaml.constructor.ConstructorError):
        strict_yaml.load(catalogue.read_text())

    result = _run(str(catalogue))
    assert result.returncode != 0
    assert "duplicate key" in result.stderr + result.stdout, (
        "must fail for the duplicate, not for some later consequence of it"
    )


def test_an_empty_catalogue_is_not_a_pass(tmp_path):
    # Zero mutations attempted is zero evidence, however it arose -- a
    # duplicate key, a bad merge, a file truncated in an edit. Exiting zero
    # there would make the CI step decorative.
    catalogue = tmp_path / "empty.yaml"
    catalogue.write_text("faults: []\n")
    result = _run(str(catalogue))
    assert result.returncode != 0
    assert "lists no mutations" in result.stderr + result.stdout


@pytest.mark.parametrize("catalogue", CATALOGUES)
def test_every_shipped_catalogue_parses_strictly_and_is_not_empty(catalogue):
    # The guards above protect against a catalogue going empty later; this
    # says the committed ones are not empty now, and that neither has
    # acquired a duplicate key since.
    faults = strict_yaml.load((ROOT / catalogue).read_text())["faults"]
    assert faults, f"{catalogue} lists no mutations"
    names = [fault["name"] for fault in faults]
    assert len(names) == len(set(names)), f"{catalogue} repeats a name"
    for fault in faults:
        assert set(fault) >= {"name", "file", "find", "replace", "kills"}, (
            f"{catalogue}: {fault.get('name')} is missing a required field"
        )
