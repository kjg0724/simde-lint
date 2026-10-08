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
    array = _index().lookup("wrapped_mask")
    assert len(array.rows) == 2
    assert array.rows[0][:4] == (0, 2, 4, 6)
    assert array.rows[1][:4] == (0, 1, 3, 5)


def test_excludes_a_writable_array_behind_a_registered_wrapper_macro():
    # The registration says where DECLARE_ALIGNED keeps its declarator. It
    # says nothing about the storage, and an initializer is only the bytes a
    # shuffle reads while nothing writes them. This is how SVT-AV1 declares
    # the table that used to carry the only grade-A findings resting on this
    # index.
    assert _index().lookup("even_odd_mask_x") is None


def test_excludes_a_wrapped_array_whose_elements_are_wider_than_a_byte():
    # The plain path's requirement, applied to the macro form: an element of
    # 0x1000 spans two lanes, and reading it as one called an unsafe mask
    # safe.
    assert _index().lookup("wide_mask") is None


def test_a_wrapper_taking_no_alignment_argument_is_registered_and_unreachable():
    # wrapper_macros.yaml registers DECLARE_ALIGNED_16 with its declarator at
    # argument 1. The collector walks assignment expressions, and this
    # spelling never produces one: with no leading integer argument,
    # tree-sitter reads `DECLARE_ALIGNED_16(const uint8_t, m[1][16])` as a
    # K&R function definition and the initializer as a separate statement.
    # Measured for both the qualified and unqualified type, inside a file and
    # alone. No corpus uses the macro, so the entry costs nothing but claims
    # something; this test is what keeps the claim from reading as working.
    assert _index().lookup("unreached_mask") is None


def test_parses_hex_lane_values():
    assert _index().lookup("sentinel_mask").rows[0] == (0xFF,) * 16


def test_excludes_an_array_of_pointers_declared_plainly():
    # The declaration's type field is `unsigned char` and the elements are
    # addresses. Four pointers are not four lanes, and reading them as lanes
    # resolved a mask whose bytes were never seen. The pointer lives in the
    # declarator, so the type check cannot see it.
    assert _index().lookup("pointer_mask") is None


def test_excludes_an_array_of_pointers_behind_a_registered_wrapper_macro():
    # The same shape through the macro form, where the `*` sits in the type
    # argument instead.
    assert _index().lookup("wrapped_pointer_mask") is None


def test_ignores_unregistered_wrapper_macros():
    assert _index().lookup("hidden_mask") is None


def test_excludes_a_table_holding_any_non_integer_element():
    # Discriminates full exclusion from the weaker "drop the bad element"
    # behaviour: under that variant this would resolve to (0, 1, 3).
    assert _index().lookup("mixed_mask") is None


def test_stops_resolving_a_name_two_files_define_differently():
    # static const tables have internal linkage, so this is legal C. A flat
    # index cannot say which one a use site meant, so it must resolve neither.
    knowledge = load_knowledge()
    first = b"static const unsigned char m[4] = {0, 1, 2, 3};"
    second = b"static const unsigned char m[4] = {4, 5, 6, 7};"
    index = build_symbol_index([("a.c", first), ("b.c", second)], knowledge)
    assert index.lookup("m") is None


def test_repeated_identical_definitions_are_not_a_collision():
    knowledge = load_knowledge()
    same = b"static const unsigned char m[4] = {0, 1, 2, 3};"
    index = build_symbol_index([("a.c", same), ("b.c", same)], knowledge)
    assert index.lookup("m").rows == ((0, 1, 2, 3),)


def test_names_excludes_an_ambiguous_entry():
    # A caller enumerating names() and looking each one up must never get
    # None back: names() promises what lookup() can deliver.
    knowledge = load_knowledge()
    first = b"static const unsigned char m[4] = {0, 1, 2, 3};"
    second = b"static const unsigned char m[4] = {4, 5, 6, 7};"
    index = build_symbol_index([("a.c", first), ("b.c", second)], knowledge)
    assert "m" not in index.names()


def test_names_lists_every_resolvable_array():
    # hidden_mask (unregistered macro), mixed_mask (non-integer element),
    # even_odd_mask_x (writable), wide_mask (wide elements), unreached_mask
    # (a registered macro the collector cannot see) and the two pointer
    # arrays never enter the index at all, so they are absent here too.
    assert _index().names() == ["plain_mask", "sentinel_mask", "wrapped_mask"]
