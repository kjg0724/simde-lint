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
    assert "is empty" in result.stderr + result.stdout


def test_an_already_failing_assertion_cannot_be_credited(tmp_path):
    """"It failed with the mutation applied" says nothing if it failed anyway.

    Watched happen: an entry's anchor drifted onto a different line after a
    refactor, the mutation landed somewhere harmless, and the run printed
    `caught` -- because the test it named was red at that moment for an
    unrelated reason. The anchor-uniqueness check could not see it; the string
    was unique, just no longer the right one.
    """
    catalogue = tmp_path / "already-red.yaml"
    catalogue.write_text(
        "faults:\n"
        "  - name: points_at_a_failing_test\n"
        "    file: tests/strict_yaml.py\n"
        '    find: "class EmptyCollection(Exception):"\n'
        '    replace: "class EmptyCollection(Exception):  # touched"\n'
        "    kills: tests/test_run_faults.py::test_that_does_not_exist\n"
    )
    result = _run(str(catalogue))
    assert result.returncode != 0
    assert "already fails without the mutation" in result.stderr + result.stdout


def test_an_anchor_that_appears_twice_is_refused(tmp_path):
    # `.replace(find, replace, 1)` mutates the first occurrence, which need
    # not be the one the entry describes. Ambiguity here is indistinguishable
    # afterwards from a mutation that did land where it was meant to.
    target = tmp_path / "twice.py"
    target.write_text("x = 1\nx = 1\n")
    catalogue = tmp_path / "ambiguous.yaml"
    catalogue.write_text(
        "faults:\n"
        "  - name: ambiguous\n"
        f"    file: {target}\n"
        '    find: "x = 1"\n'
        '    replace: "x = 2"\n'
        "    kills: tests/test_run_faults.py::test_an_empty_catalogue_is_not_a_pass\n"
    )
    result = _run(str(catalogue))
    assert result.returncode != 0
    assert "found 2 times" in result.stderr + result.stdout


def test_deleting_the_anchor_is_a_legitimate_mutation(tmp_path):
    """`replace: ""` removes the anchor, and must not read as a missing field.

    `sixteen-lane-family-unregistered` is written that way: the defect was two
    absent table rows, so the mutation deletes them. A required-field check
    that treated empty as missing rejected the whole shipped catalogue --
    caught here only because the acceptance run covers both catalogues, not
    the new one alone.
    """
    catalogue = tmp_path / "deletion.yaml"
    catalogue.write_text(yaml.safe_dump({"faults": [{
        "name": "deletes", "file": "tests/strict_yaml.py",
        "find": "class EmptyCollection(Exception):", "replace": "",
        "kills": "tests/test_run_faults.py::test_an_empty_catalogue_is_not_a_pass",
    }]}))
    result = _run(str(catalogue))
    assert "is missing" not in result.stderr + result.stdout


@pytest.mark.parametrize("missing", sorted(("name", "file", "find", "kills")))
def test_an_entry_missing_a_required_field_is_refused(tmp_path, missing):
    # A missing `kills` would credit the run to whatever node id `None`
    # resolves to, which pytest reports as an error rather than a pass -- so
    # every mutation would look caught.
    entry = {
        "name": "incomplete", "file": "tests/strict_yaml.py",
        "find": "import yaml", "replace": "import yaml  # touched",
        "kills": "tests/test_run_faults.py::test_an_empty_catalogue_is_not_a_pass",
    }
    del entry[missing]
    catalogue = tmp_path / "incomplete.yaml"
    catalogue.write_text(yaml.safe_dump({"faults": [entry]}))
    result = _run(str(catalogue))
    output = result.stderr + result.stdout
    assert result.returncode != 0
    # Asserting the key's name alone was not enough: without validation every
    # case dies of a KeyError whose traceback prints that same name, so this
    # passed with the guard removed. The sweep said so -- the first thing it
    # found that review had not.
    assert f"is missing {missing}" in output
    assert "Traceback" not in output, "must be refused, not crashed into"


def test_two_entries_with_one_name_are_refused(tmp_path):
    # "caught twin" would not say which of them was caught.
    entry = {
        "name": "twin", "file": "tests/strict_yaml.py",
        "find": "import yaml", "replace": "import yaml  # touched",
        "kills": "tests/test_run_faults.py::test_an_empty_catalogue_is_not_a_pass",
    }
    catalogue = tmp_path / "twins.yaml"
    catalogue.write_text(yaml.safe_dump({"faults": [entry, dict(entry)]}))
    result = _run(str(catalogue))
    assert result.returncode != 0
    assert "two entries named" in result.stderr + result.stdout


@pytest.mark.parametrize("catalogue", CATALOGUES)
def test_every_shipped_catalogue_parses_strictly_and_is_not_empty(catalogue):
    # The guards above protect against a catalogue going empty later; this
    # says the committed ones are not empty now, and that neither has
    # acquired a duplicate key since.
    faults = strict_yaml.load((ROOT / catalogue).read_text())["faults"]
    strict_yaml.require(faults, catalogue)
    names = [fault["name"] for fault in faults]
    assert len(names) == len(set(names)), f"{catalogue} repeats a name"
    for fault in faults:
        assert set(fault) >= {"name", "file", "find", "replace", "kills"}, (
            f"{catalogue}: {fault.get('name')} is missing a required field"
        )
