"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .analyze import analyze, read_sources
from .finding import Evidence
from .knowledge import load_knowledge
from .report import render_json, render_text
from .symbols import build_symbol_index

_TYPES = ("R", "S", "W", "F", "M", "P")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="simde-lint",
        description="Detect SIMDe emulation inefficiencies in x86 intrinsic code ported to ARM NEON",
    )
    parser.add_argument("paths", nargs="+", type=Path, help="files or directories to scan")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument(
        "--sort",
        choices=["benchmarked", "file"],
        default="benchmarked",
        help="benchmarked-first (default): the types with a microbenchmarked speedup "
             "before the rest, then evidence, then location. "
        "file: the previous (file, line, type, rule) location order",
    )
    parser.add_argument("--type", default="", help="comma-separated taxonomy types, e.g. S,F")
    parser.add_argument("--min-evidence", choices=["A", "B", "C"], default="C")
    parser.add_argument("--exclude", action="append", default=[], metavar="GLOB")
    parser.add_argument("--config", type=Path, help="JSON file with rule thresholds")
    parser.add_argument("--dump-symbols", action="store_true", help="print resolved constant arrays and exit")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    types = [t.strip() for t in args.type.split(",") if t.strip()] or None
    if types is not None:
        unknown = sorted(set(types) - set(_TYPES))
        if unknown:
            parser.error(
                f"--type: unknown taxonomy type(s) {', '.join(unknown)}; "
                f"choose from {','.join(_TYPES)}"
            )

    config = {}
    if args.config:
        config = json.loads(args.config.read_text(encoding="utf-8"))

    if args.dump_symbols:
        knowledge = load_knowledge()
        # read_sources, not a bare read_bytes loop: this path must survive an
        # unreadable file exactly like the analysis path does.
        index = build_symbol_index(read_sources(args.paths, args.exclude), knowledge)
        for name in index.names():
            array = index.lookup(name)
            print(f"{array.name}\t{array.defined_at}\t{len(array.rows)} row(s)")
        return 0

    findings, knowledge, errors = analyze(
        args.paths,
        exclude=args.exclude,
        types=types,
        min_evidence=Evidence(args.min_evidence),
        config=config,
    )

    if args.format == "json":
        print(render_json(findings, simde_version=knowledge.simde_version, sort=args.sort))
    else:
        print(render_text(findings, sort=args.sort))

    # An isolated extraction or rule failure already printed its own warning
    # to stderr as it happened; the exit code is what makes "this run is
    # incomplete" distinguishable from a clean success without a reader
    # having to notice a warning line among the findings.
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
