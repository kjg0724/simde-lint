"""Spec conformance: each rule may only emit the evidence grades §7 declares.

Design spec Section 7's table:

| Rule | Grades |
|---|---|
| R | {A} |
| S | {A, B, C} |
| W | {A, B} |
| F | {A, B} |
| M (either mechanism) | {A, B} |
| P | {A} |

`ALLOWED` below is transcribed from that table by hand, on purpose: it is
not derived from the rule modules under test, so a rule that starts
emitting a grade outside its declared set fails this test instead of
silently redefining what "allowed" means.
"""

from __future__ import annotations

from pathlib import Path

from simde_lint.extract import extract_units
from simde_lint.knowledge import load_knowledge
from simde_lint.rules import ALL_RULES, Context
from simde_lint.symbols import build_symbol_index

FIXTURES = Path(__file__).parent / "fixtures" / "rules"

ALLOWED: dict[str, set[str]] = {
    "R.zero_init_partial_load": {"A"},
    "S.pshufb_guard": {"A", "B", "C"},
    "W.mul16_widen_roundtrip": {"A", "B"},
    "F.mul_add_no_fuse": {"A", "B"},
    "M.scalar_insert_chain": {"A", "B"},
    "M.scalar_set_build": {"A", "B"},
    "P.cmp_immediate_use": {"A"},
}


def _findings_over_all_fixtures():
    sources = [(str(path), path.read_bytes()) for path in sorted(FIXTURES.glob("*.c"))]
    knowledge = load_knowledge()
    ctx = Context(symbols=build_symbol_index(sources, knowledge), knowledge=knowledge, config={})
    findings = []
    for path, source in sources:
        for unit in extract_units(path, source, knowledge):
            for rule in ALL_RULES:
                findings.extend(rule.match(unit, ctx))
    return findings


def test_allowed_table_covers_every_registered_rule():
    # A rule added to ALL_RULES without a matching ALLOWED entry would make
    # the sweep below silently skip checking it.
    assert {rule.rule_id for rule in ALL_RULES} == set(ALLOWED)


def test_every_rule_stays_within_its_declared_evidence_grades():
    findings = _findings_over_all_fixtures()
    assert findings  # the fixtures must actually exercise the rules
    seen_by_rule: dict[str, set[str]] = {}
    for finding in findings:
        seen_by_rule.setdefault(finding.rule, set()).add(finding.evidence.value)
    # Every rule with a positive fixture should show up here at all; an
    # empty seen_by_rule for a registered rule would mean the fixtures don't
    # exercise it and this test isn't checking anything for it.
    assert set(seen_by_rule) == set(ALLOWED)
    for rule_id, grades in seen_by_rule.items():
        assert grades <= ALLOWED[rule_id], (
            f"{rule_id} emitted {sorted(grades - ALLOWED[rule_id])}, "
            f"outside its declared {sorted(ALLOWED[rule_id])}"
        )
