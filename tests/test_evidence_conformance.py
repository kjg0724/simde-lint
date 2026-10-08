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
from simde_lint.rules import ALL_RULES, Context, validate_config
from simde_lint.symbols import build_symbol_index

FIXTURES = Path(__file__).parent / "fixtures" / "rules"

ALLOWED: dict[str, set[str]] = {
    # C only. R reports a transform whose safety depends on the unused lanes
    # being dead in the consumer, and it never looks at the consumer, so it
    # has nothing that could grade higher.
    "R.zero_init_partial_load": {"C"},
    "S.pshufb_guard": {"A", "B", "C"},
    # C joined when W stopped establishing its round-trip from spelling. Two
    # premises it cannot prove withdraw the replacement rather than the
    # finding: an operand rebound between the multiplies (`unresolved`), and a
    # producer inside a construct the consumer is outside (`requires_context`).
    "W.mul16_widen_roundtrip": {"A", "B", "C"},
    # A, C. B is the hop path, and it is structurally dead: every conversion in
    # `fusion._WIDENING` raises the product above the width the multiply's
    # recorded fused form accumulates at, so the width check caps the grade at
    # C before the hop's B can stand. Declared as {A, B, C} it was a claim
    # about the rule that no fixture could reach and nothing tested -- the
    # equality assertion below is what surfaced it.
    "F.mul_add_no_fuse": {"A", "C"},
    "M.scalar_insert_chain": {"A", "B"},
    "M.scalar_set_build": {"A", "B"},
    # C joined when P stopped claiming its premise held on every path. A
    # compare inside a branch its consumer is outside feeds it on the taken
    # pass only, so what the grade carries is the mechanism's presence, not a
    # withheld transform -- hence a reason of its own.
    "P.cmp_immediate_use": {"A", "C"},
}


def _findings_over_all_fixtures():
    sources = [(str(path), path.read_bytes()) for path in sorted(FIXTURES.glob("*.c"))]
    knowledge = load_knowledge()
    ctx = Context(symbols=build_symbol_index(sources, knowledge), knowledge=knowledge, config=validate_config({}, ALL_RULES))
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
        # And every declared grade has to be reachable from the fixtures, or
        # the declaration is unchecked in that direction. Containment alone let
        # a grade be added to a rule with no fixture producing it: W gained C
        # and `{A} <= {A, B}` kept passing while the table said W could not
        # emit C at all. A declared grade nothing exercises is a claim about
        # the rule that nothing tests.
        assert grades == ALLOWED[rule_id], (
            f"{rule_id} declares {sorted(ALLOWED[rule_id])} but the fixtures "
            f"only reach {sorted(grades)}; add a fixture for "
            f"{sorted(ALLOWED[rule_id] - grades)} or stop declaring it"
        )
