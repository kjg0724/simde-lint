from pathlib import Path

from simde_lint.knowledge import load_knowledge
from simde_lint.symbols import build_symbol_index

FIXTURE = Path(__file__).parent / "fixtures" / "symbols" / "table.c"


def _index():
    source = FIXTURE.read_bytes()
    return build_symbol_index([(str(FIXTURE), source)], load_knowledge())


def test_collects_plain_static_const_array_as_single_row():
    array = _index().lookup("plain_mask")
    assert array.rows == (tuple(range(16)),)
    assert array.defined_at.endswith("table.c:1")


def test_collects_two_dimensional_array_behind_a_registered_wrapper_macro():
    array = _index().lookup("even_odd_mask_x")
    assert len(array.rows) == 2
    assert array.rows[0][:4] == (0, 2, 4, 6)
    assert array.rows[1][:4] == (0, 1, 3, 5)


def test_parses_hex_lane_values():
    assert _index().lookup("sentinel_mask").rows[0] == (0xFF,) * 16


def test_ignores_unregistered_wrapper_macros():
    assert _index().lookup("hidden_mask") is None
