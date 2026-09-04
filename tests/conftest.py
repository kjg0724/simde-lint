from pathlib import Path

import pytest

from simde_lint.extract import extract_units
from simde_lint.knowledge import load_knowledge
from simde_lint.rules import ALL_RULES, validate_config
from simde_lint.rules.base import Context
from simde_lint.symbols import build_symbol_index

FIXTURES = Path(__file__).parent / "fixtures" / "rules"


@pytest.fixture
def run_rule():
    def _run(rule, fixture_name: str, config: dict | None = None):
        path = FIXTURES / fixture_name
        source = path.read_bytes()
        knowledge = load_knowledge()
        ctx = Context(
            symbols=build_symbol_index([(str(path), source)], knowledge),
            knowledge=knowledge,
            # Validated, exactly as `analyze` does it. A bare `{}` here would
            # hand rules a config the real pipeline never produces -- they
            # read declared keys directly now, so an unvalidated mapping
            # means every rule test runs against a shape no user can cause.
            config=validate_config(config or {}, ALL_RULES),
        )
        findings = []
        for unit in extract_units(str(path), source, knowledge):
            findings.extend(rule.match(unit, ctx))
        return findings

    return _run
