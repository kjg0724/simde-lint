"""I1: every rule's `Finding`s must match their producing unit's location.

`Finding.__post_init__` only enforces internal consistency between `scope`,
`function` and `macro` — it does not, and cannot, check that those three
fields actually came from the unit a rule was matching against. A rule that
reached for `unit.name` instead of `location_fields(unit)` (see
`rules/base.py`) would silently mislabel a macro finding as a function one,
or vice versa, and nothing downstream would catch it.

This sweeps every rule over every fixture in `tests/fixtures/rules/` — both
`FunctionUnit`s and the one `MacroUnit`-producing fixture
(`redundant_macro.c`) — so the contract is checked on both kinds of unit, not
only the macro side: a regression in a function-scoped rule would pass a
macro-only check just as easily as a macro-scoped regression would pass a
function-only one.
"""

from __future__ import annotations

from pathlib import Path

from simde_lint.extract import extract_units
from simde_lint.knowledge import load_knowledge
from simde_lint.rules import ALL_RULES, Context, validate_config
from simde_lint.symbols import build_symbol_index

FIXTURES = Path(__file__).parent / "fixtures" / "rules"


def _unit_and_finding_pairs():
    sources = [(str(path), path.read_bytes()) for path in sorted(FIXTURES.glob("*.c"))]
    knowledge = load_knowledge()
    ctx = Context(symbols=build_symbol_index(sources, knowledge), knowledge=knowledge, config=validate_config({}, ALL_RULES))
    pairs = []
    for path, source in sources:
        for unit in extract_units(path, source, knowledge):
            for rule in ALL_RULES:
                for finding in rule.match(unit, ctx):
                    pairs.append((unit, finding))
    return pairs


def test_fixtures_exercise_both_a_function_unit_and_a_macro_unit():
    # A regression on either side would go unnoticed if this sweep only ever
    # saw one kind of unit; pin that both are actually present.
    pairs = _unit_and_finding_pairs()
    scopes = {unit.scope for unit, _ in pairs}
    assert scopes == {"function", "macro"}


def test_every_finding_matches_its_producing_units_location_fields():
    pairs = _unit_and_finding_pairs()
    assert pairs  # the fixtures must actually produce findings to check
    for unit, finding in pairs:
        assert finding.scope == unit.scope, (
            f"{finding.rule} on {unit.file} produced scope={finding.scope!r} "
            f"for a {unit.scope!r} unit ({unit.name})"
        )
        assert finding.function == unit.function_name, (
            f"{finding.rule} on {unit.file} produced function={finding.function!r}, "
            f"expected {unit.function_name!r} from the unit"
        )
        assert finding.macro == unit.macro_name, (
            f"{finding.rule} on {unit.file} produced macro={finding.macro!r}, "
            f"expected {unit.macro_name!r} from the unit"
        )
