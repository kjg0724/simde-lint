"""Loader for the YAML knowledge tables.

The tables are data: intrinsic names, SIMDe expansion costs, NEON
counterparts, alias spellings, and wrapper-macro registrations. Structural
matching lives in the rule modules instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import yaml

_DEFAULT_DIR = Path(__file__).parent / "knowledge"
_UNKNOWN = "unknown"


class TransformStatus(str, Enum):
    """Whether a fused replacement is established for a matched intrinsic.

    Rule F grades on this and never on `suggestion`. The two answer different
    questions: `suggestion` is what the report shows a reader, this is what
    the tool is willing to assert. They moved together by accident until
    v2.1 — filling in an informative suggestion silently promoted a finding
    from C to A.

    - **ESTABLISHED** — a fused form applies generally to this intrinsic.
    - **CONDITIONAL** — one applies, but under a condition rule F does not
      check (a consumer shape, for instance). Caps at C, with its own reason,
      because the rule has not verified the condition holds here.
    - **UNKNOWN** — not established. Caps at C.
    """

    ESTABLISHED = "established"
    CONDITIONAL = "conditional"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CostInfo:
    """A SIMDe expansion cost with the source line it was read from.

    Every number and suggestion the report prints comes from one of these.
    `simde_insns`, `native_insns` and `suggestion` are `None` when the cost or
    the transform could not be established from the SIMDe source — this is an
    honest answer, not a placeholder to fill in later, and the report layer
    must render it as such rather than guessing.
    """

    key: str
    simde_insns: int | None
    native_insns: int | None
    suggestion: str | None
    source: str
    note: str = ""
    # Set only for `F.mul_add_no_fuse` entries; None elsewhere, where no rule
    # asks the question.
    transform_status: "TransformStatus | None" = None


@dataclass(frozen=True)
class Knowledge:
    simde_version: str
    redundant: dict[str, CostInfo]
    # rule_id -> intrinsic -> CostInfo, for the rules that match a set of
    # registered intrinsics (S, F, both M rules, P).
    patterns: dict[str, dict[str, CostInfo]]
    # rule_id -> CostInfo, for the one rule that matches a sequence rather
    # than a registered intrinsic (W).
    rule_costs: dict[str, CostInfo]
    aliases: dict[str, str]
    wrapper_macros: dict[str, int]

    def normalize(self, name: str) -> str:
        """Map an alias spelling onto its canonical x86 intrinsic name."""
        return self.aliases.get(name, name)

    def cost(self, rule_id: str, intrinsic: str | None = None) -> CostInfo:
        """Cost entry for a rule.

        Rule W matches a fixed three-call sequence rather than a registered
        intrinsic, so it is looked up by rule id alone. Every other rule
        matches a set of intrinsics across two register widths, whose costs
        differ, so `intrinsic` selects the entry the rule actually matched.
        """
        if rule_id in self.rule_costs:
            return self.rule_costs[rule_id]
        table = self.patterns[rule_id]
        if intrinsic is None:
            raise KeyError(f"{rule_id} requires an intrinsic name to look up its cost")
        if intrinsic not in table:
            raise KeyError(f"no cost entry for {intrinsic!r} under {rule_id}")
        return table[intrinsic]


def _read(directory: Path, filename: str) -> dict:
    with (directory / filename).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _unknown_to_none(value):
    return None if value == _UNKNOWN else value


def _cost_entry(key: str, entry: dict, requires_transform_status: bool = False) -> CostInfo:
    status = None
    if requires_transform_status:
        # KeyError, not a default: an entry that never declared what it
        # asserts must not be graded as though someone had decided.
        raw = entry["transform_status"]
        try:
            status = TransformStatus(raw)
        except ValueError:
            raise ValueError(
                f"{key}: unrecognized transform_status {raw!r}; "
                f"expected one of {[s.value for s in TransformStatus]}"
            ) from None
    return CostInfo(
        key=key,
        simde_insns=_unknown_to_none(entry["simde_insns"]),
        native_insns=_unknown_to_none(entry["native_insns"]),
        suggestion=_unknown_to_none(entry.get("suggestion")) or None,
        source=entry["source"],
        note=entry.get("note", ""),
        transform_status=status,
    )


def _costs(entries: dict, requires_transform_status: bool = False) -> dict[str, CostInfo]:
    return {
        key: _cost_entry(key, entry, requires_transform_status)
        for key, entry in entries.items()
    }


def _split_patterns(patterns_doc: dict) -> tuple[dict[str, dict[str, CostInfo]], dict[str, CostInfo]]:
    """Split patterns.yaml into per-intrinsic tables and rule-level costs.

    An entry is rule-level (like W, which matches a fixed call sequence, not
    a registered intrinsic) when it carries `simde_insns` directly; otherwise
    its value is itself a mapping of intrinsic name to cost entry.
    """
    per_intrinsic: dict[str, dict[str, CostInfo]] = {}
    rule_level: dict[str, CostInfo] = {}
    for rule_id, entry in patterns_doc["patterns"].items():
        if "simde_insns" in entry:
            rule_level[rule_id] = _cost_entry(rule_id, entry)
        else:
            per_intrinsic[rule_id] = _costs(entry, requires_transform_status=(rule_id == "F.mul_add_no_fuse"))
    return per_intrinsic, rule_level


def load_knowledge(directory: Path | None = None) -> Knowledge:
    base = directory or _DEFAULT_DIR
    redundant_doc = _read(base, "redundant.yaml")
    patterns_doc = _read(base, "patterns.yaml")
    aliases_doc = _read(base, "aliases.yaml")
    macros_doc = _read(base, "wrapper_macros.yaml")

    # wrapper_macros.yaml is exempt: its entries describe consumer-project
    # declaration macros, not SIMDe expansions, so it declares no version.
    versions = {
        redundant_doc["simde_version"],
        patterns_doc["simde_version"],
        aliases_doc["simde_version"],
    }
    if len(versions) != 1:
        raise ValueError(f"knowledge tables disagree on simde_version: {sorted(versions)}")

    wrapper_macros = {
        name: entry["declarator_arg"] for name, entry in macros_doc["macros"].items()
    }
    patterns, rule_costs = _split_patterns(patterns_doc)
    return Knowledge(
        simde_version=redundant_doc["simde_version"],
        redundant=_costs(redundant_doc["intrinsics"]),
        patterns=patterns,
        rule_costs=rule_costs,
        aliases=aliases_doc["aliases"],
        wrapper_macros=wrapper_macros,
    )
