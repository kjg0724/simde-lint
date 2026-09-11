"""Replay every historical fault and require the named assertion to catch it.

Each entry in `faults.yaml` is a defect that shipped. Most were false
negatives -- a predicate too restrictive, a family unregistered, a producer
retired too early -- and the guard-neutralisation used elsewhere does not
reach them, because making a predicate more permissive exercises false
positives only.

Requiring a *named* assertion, rather than "something fails", is most of what
stops a test being credited with catching a fault it fails for unrelated
reasons. The rest had to be added after two in-tree instances of exactly the
thing this sentence used to claim was already prevented: the name must reach
an assertion (`::`, not a bare filename), it must collect the same tests
before and after, it must pass before the mutation, and it must then fail
rather than merely exit non-zero -- an import the mutation breaks is not a
test deciding against the code.

    uv run python tests/run_faults.py [CATALOGUE] [--only NAME]

`faults.yaml` is the default and holds defects that reached a release.
`runner_guards.yaml` holds the same shape aimed at the oracle runner itself:
those are not shipped defects but guards whose inertness would be invisible,
which is how a counterexample test that re-derived its comparison instead of
calling it passed while the comparison it claimed to pin was reverted.

Not part of the default suite: it rewrites source files and shells out to
pytest once per fault. CI runs it as its own step.
"""
from __future__ import annotations

import re
import signal
import subprocess
import sys
from pathlib import Path

import yaml  # noqa: F401  -- `runner_guards.yaml` mutates the loader back to this

from simde_lint import strictyaml

ROOT = Path(__file__).resolve().parent.parent
CATALOGUE = Path(__file__).parent / "faults.yaml"


def _reindent(text: str, spaces: int) -> str:
    """Put back the indentation a YAML block scalar removed.

    A block scalar strips the indent of its first content line, which is not
    the indent the source has. Encoding it in whitespace made two anchors
    silently wrong; `indent:` states it instead.
    """
    if not spaces:
        return text
    pad = " " * spaces
    return "".join(pad + line if line.strip() else line for line in text.splitlines(keepends=True))


def _apply(fault: dict, in_flight: dict[Path, str] | None = None) -> str:
    path = ROOT / fault["file"]
    original = path.read_text()
    indent = fault.get("indent", 0)
    fault["find"] = _reindent(fault["find"], indent)
    fault["replace"] = _reindent(fault["replace"], indent)
    occurrences = original.count(fault["find"])
    if occurrences != 1:
        found = "not found" if occurrences == 0 else f"found {occurrences} times"
        raise SystemExit(
            f"{fault['name']}: anchor {found} in {fault['file']}.\n"
            "A fault whose mutation does not land silently reports success, "
            "and one that lands somewhere else reports the wrong thing. "
            "Both are the failure this file exists to prevent."
        )
    # Registered before the write, not after. Registering afterwards left a
    # window in which a signal arrived with the file already mutated and
    # nothing recorded to restore it -- reintroducing, inside the handler that
    # exists to prevent it, the failure that put `if False:` in the tree.
    if in_flight is not None:
        in_flight[path] = original
    path.write_text(original.replace(fault["find"], fault["replace"], 1))
    return original


REQUIRED = ("name", "file", "find", "replace", "kills")
# `replace` is the one that may legitimately be empty: deleting the anchor is
# how an unregistered family or a dropped guard is expressed, and
# `sixteen-lane-family-unregistered` does exactly that. The others carry no
# meaning empty -- an empty `find` matches everywhere.
MAY_BE_EMPTY = frozenset({"replace"})


def _validate(faults: list[dict], catalogue: Path) -> None:
    """Refuse a catalogue that cannot mean what it says.

    Each of these turns a mutation into a silent no-op or a mutation of the
    wrong thing, and `_apply` cannot tell afterwards which happened. A missing
    `kills` would credit the run to whatever pytest node id `None` resolves
    to; a repeated name makes "caught" ambiguous between two entries; an
    anchor occurring twice mutates the first, which need not be the one the
    entry describes.
    """
    seen: set[str] = set()
    for index, fault in enumerate(faults):
        missing = [
            key
            for key in REQUIRED
            if key not in fault
            or (not fault[key] and key not in MAY_BE_EMPTY)
        ]
        if missing:
            raise SystemExit(
                f"{catalogue}: entry {index} ({fault.get('name', 'unnamed')}) "
                f"is missing {', '.join(missing)}"
            )
        if fault["name"] in seen:
            raise SystemExit(f"{catalogue}: two entries named {fault['name']!r}")
        seen.add(fault["name"])
        if "::" not in fault["kills"]:
            raise SystemExit(
                f"{catalogue}: {fault['name']} names {fault['kills']!r}, which is a "
                "file rather than an assertion. A whole file fails for any reason "
                "at all, including a mutation that only breaks the import, so "
                "crediting one says nothing about what the mutation did."
            )


# pytest's exit codes. Only `FAILED` is a test deciding against the code; the
# rest are the run never reaching that decision, and crediting them is how a
# mutation that merely breaks an import gets reported as caught.
FAILED = 1

def _run(node: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", node, "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True,
    )


