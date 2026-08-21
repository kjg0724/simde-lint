"""Human-readable report.

The mechanism annotation is mandatory. A reader who sees "Type S: 0" without
it would conclude the tool fails to reproduce the taxonomy, when the correct
reading is that the implemented S mechanism is absent from that code while
other S mechanisms may be present.
"""

from __future__ import annotations

from collections import Counter

from ..finding import Finding, SORT_KEYS


def _label(finding: Finding) -> str:
    return f"{finding.type} ({finding.rule_mechanism})"


def _evidence_label(finding: Finding) -> str:
    # Reason is set only on grade C, distinguishing "could not resolve"
    # (unresolved) from "resolved, and the guard is load-bearing"
    # (guard_required). Both share grade C because v1 acts on them
    # identically: no transform without human confirmation.
    if finding.reason is not None:
        return f"{finding.evidence.value} ({finding.reason.value})"
    return finding.evidence.value


def _intrinsic_label(finding: Finding) -> str:
    if finding.raw_name is not None:
        return f"{finding.intrinsic} (source spelling: {finding.raw_name})"
    return finding.intrinsic


def _location_label(finding: Finding) -> str:
    if finding.macro is not None:
        return f"{finding.macro} (macro)"
    return finding.function


def _counts(finding: Finding) -> str:
    if finding.simde_insns is None or finding.native_insns is None:
        return "instruction count unknown"
    return f"{finding.simde_insns} -> {finding.native_insns} instructions"


def _suggestion_line(finding: Finding) -> str:
    counts = _counts(finding)
    if finding.suggestion is None:
        # Plainly visible rather than silently dropped: the rationale above
        # already states why (unresolved evidence or no known fused/native
        # form), this line just confirms nothing is being recommended.
        return f"    no suggestion offered ({counts})"
    return f"    suggestion: {finding.suggestion} ({counts})"


def render_text(findings: list[Finding], *, sort: str = "impact") -> str:
    lines: list[str] = []
    for finding in sorted(findings, key=SORT_KEYS[sort]):
        lines.append(
            f"{finding.file}:{finding.line}  {_label(finding)}  "
            f"evidence={_evidence_label(finding)}  impact={finding.impact.value}"
        )
        lines.append(f"    {_intrinsic_label(finding)} in {_location_label(finding)}")
        lines.append(f"    {finding.rationale}")
        lines.append(_suggestion_line(finding))
        lines.append("")

    lines.append(f"Summary: {len(findings)} findings")
    # Grouped by rule, not by type: a taxonomy type can have more than one
    # implemented mechanism, and collapsing them would hide which one ran.
    mechanisms = {f.rule: f.rule_mechanism for f in findings}
    types = {f.rule: f.type for f in findings}
    by_rule = Counter(f.rule for f in findings)
    for rule_id in sorted(by_rule):
        lines.append(
            f"  {types[rule_id]} ({mechanisms[rule_id]}) [{rule_id}]: {by_rule[rule_id]}"
        )
    by_evidence = Counter(f.evidence.value for f in findings)
    for grade in sorted(by_evidence):
        lines.append(f"  evidence {grade}: {by_evidence[grade]}")
    return "\n".join(lines)
