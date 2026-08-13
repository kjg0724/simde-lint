from pathlib import Path

from simde_lint.extract import extract_units
from simde_lint.ir import ValueKind
from simde_lint.knowledge import load_knowledge

FIXTURE = Path(__file__).parent / "fixtures" / "extract" / "basic.c"


def _unit():
    units = extract_units(str(FIXTURE), FIXTURE.read_bytes(), load_knowledge())
    return next(u for u in units if u.name == "kernel")


def test_collects_intrinsic_calls_in_source_order():
    names = [c.name for c in _unit().calls]
    assert names[0] == "_mm_setr_epi8"
    assert names.count("_mm_shuffle_epi8") == 2


def test_resolves_a_file_local_macro_alias_and_keeps_the_raw_name():
    call = next(c for c in _unit().calls if c.raw_name == "_my_cmpgt_epi64")
    assert call.name == "_mm_cmpgt_epi64"


def test_records_inline_literal_lanes_as_a_literal_vector_argument():
    # Calls are ordered by position, so the nested _mm_setr_epi8 comes after the
    # _mm_shuffle_epi8 that encloses it; select the shuffle explicitly.
    call = [c for c in _unit().calls if c.name == "_mm_shuffle_epi8"][-1]
    assert call.args[1].kind == ValueKind.LITERAL_VECTOR
    assert call.args[1].lanes == tuple(range(16))


def test_records_a_variable_argument_and_its_definition():
    unit = _unit()
    call = next(c for c in unit.calls if c.name == "_mm_shuffle_epi8")
    assert call.args[1].kind == ValueKind.VARIABLE
    assert call.args[1].text == "shuf"
    definition = unit.definition_before("shuf", call.line)
    assert definition is not None


def test_a_variable_assigned_a_byte_literal_constructor_is_a_literal_vector():
    # `shuf = _mm_setr_epi8(...)` is a local constant: its lanes are as
    # knowable as the same literal written inline, so its definition should
    # carry them rather than an opaque call result.
    unit = _unit()
    definition = unit.definition_before("shuf", unit.end_line)
    assert definition.value.kind == ValueKind.LITERAL_VECTOR
    assert definition.value.lanes == (0, 0, 1, 1, 2, 2, 3, 3, 255, 255, 255, 255, 255, 255, 255, 255)


def test_a_variable_assigned_a_non_literal_call_stays_a_call_result():
    # `cmp = _mm_cmpgt_epi64(...)` has no literal lanes to record, so its
    # definition still names the producing call for one-hop tracing.
    unit = _unit()
    definition = unit.definition_before("cmp", unit.end_line)
    assert definition.value.kind == ValueKind.CALL_RESULT


def test_records_the_result_variable_of_a_call():
    call = next(c for c in _unit().calls if c.name == "_mm_loadu_si32")
    assert call.result_var == "data"


def test_a_nested_call_binds_no_result_variable():
    # `out = _mm_shuffle_epi8(data, _mm_setr_epi8(...))` binds only the
    # shuffle. Attributing `out` to the nested literal as well would put two
    # definitions on one line and make definition_before name the wrong
    # producing call.
    unit = _unit()
    nested = [c for c in unit.calls if c.name == "_mm_setr_epi8"][-1]
    assert nested.result_var is None
    assert len([d for d in unit.definitions["out"] if d.line == nested.line]) == 1


def test_literal_lanes_are_recorded_only_for_byte_constructors():
    # Rule S reads lanes to judge a byte shuffle mask. A wider constructor
    # recorded under a byte mask would report truncated values, so it stays
    # opaque instead.
    units = extract_units(
        "t.c",
        b"void f(void) { __m128i x = _mm_cmpeq_epi32(a, _mm_set_epi32(0x01020304, 0, 0, -1)); }",
        load_knowledge(),
    )
    outer = next(c for c in units[0].calls if c.name == "_mm_cmpeq_epi32")
    assert outer.args[1].kind == ValueKind.CALL_RESULT
    assert outer.args[1].lanes is None
