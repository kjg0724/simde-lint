"""Finding schema shared by rules and reporters."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class Evidence(str, Enum):
    A = "A"
    B = "B"
    C = "C"


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
    file: str
    line: int
    # None for a macro-scoped finding (see `scope`/`macro` below) — never
    # both `function` and `macro` set, never both unset.
    function: str | None
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
    # "function" or "macro" — whether the call site sits in a function body
    # or a `#define` body. A macro finding is fixed differently from a
    # function one: one edit changes every expansion, and has to be valid at
    # every expansion site, which this tool does not check. `function` and
    # `macro` mirror this: exactly one of them is set, matching `scope`.
    scope: str = "function"
    macro: str | None = None
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

    def __post_init__(self) -> None:
        # The field comments above state the rule as absolute — enforcing it
        # turns that into a guarantee instead of leaving it to convention. A
        # violation would otherwise reach a reporter silently: `text.py`
        # would print the literal word "None" as a location, or "(macro)"
        # with a blank macro name.
        if self.scope == "function":
            if self.function is None or self.macro is not None:
                raise ValueError(
                    "a function-scoped finding must set function and leave macro "
                    f"unset: function={self.function!r}, macro={self.macro!r}"
                )
        elif self.scope == "macro":
            if self.macro is None or self.function is not None:
                raise ValueError(
                    "a macro-scoped finding must set macro and leave function "
                    f"unset: function={self.function!r}, macro={self.macro!r}"
                )
        else:
            raise ValueError(f"scope must be 'function' or 'macro', got {self.scope!r}")

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "type": self.type,
            "rule": self.rule,
            "rule_mechanism": self.rule_mechanism,
            "evidence": self.evidence.value,
            "reason": self.reason.value if self.reason is not None else None,
            "file": self.file,
            "line": self.line,
            "scope": self.scope,
            "function": self.function,
            "macro": self.macro,
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


# Explicit rank tables, not a bare comparison on the enum values. "confirmed"
# < "diagnostic" and "A" < "B" < "C" happen to sort correctly as plain
# strings today, but that is a coincidence of the value names — renaming a
# value would silently reorder findings with no test catching it. A rank
# table makes the order an explicit decision instead of an accident of
# spelling.
# The taxonomy types whose isolated-kernel microbenchmarks showed a speedup.
# This is a property of the type, not of any call site, which is why it is a
# constant here rather than a field on Finding: a per-finding "impact" column
# would be a complete function of `type` and would read as a claim about this
# call site's measured effect, which no measurement supports.
BENCHMARK_BACKED_TYPES = frozenset({"S", "W", "F"})


def _type_rank(finding: "Finding") -> int:
    return 0 if finding.type in BENCHMARK_BACKED_TYPES else 1
evidence_rank = {Evidence.A: 0, Evidence.B: 1, Evidence.C: 2}


def sort_key(finding: "Finding") -> tuple[int, int, str, int, str]:
    """Benchmarked-type-first display order — the v1.1 default.

    Rule R alone accounts for the majority of a large sweep's findings (56%
    of SVT-AV1's), and its impact is always `diagnostic`: `-O3` generally
    removes the pattern on its own. Sorting by location first buried the
    `confirmed` findings — the ones actually worth acting on — under a wall
    of diagnostic ones. This key surfaces `confirmed` first, then the
    strongest evidence within it, and only then falls back to a stable
    location order.

    Includes the rule id because one location can legitimately carry findings
    from several rules — two Type M mechanisms can fire on the same statement.
    Without it the order of such a pair would depend on the order the caller
    happened to assemble them, and two runs over the same input could differ.
    Both reporters use this so their outputs stay comparable.
    """
    return (
        _type_rank(finding),
        evidence_rank[finding.evidence],
        finding.file,
        finding.line,
        finding.rule,
    )


def file_sort_key(finding: "Finding") -> tuple[str, int, str, str]:
    """Location-first display order — the pre-v1.1 default, kept as `--sort file`.

    Some readers want a diff-friendly walk through the source tree rather
    than a priority ordering; this preserves that.
    """
    return (finding.file, finding.line, finding.type, finding.rule)


# Both reporters index into this by the CLI's --sort value, so the two
# formats can never end up sorted differently for the same invocation.
SORT_KEYS = {"benchmarked": sort_key, "file": file_sort_key}
