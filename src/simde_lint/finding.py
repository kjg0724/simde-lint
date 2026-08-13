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
    simde_insns: int
    native_insns: int
    suggestion: str
    mask_source: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "type": self.type,
            "rule": self.rule,
            "rule_mechanism": self.rule_mechanism,
            "evidence": self.evidence.value,
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
        return data
