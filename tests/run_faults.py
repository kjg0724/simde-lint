"""Replay every historical fault and require the named assertion to catch it.

Each entry in `faults.yaml` is a defect that shipped. Most were false
negatives -- a predicate too restrictive, a family unregistered, a producer
retired too early -- and the guard-neutralisation used elsewhere does not
reach them, because making a predicate more permissive exercises false
positives only.

Requiring a *named* assertion, rather than "something fails", is what stops a
test being credited with catching a fault it fails for unrelated reasons.

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

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import strict_yaml
import yaml  # noqa: F401  -- `runner_guards.yaml` mutates the loader back to this

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


def _apply(fault: dict) -> str:
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


def _run(node: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", node, "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True,
    )


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

    faults = strict_yaml.load(catalogue.read_text())["faults"]
    try:
        strict_yaml.require(faults, f"{catalogue}: faults")
    except strict_yaml.EmptyCollection as empty:
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
    for fault in faults:
        path = ROOT / fault["file"]
        # The named assertion has to pass before the mutation, or "it failed
        # with the mutation applied" says nothing. An entry whose anchor had
        # drifted onto a different line reported `caught` here purely because
        # its target test was already red for an unrelated reason.
        if _run(fault["kills"]).returncode != 0:
            raise SystemExit(
                f"{fault['name']}: {fault['kills']} already fails without the "
                "mutation, so it cannot be credited with catching it."
            )
        original = _apply(fault)
        try:
            caught = _run(fault["kills"]).returncode != 0
        finally:
            path.write_text(original)
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
