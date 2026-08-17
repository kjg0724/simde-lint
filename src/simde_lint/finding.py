"""Finding schema shared by rules and reporters."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class Evidence(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class Impact(str, Enum):
    CONFIRMED = "confirmed"
    DIAGNOSTIC = "diagnostic"


class Reason(str, Enum):
    """Why a finding graded C, distinguishing two meanings that grade alone can't.

    Grade C always means "the tool cannot confirm the transform is safe from
    source alone", but that collapses two different situations:

    - **UNRESOLVED** — the rule could not see far enough to judge at all (a
      runtime-loaded value, a call result with unknown lanes, a symbol not
      defined in the scanned inputs).
    - **GUARD_REQUIRED** — the rule saw everything relevant and the answer is
      that the guard the rule is examining is load-bearing (a mask whose
      lanes are fully known but include one outside the safe range).

    v1 keeps one grade, C, for both: the action either warrants is identical
    — do not transform without human confirmation. A fourth grade would only
    be warranted if the two ever needed different `--min-evidence` filtering
    or other CLI/automation behaviour, which they do not today.
    """

    UNRESOLVED = "unresolved"
    GUARD_REQUIRED = "guard_required"


@dataclass(frozen=True)
class Finding:
    type: str
    rule: str
    rule_mechanism: str
    evidence: Evidence
    impact: Impact
    file: str
    line: int
    function: str
    intrinsic: str
    rationale: str
    # None means the cost, or the suggested transform, could not be
    # established — either the SIMDe expansion cost is unknown at the data
    # layer, or the rule's own evidence does not support the transform at
    # this call site. Both reporters render the pair as "unknown" rather
    # than guessing, and to_dict() emits null rather than a number.
    simde_insns: int | None
    native_insns: int | None
    suggestion: str | None
    mask_source: dict[str, Any] | None = None
    # Set only when evidence is C; None for A and B. See Reason's docstring
    # for why one grade carries two reasons rather than splitting into two
    # grades.
    reason: Reason | None = None
    # The call's original spelling, set only when it differs from `intrinsic`
    # (a macro-aliased call site, e.g. VVenC's `_my_cmpgt_epi64` resolving to
    # `_mm_cmpgt_epi64`). Without this, grepping the source for `intrinsic`
    # finds nothing at an aliased site.
    raw_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "type": self.type,
            "rule": self.rule,
            "rule_mechanism": self.rule_mechanism,
            "evidence": self.evidence.value,
            "reason": self.reason.value if self.reason is not None else None,
            "impact": self.impact.value,
            "file": self.file,
            "line": self.line,
            "function": self.function,
            "intrinsic": self.intrinsic,
            "rationale": self.rationale,
            "simde_insns": self.simde_insns,
            "native_insns": self.native_insns,
            "suggestion": self.suggestion,
        }
        if self.mask_source is not None:
            data["mask_source"] = self.mask_source
        if self.raw_name is not None:
            data["raw_name"] = self.raw_name
        return data


def sort_key(finding: "Finding") -> tuple[str, int, str, str]:
    """Total display order for findings.

    Includes the rule id because one location can legitimately carry findings
    from several rules — two Type M mechanisms can fire on the same statement.
    Without it the order of such a pair would depend on the order the caller
    happened to assemble them, and two runs over the same input could differ.
    Both reporters use this so their outputs stay comparable.
    """
    return (finding.file, finding.line, finding.type, finding.rule)
