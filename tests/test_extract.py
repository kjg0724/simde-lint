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
    # `shuf` is assigned a byte literal constructor, so the definition carries
    # the lanes AND still names the call that produced them — rules F, W and M
    # reach a producing call through `call_id`.
    definition = unit.definition_before("shuf", call.line)
    assert definition.value.kind == ValueKind.LITERAL_VECTOR
    assert definition.value.lanes is not None
    assert unit.call_by_id(definition.value.call_id).name == "_mm_setr_epi8"


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


def test_an_overwrite_by_a_non_intrinsic_call_is_recorded():
    # `mask = helper_load(c)` is invisible to both extraction paths today: the
    # intrinsic-call loop skips it because helper_load isn't an intrinsic, and
    # `_record_plain_assignments` skips every call_expression outright. A rule
    # asking `redefined_between("mask", ...)` then believes the compare's
    # result survived to line 5 when it did not.
    source = b"""
void f(__m128i a, __m128i b, __m128i c) {
    __m128i mask = _mm_cmpgt_epi64(a, b);
    mask = helper_load(c);
    __m128i sel = _mm_and_si128(c, mask);
}
"""
    unit = extract_units("t.c", source, load_knowledge())[0]
    assert unit.redefined_between("mask", 3, 5) is True
    overwrite = unit.definition_before("mask", 5)
    assert overwrite.line == 4
    assert overwrite.value.kind == ValueKind.UNKNOWN


def test_a_cast_wrapped_intrinsic_initializer_records_exactly_one_definition():
    # `(__m128i)_mm_setr_epi8(...)` is not a call_expression at the top level,
    # so the old plain-assignment skip (`right.type == "call_expression"`)
    # missed it and recorded a second, UNKNOWN definition alongside the one
    # the intrinsic-call loop already added with lanes.
    source = b"""
void f(void) {
    __m128i m = (__m128i)_mm_setr_epi8(0,0,1,1,2,2,3,3,4,4,5,5,6,6,7,7);
}
"""
    unit = extract_units("t.c", source, load_knowledge())[0]
    assert len(unit.definitions["m"]) == 1
    definition = unit.definitions["m"][0]
    assert definition.value.kind == ValueKind.LITERAL_VECTOR
    assert definition.value.lanes == (0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7)


def test_a_cast_wrapped_non_intrinsic_call_is_still_recorded_as_unknown():
    # The same cast-unwrap must not swallow a genuinely unrecognized call: it
    # should fall through to being recorded, just like the uncast case above.
    source = b"""
void f(__m128i c) {
    __m128i mask = (__m128i)helper_load(c);
}
"""
    unit = extract_units("t.c", source, load_knowledge())[0]
    assert len(unit.definitions["mask"]) == 1
    assert unit.definitions["mask"][0].value.kind == ValueKind.UNKNOWN
