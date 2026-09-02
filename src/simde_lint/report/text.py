"""Human-readable report.

The mechanism annotation is mandatory. A reader who sees "Type S: 0" without
it would conclude the tool fails to reproduce the taxonomy, when the correct
reading is that the implemented S mechanism is absent from that code while
other S mechanisms may be present.
"""

from __future__ import annotations

from collections import Counter

from ..finding import Finding, Reason, SORT_KEYS


def _label(finding: Finding) -> str:
    return f"{finding.type} ({finding.rule_mechanism})"


def _evidence_label(finding: Finding) -> str:
    # Reason is set only on grade C, distinguishing "could not resolve"
    # (unresolved) from "resolved, and the guard is load-bearing"
    # (guard_required) from "a transform exists, but the condition it needs
    # was not verified here" (transform_requires_context). All three share
    # grade C because v1 acts on them identically: no transform without
    # human confirmation.
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
    """What is known about the cost, without rounding one side down to nothing.

    The two sides are established separately and one is often known while the
    other is not: rule R reads the SIMDe expansion straight out of the header
    but cannot say what replaces it, because that depends on a consumer it
    does not analyse. Collapsing that to "instruction count unknown" threw
    away a fact the header states plainly.
    """
    if finding.simde_insns is None and finding.native_insns is None:
        return "instruction count unknown"
    if finding.native_insns is None:
        return f"SIMDe expansion: {finding.simde_insns} instructions; replacement count unknown"
    if finding.simde_insns is None:
        return f"replacement: {finding.native_insns} instructions; SIMDe expansion count unknown"
    return f"{finding.simde_insns} -> {finding.native_insns} instructions"


def _suggestion_line(finding: Finding) -> str:
    counts = _counts(finding)
    if finding.suggestion is None:
        # Plainly visible rather than silently dropped: the rationale above
        # already states why (unresolved evidence or no known fused/native
        # form), this line just confirms nothing is being recommended.
        return f"    no suggestion offered ({counts})"
    if finding.reason is Reason.TRANSFORM_REQUIRES_CONTEXT:
        # A conditional suggestion must not read like the unconditional
        # replacement line below: the rule has not verified that the
        # condition holds at this call site. Read from `reason`, which the
        # rule has already decided, never from `transform_status` -- Finding
        # does not carry that field, and a reporter reasoning about it
        # directly would be re-deciding a grading question that belongs to
        # the rule.
        #
        # Which condition is deliberately not named here. It is a per-rule
        # fact and the rationale states it: rule F's is a horizontal-reduction
        # consumer, drawn from an adjudicated knowledge entry; rule R's is
        # dead unused lanes, which is rule logic. Naming one of them on this
        # line made every rule that reports this reason inherit F's sentence.
        return f"    conditional suggestion: {finding.suggestion} ({counts})"
    return f"    suggestion: {finding.suggestion} ({counts})"


def render_text(findings: list[Finding], *, sort: str = "benchmarked") -> str:
    lines: list[str] = []
    for finding in sorted(findings, key=SORT_KEYS[sort]):
        lines.append(
            f"{finding.file}:{finding.line}  {_label(finding)}  "
            f"evidence={_evidence_label(finding)}"
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
