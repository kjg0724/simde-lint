"""Human-readable report.

The mechanism annotation is mandatory. A reader who sees "Type S: 0" without
it would conclude the tool fails to reproduce the taxonomy, when the correct
reading is that the implemented S mechanism is absent from that code while
other S mechanisms may be present.
"""

from __future__ import annotations

from collections import Counter

from ..finding import Finding


def _label(finding: Finding) -> str:
    return f"{finding.type} ({finding.rule_mechanism})"


def render_text(findings: list[Finding]) -> str:
    lines: list[str] = []
    for finding in sorted(findings, key=lambda f: (f.file, f.line, f.type)):
        lines.append(
            f"{finding.file}:{finding.line}  {_label(finding)}  "
            f"evidence={finding.evidence.value}  impact={finding.impact.value}"
        )
        lines.append(f"    {finding.intrinsic} in {finding.function}")
        lines.append(f"    {finding.rationale}")
        lines.append(
            f"    suggestion: {finding.suggestion} "
            f"({finding.simde_insns} -> {finding.native_insns} instructions)"
        )
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