# Only outcomes of a test that actually executed. An `error` is collection or
# a fixture failing, which is the run never reaching the assertion -- counting
# those as "ran" let a mutation that broke an import keep the count unchanged
# and slip past the comparison below.
_COUNT = re.compile(r"(\d+) (passed|failed|xfailed|xpassed)\b")


def _ran(run: subprocess.CompletedProcess) -> int:
    """How many tests actually ran, from pytest's own summary line.

    Read out of the run already performed rather than measured with a second
    `--collect-only` pass. These tests spawn this harness, which spawns
    pytest, so an extra invocation per entry is not a constant cost: the first
    version multiplied at every level of that nesting and left 357 pytest
    processes alive.
    """
    return sum(int(count) for count, _ in _COUNT.findall(run.stdout))


def _restore_on_interrupt(paths: dict[Path, str]):
    """Put every mutated file back if the run is killed.

    `finally` does not run for SIGTERM, and a killed run left a guard
    neutralised in the working tree -- where the next run would measure its
    baseline against it, and where it could be committed by accident.
    """
    def handler(signum, _frame):
        for path, text in paths.items():
            path.write_text(text)
        raise SystemExit(
            f"interrupted (signal {signum}); restored {len(paths)} file(s)"
        )
    return handler


def main() -> int:
    argv = sys.argv[1:]
    only = None
    if "--only" in argv:
        index = argv.index("--only")
        only = argv[index + 1]
        argv = argv[:index] + argv[index + 2:]
    catalogue = Path(argv[0]) if argv else CATALOGUE
    if not catalogue.is_absolute():
        catalogue = ROOT / catalogue if (ROOT / catalogue).exists() else catalogue

    try:
        document = strictyaml.load(catalogue.read_text())
    except yaml.constructor.ConstructorError as clash:
        # Refused deliberately rather than crashed into. Letting this escape
        # made the test that checks it match on the source line Python echoes
        # in the traceback, not on anything the harness meant to say.
        where = str(clash.problem_mark).strip().splitlines()[0]
        raise SystemExit(
            f"{catalogue}: {clash.problem} ({where}). PyYAML keeps the last "
            "one, so the entries before it would vanish without a word."
        ) from None
    faults = document["faults"]
    try:
        strictyaml.require(faults, f"{catalogue}: faults")
    except strictyaml.EmptyCollection as empty:
        raise SystemExit(
            f"{empty}\nAn empty catalogue would print 'all 0 mutations caught' "
            "and exit zero, which is the silent success this file exists to "
            "prevent."
        ) from None
    _validate(faults, catalogue)
    if only:
        faults = [f for f in faults if f["name"] == only]
        if not faults:
            raise SystemExit(f"no fault named {only}")

    undetected = []
    in_flight: dict[Path, str] = {}
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, _restore_on_interrupt(in_flight))

    for fault in faults:
        path = ROOT / fault["file"]
        # The named assertion has to pass before the mutation, or "it failed
        # with the mutation applied" says nothing. An entry whose anchor had
        # drifted onto a different line reported `caught` here purely because
        # its target test was already red for an unrelated reason.
        baseline = _run(fault["kills"])
        before = _ran(baseline)
        if before < 1:
            raise SystemExit(
                f"{fault['name']}: {fault['kills']} runs no tests, so there is "
                "no assertion for the mutation to fail."
            )
        if baseline.returncode != 0:
            raise SystemExit(
                f"{fault['name']}: {fault['kills']} already fails without the "
                f"mutation (exit {baseline.returncode}), so it cannot be "
                "credited with catching it."
            )
        original = _apply(fault, in_flight)
        try:
            after = _run(fault["kills"])
            # The same tests must still run: a mutation that breaks the import
            # makes every entry naming that file look caught at once, which is
            # how a mutation deleting a function argument was credited for
            # neutralising a guard it never reached.
            if _ran(after) != before:
                raise SystemExit(
                    f"{fault['name']}: the mutation changed what "
                    f"{fault['kills']} runs ({before} -> {_ran(after)}), so the "
                    "failure is a broken run rather than an assertion deciding "
                    "against the code."
                )
            # Narrower than `!= 0` deliberately, though the count check above
            # reaches every scenario found so far: a run that never gets to
            # the assertion also changes how many tests ran. Kept as the
            # precise statement of what counts, and `runner_guards.yaml`
            # carries no entry for it -- nothing can falsify it on its own,
            # and an unfalsifiable entry would report coverage it does not
            # have.
            caught = after.returncode == FAILED
        finally:
            path.write_text(original)
            in_flight.pop(path, None)
        mark = "caught" if caught else "MISSED"
        print(f"  {mark:7} {fault['name']}")
        if not caught:
            undetected.append(fault)

    print()
    if undetected:
        print(f"{len(undetected)} of {len(faults)} mutations in {catalogue.name} "
              "are not caught by the assertion credited with catching them:")
        for fault in undetected:
            print(f"  {fault['name']} -> {fault['kills']}")
        return 1
    print(f"all {len(faults)} mutations in {catalogue.name} caught")
    return 0


if __name__ == "__main__":
    sys.exit(main())
