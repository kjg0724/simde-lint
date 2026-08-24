"""Analysis pipeline: discover, index symbols, extract, run rules."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Sequence

from .discover import discover_files
from .extract import extract_units
from .finding import Evidence, Finding, Impact
from .ir import AnalysisUnit
from .knowledge import Knowledge, load_knowledge
from .rules import ALL_RULES, Context, Rule
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


def _unit_location(unit: AnalysisUnit) -> str:
    """Identify a unit in a warning: its scope, name, and a start position.

    Scope and name alone are not enough to tell two units apart: a macro
    name redefined under separate `#if` branches (VVenC's `RdCostX86.h`
    `UNPACKX`, see docs/verification.md) yields two units sharing both, and
    a warning without a position would be two identical, unattributable
    lines.

    `FunctionUnit.start_line` is the real thing — the function_definition
    node's own line — read here via `getattr` since it is not part of the
    `AnalysisUnit` protocol every rule sees (rules have no need for a
    unit's own position, only its calls' and definitions'). `MacroUnit`
    carries no position of its own — extraction never stored the `#define`
    line, only its calls' — so the first call's line is the closest honest
    anchor available, labelled as such rather than presented as the
    macro's own start.
    """
    name = unit.function_name or unit.macro_name or unit.name
    start_line = getattr(unit, "start_line", None)
    if start_line:
        position = f"line {start_line}"
    elif unit.calls:
        position = f"first call at line {unit.calls[0].line}"
    else:
        position = "no calls recorded"
    return f"{unit.scope} {name!r} ({position})"


def _run_rule(
    rule: Rule, unit: AnalysisUnit, ctx: Context, path: str, errors: list[str]
) -> list[Finding]:
    """Run one rule over one unit, isolating a failure to that pair alone.

    `rule.match` is a generator: an exception can surface partway through
    iteration rather than at call time, so materializing it with `list(...)`
    has to be inside the guard too, not just the call that creates it. A
    malformed `Finding` from one rule on one unit — `Finding.__post_init__`
    raising is the new way this can happen, since v1.2 added it — must cost
    only that rule's results for that unit, never the other rules, the other
    units in the same file, or the other files in the sweep.
    """
    try:
        return list(rule.match(unit, ctx))
    except Exception as error:  # noqa: BLE001 - isolate one rule/unit pair, not the whole sweep
        message = f"{path}: rule {rule.rule_id} failed on {_unit_location(unit)}: {error}"
        print(f"warning: {message} -- this unit's {rule.rule_id} results are incomplete", file=sys.stderr)
        errors.append(message)
        return []


def analyze(
    paths: Sequence[Path | str],
    *,
    exclude: Sequence[str] = (),
    types: Sequence[str] | None = None,
    min_evidence: Evidence = Evidence.C,
    impact: Impact | None = None,
    config: dict[str, Any] | None = None,
) -> tuple[list[Finding], Knowledge, list[str]]:
    """Run the full pipeline and report what it found.

    The third return value is the list of warnings produced by an isolated
    extraction or rule failure (empty on a clean run) — callers that need to
    know whether the analysis was complete, rather than merely non-crashing,
    check this rather than inferring it from stderr output.
    """
    knowledge = load_knowledge()
    sources = read_sources(paths, exclude)

    ctx = Context(
        symbols=build_symbol_index(sources, knowledge),
        knowledge=knowledge,
        config=config or {},
    )

    errors: list[str] = []
    findings: list[Finding] = []
    for path, source in sources:
        try:
            units = extract_units(path, source, knowledge)
        except Exception as error:  # noqa: BLE001 - a bad file must not abort the sweep
            message = f"{path}: extraction failed: {error}"
            print(f"warning: skipping {path}: {error}", file=sys.stderr)
            errors.append(message)
            continue
        for unit in units:
            for rule in ALL_RULES:
                findings.extend(_run_rule(rule, unit, ctx, path, errors))

    if types:
        allowed = set(types)
        findings = [f for f in findings if f.type in allowed]
    findings = [f for f in findings if _EVIDENCE_ORDER[f.evidence] <= _EVIDENCE_ORDER[min_evidence]]
    if impact is not None:
        findings = [f for f in findings if f.impact is impact]
    return findings, knowledge, errors
