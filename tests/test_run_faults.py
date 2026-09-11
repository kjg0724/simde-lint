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
import run_faults
import yaml

from simde_lint import strictyaml

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
        strictyaml.load(catalogue.read_text())

    result = _run(str(catalogue))
    output = result.stderr + result.stdout
    assert result.returncode != 0
    assert "duplicate key" in output, (
        "must fail for the duplicate, not for some later consequence of it"
    )
    # An uncaught ConstructorError also prints "duplicate key", in a traceback.
    # Matching the phrase alone could not tell a deliberate refusal from a
    # crash, so the mutation that stops catching it went undetected.
    assert "Traceback" not in output, "must be refused, not crashed into"
    assert "PyYAML keeps the last one" in output


def test_an_empty_catalogue_is_not_a_pass(tmp_path):
    # Zero mutations attempted is zero evidence, however it arose -- a
    # duplicate key, a bad merge, a file truncated in an edit. Exiting zero
    # there would make the CI step decorative.
    catalogue = tmp_path / "empty.yaml"
    catalogue.write_text("faults: []\n")
    result = _run(str(catalogue))
    assert result.returncode != 0
    assert "is empty" in result.stderr + result.stdout


def _catalogue(tmp_path, **entry) -> Path:
    """A one-entry catalogue whose target is a file under `tmp_path`.

    Mutating a real source file to test the harness worked only because these
    run sequentially; under `pytest -n auto`, or on an interrupt between the
    write and the restore, the tree is left corrupted and the next entry's
    baseline is measured against it.
    """
    target = tmp_path / "subject.py"
    if not target.exists():
        target.write_text("VALUE = 1\n")
    entry.setdefault("file", str(target))
    catalogue = tmp_path / f"{entry['name']}.yaml"
    catalogue.write_text(yaml.safe_dump({"faults": [entry]}))
    return catalogue


def test_a_kills_that_collects_nothing_is_refused(tmp_path):
    # Distinct from an already-red assertion, and it used to be reported as
    # one: a typo'd node id sent a maintainer to debug a green test.
    catalogue = _catalogue(
        tmp_path, name="collects_nothing", find="VALUE = 1", replace="VALUE = 2",
        kills="tests/test_run_faults.py::test_that_does_not_exist",
    )
    result = _run(str(catalogue))
    assert result.returncode != 0
    assert "runs no tests" in result.stderr + result.stdout


def test_an_already_failing_assertion_cannot_be_credited(tmp_path):
    """"It failed with the mutation applied" says nothing if it failed anyway.

    Watched happen: an entry's anchor drifted onto a different line after a
    refactor, the mutation landed somewhere harmless, and the run printed
    `caught` -- because the test it named was red at that moment for an
    unrelated reason. The anchor-uniqueness check could not see it; the string
    was unique, just no longer the right one.

    The assertion here is genuinely red, not merely absent. Written with a
    node id that matched nothing, this exercised the collection path above
    instead and never reached the baseline comparison it is named for.
    """
    red = tmp_path / "test_red.py"
    red.write_text("def test_red():\n    assert False, 'red on purpose'\n")
    catalogue = _catalogue(
        tmp_path, name="points_at_a_failing_test", find="VALUE = 1", replace="VALUE = 2",
        kills=f"{red}::test_red",
    )
    result = _run(str(catalogue))
    output = result.stderr + result.stdout
    assert result.returncode != 0
    assert "already fails without the mutation" in output
    assert "runs no tests" not in output, "the node must be found, and red"


def test_a_mutation_that_breaks_collection_is_not_credited(tmp_path):
    """A mutation can fail a test by stopping it existing.

    Any non-zero pytest exit used to count, so a mutation that only broke an
    import was credited -- and every entry naming that file was credited at
    once. This is the mechanism that let a bogus mutation stand in for a real
    one in `runner_guards.yaml`.
    """
    green = tmp_path / "test_green.py"
    green.write_text("import subject\n\ndef test_green():\n    assert subject.VALUE == 1\n")
    catalogue = _catalogue(
        tmp_path, name="breaks_collection", find="VALUE = 1",
        replace="this is not python", kills=f"{green}::test_green",
    )
    result = _run(str(catalogue))
    output = result.stderr + result.stdout
    assert result.returncode != 0
    assert "changed what" in output and "runs (1 -> 0)" in output


def test_kills_must_name_an_assertion_not_a_file(tmp_path):
    """A whole file fails for any reason at all, including a broken import.

    The file named here is a throwaway under `tmp_path`, not this one. Pointing
    it at `tests/test_run_faults.py` made the guard's own mutation recurse:
    with the check disabled the harness ran every test in this file, one of
    which is this test, which spawns the harness again. It did not fail -- it
    forked until the machine was carrying several hundred pytest processes.
    """
    green = tmp_path / "test_green.py"
    green.write_text("def test_green():\n    assert True\n")
    catalogue = _catalogue(
        tmp_path, name="names_a_file", find="VALUE = 1", replace="VALUE = 2",
        kills=str(green),
    )
    result = _run(str(catalogue))
    assert result.returncode != 0
    assert "rather than an assertion" in result.stderr + result.stdout


def test_an_anchor_that_appears_twice_is_refused(tmp_path):
    # `.replace(find, replace, 1)` mutates the first occurrence, which need
    # not be the one the entry describes. Ambiguity here is indistinguishable
    # afterwards from a mutation that did land where it was meant to.
    target = tmp_path / "subject.py"
    target.write_text("VALUE = 1\nVALUE = 1\n")
    catalogue = _catalogue(
        tmp_path, name="ambiguous", find="VALUE = 1", replace="VALUE = 2",
        kills="tests/test_run_faults.py::test_an_empty_catalogue_is_not_a_pass",
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
    subject = tmp_path / "subject.py"
    subject.write_text("VALUE = 1\nGUARD = True\n")
    green = tmp_path / "test_green.py"
    green.write_text("import subject\n\ndef test_green():\n    assert subject.GUARD\n")
    catalogue = _catalogue(
        tmp_path, name="deletes", find="GUARD = True\n", replace="",
        kills=f"{green}::test_green",
    )
    result = _run(str(catalogue))
    output = result.stderr + result.stdout
    assert "is missing" not in output
    # The deletion has to have been performed and noticed, not merely not
    # refused: asserting the absence of one phrase said nothing about whether
    # anything happened.
    assert result.returncode == 0
    assert "caught  deletes" in output
    assert subject.read_text() == "VALUE = 1\nGUARD = True\n", "tree must be restored"


@pytest.mark.parametrize("missing", sorted(("name", "file", "find", "kills")))
def test_an_entry_missing_a_required_field_is_refused(tmp_path, missing):
    # A missing `kills` would credit the run to whatever node id `None`
    # resolves to, which pytest reports as an error rather than a pass -- so
    # every mutation would look caught.
    entry = {
        "name": "incomplete", "file": "tests/strictyaml.py",
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
        "name": "twin", "file": "tests/strictyaml.py",
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
    faults = strictyaml.load((ROOT / catalogue).read_text())["faults"]
    strictyaml.require(faults, catalogue)
    # Calls the validator rather than restating its rule. Retyping the
    # required-field set here meant a field added to `REQUIRED` would never be
    # checked against the shipped catalogues while this test went on reporting
    # that they "parse strictly" -- the same re-derivation that produced the
    # ninth inert assertion.
    run_faults._validate(faults, ROOT / catalogue)
