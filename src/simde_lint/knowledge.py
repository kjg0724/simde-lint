"""Loader for the YAML knowledge tables.

The tables are data: intrinsic names, SIMDe expansion costs, NEON
counterparts, alias spellings, and wrapper-macro registrations. Structural
matching lives in the rule modules instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

_DEFAULT_DIR = Path(__file__).parent / "knowledge"


@dataclass(frozen=True)
class CostInfo:
    """A SIMDe expansion cost with the source line it was read from.

    Every number and suggestion the report prints comes from one of these.
    """

    key: str
    simde_insns: int
    native_insns: int
    suggestion: str
    source: str
    note: str = ""


@dataclass(frozen=True)
class Knowledge:
    simde_version: str
    redundant: dict[str, CostInfo]
    patterns: dict[str, CostInfo]
    aliases: dict[str, str]
    wrapper_macros: dict[str, int]

    def normalize(self, name: str) -> str:
        """Map an alias spelling onto its canonical x86 intrinsic name."""
        return self.aliases.get(name, name)

    def cost(self, rule_id: str) -> CostInfo:
        """Cost entry for a rule that matches a sequence, by rule id."""
        return self.patterns[rule_id]


def _read(directory: Path, filename: str) -> dict:
    with (directory / filename).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _costs(entries: dict) -> dict[str, CostInfo]:
    return {
        key: CostInfo(
            key=key,
            simde_insns=entry["simde_insns"],
            native_insns=entry["native_insns"],
            suggestion=entry["suggestion"],
            source=entry["source"],
            note=entry.get("note", ""),
        )
        for key, entry in entries.items()
    }


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
    return Knowledge(
        simde_version=redundant_doc["simde_version"],
        redundant=_costs(redundant_doc["intrinsics"]),
        patterns=_costs(patterns_doc["patterns"]),
        aliases=aliases_doc["aliases"],
        wrapper_macros=wrapper_macros,
    )
