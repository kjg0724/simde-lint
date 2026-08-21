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
    definition = unit.definition_before("shuf", call.start_byte)
    assert definition.value.kind == ValueKind.LITERAL_VECTOR
    assert definition.value.lanes is not None
    assert unit.call_by_id(definition.value.call_id).name == "_mm_setr_epi8"


def test_a_variable_assigned_a_byte_literal_constructor_is_a_literal_vector():
    # `shuf = _mm_setr_epi8(...)` is a local constant: its lanes are as
    # knowable as the same literal written inline, so its definition should
    # carry them rather than an opaque call result.
    unit = _unit()
    # A position past the whole file's bytes stands in for "after everything",
    # the byte-offset equivalent of the old line sentinel `unit.end_line`.
    definition = unit.definition_before("shuf", len(FIXTURE.read_bytes()))
    assert definition.value.kind == ValueKind.LITERAL_VECTOR
    assert definition.value.lanes == (0, 0, 1, 1, 2, 2, 3, 3, 255, 255, 255, 255, 255, 255, 255, 255)


def test_a_variable_assigned_a_non_literal_call_stays_a_call_result():
    # `cmp = _mm_cmpgt_epi64(...)` has no literal lanes to record, so its
    # definition still names the producing call for one-hop tracing.
    unit = _unit()
    definition = unit.definition_before("cmp", len(FIXTURE.read_bytes()))
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
    # Byte-offset equivalents of the old line bounds 3 and 5: the first
    # `mask` definition's own position, and the position of the call that
    # follows the overwrite.
    mask_defs = unit.definitions["mask"]
    sel_call = next(c for c in unit.calls if c.name == "_mm_and_si128")
    assert unit.redefined_between("mask", mask_defs[0].start_byte, sel_call.start_byte) is True
    overwrite = unit.definition_before("mask", sel_call.start_byte)
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


def test_extraction_orders_same_line_statements_by_byte():
    source = (
        b"void f(const int *p) {\n"
        b"    __m128i a = _mm_loadu_si32(p); a = _mm_add_epi32(a, a); "
        b"__m128i b = _mm_add_epi32(a, a);\n"
        b"}\n"
    )
    unit = extract_units("t.c", source, load_knowledge())[0]
    adds = [c for c in unit.calls if c.name == "_mm_add_epi32"]
    assert len(adds) == 2
    # The second add sees the reassignment made by the first; the first does not.
    first, second = sorted(adds, key=lambda c: c.start_byte)
    assert unit.definition_before("a", first.start_byte).value.text == "_mm_loadu_si32"
    assert unit.definition_before("a", second.start_byte).value.text == "_mm_add_epi32"


def test_a_multi_operation_macro_is_not_registered_as_an_alias():
    # LOAD8_S-style: several calls in the body. Registering it as an alias for
    # the first would report its call sites as that intrinsic's call sites.
    source = (
        b"#define LOAD8_S(p) \\\n"
        b"    _mm256_setr_epi32(_mm_loadl_epi64(p), _mm_loadl_epi64(p))\n"
        b"void f(const void *p) { __m256i v = LOAD8_S(p); (void)v; }\n"
    )
    unit = next(u for u in extract_units("t.c", source, load_knowledge()) if u.name == "f")
    assert [c.name for c in unit.calls] == []


NESTED_MACRO = (
    b"#define LOAD4(BASE, OFF) \\\n"
    b"    _mm_unpacklo_epi64(_mm_loadl_epi64((const __m128i*)((BASE)+(OFF))), \\\n"
    b"                       _mm_loadl_epi64((const __m128i*)((BASE)+(OFF)+8)))\n"
)

STATEMENT_MACRO = (
    b"#define ACC(dst, a, b) do { \\\n"
    b"    __m128i t = _mm_mullo_epi32(a, b); \\\n"
    b"    dst = _mm_add_epi32(dst, t); \\\n"
    b"} while (0)\n"
)


def test_a_macro_body_becomes_a_unit():
    units = extract_units("t.c", NESTED_MACRO, load_knowledge())
    macro = next(u for u in units if u.scope == "macro")
    assert macro.macro_name == "LOAD4"
    assert sorted(c.name for c in macro.calls) == [
        "_mm_loadl_epi64", "_mm_loadl_epi64", "_mm_unpacklo_epi64",
    ]
    assert [c.line for c in macro.calls if c.name == "_mm_loadl_epi64"] == [2, 3]


def test_macro_def_use_links_a_body_assignment():
    units = extract_units("t.c", STATEMENT_MACRO, load_knowledge())
    macro = next(u for u in units if u.scope == "macro")
    mul = next(c for c in macro.calls if c.name == "_mm_mullo_epi32")
    add = next(c for c in macro.calls if c.name == "_mm_add_epi32")
    assert macro.definition_before("t", add.start_byte).value.call_id == mul.id


def test_a_macro_parameter_has_no_definition():
    units = extract_units("t.c", NESTED_MACRO, load_knowledge())
    macro = next(u for u in units if u.scope == "macro")
    assert macro.definition_before("BASE", 10_000) is None


def test_a_macro_without_intrinsics_makes_no_unit():
    source = b"#define MAX2(a, b) ((a) > (b) ? (a) : (b))\n"
    assert [u for u in extract_units("t.c", source, load_knowledge()) if u.scope == "macro"] == []


def test_units_do_not_share_symbols():
    # M's body deliberately holds two calls, not one: a single-call body
    # (`_mm_add_epi32(tmp, a)` alone) satisfies the forwarding-alias predicate
    # from Task 3 regardless of what its argument spells, so it would be
    # registered as an alias and produce no MacroUnit at all — leaving nothing
    # for this test to isolate. The second call keeps the body a genuine
    # multi-operation macro while still referencing the free variable `tmp`.
    source = (
        b"#define M(a) _mm_add_epi32(tmp, _mm_add_epi32(a, a))\n"
        b"void f(__m128i x) { __m128i tmp = _mm_loadu_si32(&x); (void)tmp; }\n"
    )
    units = extract_units("t.c", source, load_knowledge())
    macro = next(u for u in units if u.scope == "macro")
    assert macro.definition_before("tmp", 10_000) is None


def test_an_alias_used_inside_a_macro_keeps_its_written_spelling():
    source = (
        b"#define LOAD1(p) _mm_loadl_epi64(p)\n"
        b"#define LOAD_PAIR(a, b) _mm_unpacklo_epi64(LOAD1(a), LOAD1(b))\n"
    )
    units = extract_units("t.c", source, load_knowledge())
    names = {u.macro_name for u in units if u.scope == "macro"}
    assert names == {"LOAD_PAIR"}
    pair = next(u for u in units if getattr(u, "macro_name", None) == "LOAD_PAIR")
    loads = [c for c in pair.calls if c.name == "_mm_loadl_epi64"]
    assert len(loads) == 2
    assert {c.raw_name for c in loads} == {"LOAD1"}


def test_a_macro_used_many_times_still_yields_one_unit():
    source = (
        b"#define LOAD1(p) _mm_unpacklo_epi64(_mm_loadl_epi64(p), _mm_loadl_epi64(p))\n"
        b"void f(const void *p) {\n"
        b"    __m128i a = LOAD1(p); __m128i b = LOAD1(p); __m128i c = LOAD1(p);\n"
        b"    (void)a; (void)b; (void)c;\n"
        b"}\n"
    )
    units = extract_units("t.c", source, load_knowledge())
    macros = [u for u in units if u.scope == "macro"]
    assert len(macros) == 1
    assert sum(1 for c in macros[0].calls if c.name == "_mm_loadl_epi64") == 2
