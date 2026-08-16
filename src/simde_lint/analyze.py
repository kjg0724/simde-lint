"""Analysis pipeline: discover, index symbols, extract, run rules."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Sequence

from .discover import discover_files
from .extract import extract_units
from .finding import Evidence, Finding, Impact
from .knowledge import Knowledge, load_knowledge
from .rules import ALL_RULES, Context
from .symbols import build_symbol_index

# Ordered by strictness. --min-evidence is a floor: passing "B" keeps grades
# A and B, not B alone, so the comparison below is <=, not ==.
_EVIDENCE_ORDER = {Evidence.A: 0, Evidence.B: 1, Evidence.C: 2}


def _read(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError as error:
        print(f"warning: cannot read {path}: {error}", file=sys.stderr)
        return None


def read_sources(
    paths: Sequence[Path | str], exclude: Sequence[str] = ()
) -> list[tuple[str, bytes]]:
    """Discover and read every scannable file, skipping the unreadable.

    Shared by the analysis pipeline and by --dump-symbols so both survive a
    file that cannot be read; one bad file must never abort a sweep.
    """
    sources: list[tuple[str, bytes]] = []
    for path in discover_files(paths, exclude):
        content = _read(path)
        if content is not None:
            sources.append((str(path), content))
    return sources


def analyze(
    paths: Sequence[Path | str],
    *,
    exclude: Sequence[str] = (),
    types: Sequence[str] | None = None,
    min_evidence: Evidence = Evidence.C,
    impact: Impact | None = None,
    config: dict[str, Any] | None = None,
) -> tuple[list[Finding], Knowledge]:
    knowledge = load_knowledge()
    sources = read_sources(paths, exclude)

    ctx = Context(
        symbols=build_symbol_index(sources, knowledge),
        knowledge=knowledge,
        config=config or {},
    )

    findings: list[Finding] = []
    for path, source in sources:
        try:
            units = extract_units(path, source, knowledge)
        except Exception as error:  # noqa: BLE001 - a bad file must not abort the sweep
            print(f"warning: skipping {path}: {error}", file=sys.stderr)
            continue
        for unit in units:
            for rule in ALL_RULES:
                findings.extend(rule.match(unit, ctx))

    if types:
        allowed = set(types)
        findings = [f for f in findings if f.type in allowed]
    findings = [f for f in findings if _EVIDENCE_ORDER[f.evidence] <= _EVIDENCE_ORDER[min_evidence]]
    if impact is not None:
        findings = [f for f in findings if f.impact is impact]
    return findings, knowledge
