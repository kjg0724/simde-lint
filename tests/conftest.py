from pathlib import Path

import pytest

from simde_lint.extract import extract_units
from simde_lint.knowledge import load_knowledge
from simde_lint.rules.base import Context
from simde_lint.symbols import build_symbol_index

FIXTURES = Path(__file__).parent / "fixtures" / "rules"


@pytest.fixture
def run_rule():
    def _run(rule, fixture_name: str):
        path = FIXTURES / fixture_name
        source = path.read_bytes()
        knowledge = load_knowledge()
        ctx = Context(
            symbols=build_symbol_index([(str(path), source)], knowledge),
            knowledge=knowledge,
            config={},
        )
        findings = []
        for unit in extract_units(str(path), source, knowledge):
            findings.extend(rule.match(unit, ctx))
        return findings

    return _run
