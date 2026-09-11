"""Replay every historical fault and require the named assertion to catch it.

Each entry in `faults.yaml` is a defect that shipped. Most were false
negatives -- a predicate too restrictive, a family unregistered, a producer
retired too early -- and the guard-neutralisation used elsewhere does not
reach them, because making a predicate more permissive exercises false
positives only.

Requiring a *named* assertion, rather than "something fails", is what stops a
test being credited with catching a fault it fails for unrelated reasons.

    uv run python tests/run_faults.py [--only NAME]

Not part of the default suite: it rewrites source files and shells out to
pytest once per fault. CI runs it as its own step.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

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
    if fault["find"] not in original:
        raise SystemExit(
            f"{fault['name']}: anchor not found in {fault['file']}.\n"
            "A fault whose mutation does not land silently reports success, "
            "which is the failure this file exists to prevent."
        )
    path.write_text(original.replace(fault["find"], fault["replace"], 1))
    return original


def _run(node: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", node, "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True,
    )


def main() -> int:
    only = None
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1]

    faults = yaml.safe_load(CATALOGUE.read_text())["faults"]
    if only:
        faults = [f for f in faults if f["name"] == only]
        if not faults:
            raise SystemExit(f"no fault named {only}")

    undetected = []
    for fault in faults:
        path = ROOT / fault["file"]
        original = _apply(fault)
        try:
            baseline = _run(fault["kills"])
            caught = baseline.returncode != 0
        finally:
            path.write_text(original)
        mark = "caught" if caught else "MISSED"
        print(f"  {mark:7} {fault['name']}")
        if not caught:
            undetected.append(fault)

    print()
    if undetected:
        print(f"{len(undetected)} of {len(faults)} faults are not caught by the "
              "assertion credited with catching them:")
        for fault in undetected:
            print(f"  {fault['name']} -> {fault['kills']}")
        return 1
    print(f"all {len(faults)} historical faults caught")
    return 0


if __name__ == "__main__":
    sys.exit(main())
