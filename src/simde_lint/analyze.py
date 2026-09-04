"""Analysis pipeline: discover, index symbols, extract, run rules."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Sequence

from .discover import discover_files
from .extract import extract_units_and_diagnostics
from .finding import Evidence, Finding
from .ir import AnalysisUnit
from .knowledge import Knowledge, load_knowledge
from .rules import ALL_RULES, Context, Rule, validate_config
from .symbols import build_symbol_index

# Ordered by strictness. --min-evidence is a floor: passing "B" keeps grades
# A and B, not B alone, so the comparison below is <=, not ==.
_EVIDENCE_ORDER = {Evidence.A: 0, Evidence.B: 1, Evidence.C: 2}

# A file can carry many unparsed spans; a warning naming all of them would
# bury the file name it is about. The count is always reported, so nothing
# is hidden by the cap — only shortened.
_MAX_REPORTED_SPANS = 3


class Diagnostic(str):
    """A warning about an incomplete run, carrying why without ceasing to be
    a message.

    Two things go wrong in a sweep and they are not the same thing. A
    FAILURE is the tool breaking on input it should have handled: a file it
    could not read, an extraction that raised, a rule that raised. An
    UNPARSED is tree-sitter declining to parse a construct, recovering, and
    returning a tree anyway — the tool worked, and the findings it produced
    are real; what is missing is the assurance that they are all of them.

    Only a FAILURE may set the exit code. Preprocessor-heavy C++ makes
    UNPARSED the normal case rather than the exceptional one — 362 of
    SVT-AV1's 561 files at the pinned revision — so an exit code that
    counted them would be 1 on nearly every real sweep and would say
    nothing.

    Subclassing `str` rather than wrapping it keeps every existing consumer
    working unchanged: these are still printed, still substring-matched,
    still collected into a plain list.
    """

    FAILURE = "failure"
    UNPARSED = "unparsed"

    kind: str

    def __new__(cls, message: str, kind: str) -> "Diagnostic":
        diagnostic = super().__new__(cls, message)
        diagnostic.kind = kind
        return diagnostic


def is_failure(diagnostic: str) -> bool:
    """Whether a diagnostic means the tool broke, rather than that a file
    did not fully parse. A plain string counts as a failure: it predates the
    distinction, and treating an unlabelled warning as benign would be the
    unsafe direction."""
    return getattr(diagnostic, "kind", Diagnostic.FAILURE) == Diagnostic.FAILURE


def _read(path: Path, errors: list[str] | None) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError as error:
        message = f"cannot read {path}: {error}"
        print(f"warning: {message}", file=sys.stderr)
        if errors is not None:
            errors.append(Diagnostic(message, Diagnostic.FAILURE))
        return None


def read_sources(
    paths: Sequence[Path | str],
    exclude: Sequence[str] = (),
    errors: list[str] | None = None,
) -> list[tuple[str, bytes]]:
    """Discover and read every scannable file, skipping the unreadable.

    Shared by the analysis pipeline and by --dump-symbols so both survive a
    file that cannot be read; one bad file must never abort a sweep.

    Surviving is not the same as succeeding. A path that does not exist and a
    file that cannot be opened are both the tool failing to do what it was
    asked, so they go into `errors` as failures and reach the exit code. The
    case that must NOT reach it is a file that was read and did not fully
    parse -- that one produced findings, and on real C++ it is the common
    case.
    """
    sources: list[tuple[str, bytes]] = []
    for path in discover_files(paths, exclude, errors):
        content = _read(path, errors)
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
        message = Diagnostic(
            f"{path}: rule {rule.rule_id} failed on {_unit_location(unit)}: {error}",
            Diagnostic.FAILURE,
        )
        print(f"warning: {message} -- this unit's {rule.rule_id} results are incomplete", file=sys.stderr)
        errors.append(message)
        return []


def analyze(
    paths: Sequence[Path | str],
    *,
    exclude: Sequence[str] = (),
    types: Sequence[str] | None = None,
    min_evidence: Evidence = Evidence.C,
    config: dict[str, Any] | None = None,
) -> tuple[list[Finding], Knowledge, list[str]]:
    """Run the full pipeline and report what it found.

    The third return value is the list of warnings produced by an isolated
    extraction or rule failure, or by a file tree-sitter could not fully
    parse (empty on a clean run) — callers that need to know whether the
    analysis was complete, rather than merely non-crashing, check this
    rather than inferring it from stderr output.

    A parse error is a warning, not a skip. tree-sitter recovers and the
    file still yields findings; what is lost is the guarantee that they are
    all of them. Staying silent about that was the defect this reports: a
    holdout sweep of VVdeC found eleven registered-intrinsic call sites the
    tool never saw, all of them past the point where one 3398-line header
    stopped parsing, and nothing in the output said so.
    """
    # Before any file is opened. A config the tool will not honour must not
    # produce a report -- a run that quietly ignored what it was asked to do
    # is indistinguishable from one that did it. This is here rather than in
    # the CLI because `analyze` is a public entry point with the same
    # exposure.
    resolved_config = validate_config(config or {}, ALL_RULES)

    knowledge = load_knowledge()
    errors: list[str] = []
    sources = read_sources(paths, exclude, errors)

    ctx = Context(
        symbols=build_symbol_index(sources, knowledge),
        knowledge=knowledge,
        config=resolved_config,
    )

    findings: list[Finding] = []
    for path, source in sources:
        try:
            units, unparsed = extract_units_and_diagnostics(path, source, knowledge)
        except Exception as error:  # noqa: BLE001 - a bad file must not abort the sweep
            message = Diagnostic(f"{path}: extraction failed: {error}", Diagnostic.FAILURE)
            print(f"warning: skipping {path}: {error}", file=sys.stderr)
            errors.append(message)
            continue
        if unparsed:
            spans = ", ".join(
                f"line {start}" if start == end else f"lines {start}-{end}"
                for start, end in unparsed[:_MAX_REPORTED_SPANS]
            )
            if len(unparsed) > _MAX_REPORTED_SPANS:
                spans += f", and {len(unparsed) - _MAX_REPORTED_SPANS} more"
            message = Diagnostic(
                f"{path}: could not be fully parsed ({spans}); findings there may be incomplete",
                Diagnostic.UNPARSED,
            )
            print(f"warning: {message}", file=sys.stderr)
            errors.append(message)
        for unit in units:
            for rule in ALL_RULES:
                findings.extend(_run_rule(rule, unit, ctx, path, errors))

    if types:
        allowed = set(types)
        findings = [f for f in findings if f.type in allowed]
    findings = [f for f in findings if _EVIDENCE_ORDER[f.evidence] <= _EVIDENCE_ORDER[min_evidence]]
    return findings, knowledge, errors
