"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .analyze import analyze, read_sources
from .finding import Evidence, Impact
from .knowledge import load_knowledge
from .report import render_json, render_text
from .symbols import build_symbol_index


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="simde-lint",
        description="Detect SIMDe emulation inefficiencies in x86 intrinsic code ported to ARM NEON",
    )
    parser.add_argument("paths", nargs="+", type=Path, help="files or directories to scan")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--type", default="", help="comma-separated taxonomy types, e.g. S,F")
    parser.add_argument("--min-evidence", choices=["A", "B", "C"], default="C")
    parser.add_argument("--impact", choices=["confirmed", "all"], default="all")
    parser.add_argument("--exclude", action="append", default=[], metavar="GLOB")
    parser.add_argument("--config", type=Path, help="JSON file with rule thresholds")
    parser.add_argument("--dump-symbols", action="store_true", help="print resolved constant arrays and exit")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

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

    findings, knowledge = analyze(
        args.paths,
        exclude=args.exclude,
        types=[t.strip() for t in args.type.split(",") if t.strip()] or None,
        min_evidence=Evidence(args.min_evidence),
        impact=Impact.CONFIRMED if args.impact == "confirmed" else None,
        config=config,
    )

    if args.format == "json":
        print(render_json(findings, simde_version=knowledge.simde_version))
    else:
        print(render_text(findings))
    return 0


if __name__ == "__main__":
    sys.exit(main())
