from pathlib import Path

import pytest

import simde_lint.extract as extract_module
from simde_lint.analyze import Diagnostic, analyze, is_failure
from simde_lint.cli import main as cli_main
from simde_lint.extract import Coordinates, extract_units, extract_units_and_diagnostics
from simde_lint.ir import ValueKind
from simde_lint.knowledge import load_knowledge
from simde_lint.macros import build_alias_map, is_forwarding_alias, reparse_macros
from simde_lint.parser import iter_nodes, parse_source
from simde_lint.rules import fusion, memory, suboptimal, widening
from simde_lint.rules.base import Context
from simde_lint.symbols import build_symbol_index

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
    # NESTED_MACRO's body binds nothing at all, so a bare
    # `definition_before("BASE", ...) is None` would hold for every
    # identifier, not just a parameter -- it would not catch a regression
    # where a real body binding lost its Definition. STATEMENT_MACRO's `a` is
    # a genuinely merely-referenced parameter (an argument to
    # `_mm_mullo_epi32`, never assigned), and its `t` is a genuine body
    # binding in the same unit: asserting both distinguishes "parameters
    # never get a synthetic definition" from "this unit defines nothing".
    units = extract_units("t.c", STATEMENT_MACRO, load_knowledge())
    macro = next(u for u in units if u.scope == "macro")
    assert macro.definition_before("a", 10_000) is None
    assert macro.definition_before("t", 10_000) is not None


def test_a_macro_without_intrinsics_makes_no_unit():
    source = b"#define MAX2(a, b) ((a) > (b) ? (a) : (b))\n"
    assert [u for u in extract_units("t.c", source, load_knowledge()) if u.scope == "macro"] == []


def test_units_do_not_share_symbols():
    # Each unit binds its own `tmp` to a different producing call, so this
    # pins isolation rather than mere absence: the macro's body never defines
    # anything under any implementation, so `definition_before("tmp", ...) is
    # None` alone would hold vacuously and would not catch state leaking
    # between units. Both `tmp`s must resolve, and each to its own call.
    #
    # M's body deliberately holds two calls, not one:
    # `__m128i tmp = _mm_setzero_si128();` alone would satisfy the
    # forwarding-alias predicate from Task 3 regardless of what its body
    # names, so it would be registered as an alias and produce no MacroUnit
    # at all. The second call (`a = _mm_add_epi32(a, tmp)`) keeps the body a
    # genuine multi-operation macro.
    source = (
        b"#define M(a) do { \\\n"
        b"    __m128i tmp = _mm_setzero_si128(); \\\n"
        b"    a = _mm_add_epi32(a, tmp); \\\n"
        b"} while (0)\n"
        b"void f(__m128i x) { __m128i tmp = _mm_loadu_si32(&x); (void)tmp; }\n"
    )
    units = extract_units("t.c", source, load_knowledge())
    macro = next(u for u in units if u.scope == "macro")
    func = next(u for u in units if u.scope == "function")

    macro_tmp = macro.definition_before("tmp", 10_000)
    func_tmp = func.definition_before("tmp", 10_000)
    assert macro_tmp is not None and func_tmp is not None
    assert macro.call_by_id(macro_tmp.value.call_id).name == "_mm_setzero_si128"
    assert func.call_by_id(func_tmp.value.call_id).name == "_mm_loadu_si32"
    # `definitions` is a separate dict per unit (each backed by its own
    # `_UnitBase` instance), so the two `tmp` bindings above are not the same
    # object -- if extraction ever shared state between units, one of the two
    # assertions above would resolve to the other unit's producing call.
    assert macro_tmp is not func_tmp


def test_an_alias_used_inside_a_macro_keeps_its_written_spelling():
    source = (
        b"#define LOAD1(p) _mm_loadl_epi64(p)\n"
        b"#define LOAD_PAIR(a, b) _mm_unpacklo_epi64(LOAD1(a), LOAD1(b))\n"
    )
    units = extract_units("t.c", source, load_knowledge())
    names = {u.macro_name for u in units if u.scope == "macro"}
    assert names == {"LOAD_PAIR"}
    pair = next(u for u in units if u.macro_name == "LOAD_PAIR")
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


# Three leading lines before the `#define` so the synthetic wrapper's own
# line numbering (which always starts fresh at the body, one line in) cannot
# coincide with the real file's. NESTED_MACRO sits at byte 0 of a one-macro
# file, where `_PREFIX` being exactly one line and the macro's own header
# also occupying exactly one line before the body starts makes the two
# numberings agree by coincidence -- a fixture built that way cannot catch
# `original_byte`/`line_column` being bypassed, only that the two happen to
# line up. Verified directly: replacing every remapping call site with the
# synthetic node's own coordinates leaves every test against NESTED_MACRO
# and STATEMENT_MACRO passing.
PRECEDED_MACRO = (
    b"// leading comment\n"
    b"// another leading comment\n"
    b"typedef int placeholder;\n"
    b"#define LOAD4(BASE, OFF) \\\n"
    b"    _mm_unpacklo_epi64(_mm_loadl_epi64((const __m128i*)((BASE)+(OFF))), \\\n"
    b"                       _mm_loadl_epi64((const __m128i*)((BASE)+(OFF)+8)))\n"
)

PRECEDED_STATEMENT_MACRO = (
    b"// leading comment\n"
    b"// another leading comment\n"
    b"typedef int placeholder;\n"
    b"#define ACC(dst, a, b) do { \\\n"
    b"    __m128i t = _mm_mullo_epi32(a, b); \\\n"
    b"    dst = _mm_add_epi32(dst, t); \\\n"
    b"} while (0)\n"
)


def test_macro_call_positions_map_back_to_the_real_file_not_the_synthetic_wrapper():
    # This is the property spec Section 3 calls load-bearing: "line and
    # column are recomputed from original_byte against the original source,
    # never taken from the synthetic text." Asserting a call's line, column,
    # and that its own start_byte, sliced into the *real* source, spells its
    # own raw_name, rules out every one of those three ever coming from the
    # synthetic wrapper's coordinates instead.
    units = extract_units("t.c", PRECEDED_MACRO, load_knowledge())
    macro = next(u for u in units if u.scope == "macro")

    unpacklo = next(c for c in macro.calls if c.name == "_mm_unpacklo_epi64")
    assert (unpacklo.line, unpacklo.column) == (5, 5)
    assert PRECEDED_MACRO[unpacklo.start_byte : unpacklo.start_byte + len(unpacklo.raw_name)] == (
        unpacklo.raw_name.encode()
    )

    loads = sorted((c for c in macro.calls if c.name == "_mm_loadl_epi64"), key=lambda c: c.start_byte)
    assert [(c.line, c.column) for c in loads] == [(5, 24), (6, 24)]
    for call in loads:
        assert PRECEDED_MACRO[call.start_byte : call.start_byte + len(call.raw_name)] == call.raw_name.encode()


def test_macro_definition_available_after_byte_maps_back_to_the_real_file():
    # A Definition's `available_after_byte` goes through the same
    # `original_byte` remapping as a call's own `start_byte` (extract.py's
    # `Coordinates.end_of`, via `_extract_calls`) but is never itself
    # asserted by the other position tests. The
    # init_declarator `t = _mm_mullo_epi32(a, b)` ends right after the call's
    # closing paren, so the real-file byte immediately before
    # `available_after_byte` must be that `)` -- a check that only holds if
    # the byte is a real-file coordinate, not the synthetic wrapper's.
    units = extract_units("t.c", PRECEDED_STATEMENT_MACRO, load_knowledge())
    macro = next(u for u in units if u.scope == "macro")
    add = next(c for c in macro.calls if c.name == "_mm_add_epi32")
    definition = macro.definition_before("t", add.start_byte)
    assert definition is not None
    assert definition.line == 5
    assert PRECEDED_STATEMENT_MACRO[definition.available_after_byte - 1 : definition.available_after_byte] == b")"


def _calls_and_definitions_shape(unit):
    """Everything about a unit's extracted calls and definitions except position.

    Used to compare the function path against the macro path over the same
    body text: positions necessarily differ (one is real-file coordinates
    from the start, the other goes through the macro remapping), but every
    other decision extraction makes about the body should not.
    """
    calls = [
        (c.name, c.raw_name, c.result_var, tuple(a.kind for a in c.args), tuple(a.text for a in c.args))
        for c in unit.calls
    ]
    definitions = {
        var: [(d.value.kind, d.value.text, d.value.call_id) for d in defs]
        for var, defs in unit.definitions.items()
    }
    return calls, definitions


def test_function_and_macro_paths_agree_on_the_same_body():
    # `_extract_calls` and `_record_plain_assignments` are now shared between
    # the function-unit and macro-unit paths, parameterized only by which
    # `Coordinates` they are given (`of_file` vs. `of_macro`). This test pins
    # that the choice of `Coordinates` changes position and nothing else --
    # a future extraction change (compound assignment `+=` is the obvious
    # next one; neither path handles it today) reaches both paths by
    # construction, but a `Coordinates` bug that also perturbed some other
    # decision would still show up here. The same body text -- one direct
    # call bound to a local, one plain assignment overwriting a parameter --
    # runs through both paths; only position should differ.
    body = (
        b"    __m128i t = _mm_mullo_epi32(a, b);\n"
        b"    dst = _mm_add_epi32(dst, t);\n"
    )
    function_source = b"void f(__m128i dst, __m128i a, __m128i b) {\n" + body + b"}\n"
    macro_source = (
        b"#define M(dst, a, b) do { \\\n"
        b"    __m128i t = _mm_mullo_epi32(a, b); \\\n"
        b"    dst = _mm_add_epi32(dst, t); \\\n"
        b"} while (0)\n"
    )

    function_unit = next(
        u for u in extract_units("t.c", function_source, load_knowledge()) if u.scope == "function"
    )
    macro_unit = next(u for u in extract_units("t.c", macro_source, load_knowledge()) if u.scope == "macro")

    assert _calls_and_definitions_shape(function_unit) == _calls_and_definitions_shape(macro_unit)


def test_of_file_never_calls_line_column(monkeypatch):
    # The one behaviour the merge must not change: today the function path
    # reads a call's line and column straight off tree-sitter's own
    # `start_point`, never through `line_column` -- that recomputation is the
    # macro path's job, needed only because a macro body is reparsed inside a
    # synthetic wrapper. A v1.2 review flagged exactly the risk this pins.
    #
    # A value comparison cannot express this: `line_column` and
    # `start_point` agree on ordinary source (confirmed across LF, CRLF,
    # bare CR and UTF-8), so a `place()` that switched `of_file` over to
    # `line_column` would still satisfy `(line, column, start_byte) ==
    # (start_point..., start_byte)`. Only forbidding the call itself can
    # catch that switch: `line_column` is made to raise before `place()`
    # runs, and an `of_file` that still returns cleanly is the proof it
    # never called it.
    def _must_not_be_called(source, byte):
        raise AssertionError("Coordinates.of_file must not call line_column")

    monkeypatch.setattr(extract_module, "line_column", _must_not_be_called)

    source = b"void f(__m128i a, __m128i b) {\n    __m128i r = _mm_add_epi32(a, b);\n}\n"
    root = parse_source(source).root_node
    call = next(iter_nodes(root, "call_expression"))

    line, column, start_byte = Coordinates.of_file(source).place(call)

    assert (line, column, start_byte) == (
        call.start_point[0] + 1,
        call.start_point[1] + 1,
        call.start_byte,
    )


def test_of_macro_always_calls_line_column(monkeypatch):
    # Symmetric to the pin above: the macro path's recomputation is not
    # incidental, it is the reason `of_macro` exists. If a future change
    # gave the macro path the file path's shortcut instead -- the opposite
    # mistake from the one above -- positions inside a macro body would stop
    # tracking `original_byte` remapping and this must fail, not merely
    # continue to agree by coincidence on whatever body this test happens
    # to use.
    macro_source = b"#define M(a, b) _mm_add_epi32(a, b)\n"
    root = parse_source(macro_source).root_node
    macro = reparse_macros(root, macro_source)[0]
    call = next(iter_nodes(macro.root, "call_expression"))

    def _must_be_called(source, byte):
        raise AssertionError("Coordinates.of_macro must call line_column")

    monkeypatch.setattr(extract_module, "line_column", _must_be_called)

    with pytest.raises(AssertionError, match="must call line_column"):
        Coordinates.of_macro(macro, macro_source).place(call)


# Structural reproductions (not literal source) of the confirmed-alias shapes
# the Task 4 review's I-2 finding enumerated across SVT-AV1 and VVenC:
# reversed operands (`_mm256_setr_m128i(lo, hi)` -> `_mm256_set_m128i((hi),
# (lo))`) and an arity that does not match the forwarded intrinsic's real
# arity (`LOAD8_S`/`pair_set_epi16`-shaped macros). Generic names keep this
# test self-contained -- no external checkout required.
_ALIAS_SHAPES = (
    b"#define WRAP_REVERSED(lo, hi) _mm256_set_m128i((hi), (lo))\n"
    b"#define WRAP_ARITY(a, b, c) _mm256_setr_epi32((a), (b), (c), 0, 0, 0, 0, 0)\n"
)

# P1: a body that drops a parameter -- writes it in the macro's own parameter
# list but never passes it to the forwarded call. `WRAP_NARROWED`'s `b` is
# exactly this. This must NOT resolve as an alias at all (see
# `is_forwarding_alias`'s docstring in `macros.py`): a rule that decides by
# checking whether a producer's result is a *member* of a following call's
# args -- F and P -- would otherwise see a phantom operand the forwarded
# intrinsic never actually receives, and report a finding on a call that
# never happened. This shape used to be included in `_ALIAS_SHAPES` above as
# a third "safe unfaithful forward"; it was not safe, it was a live false
# positive (see docs/verification.md and `tests/test_rule_pipeline.py`/
# `tests/test_rule_fusion.py` for the reproduction).
_DROPPED_PARAMETER_SHAPE = b"#define WRAP_NARROWED(a, b) _mm_set1_epi32((a))\n"


def test_confirmed_alias_targets_do_not_reach_an_operand_sensitive_rule_anchor():
    """Fast, fixture-based companion to the C1 corpus tripwire.

    A forwarding alias's call site presents the alias macro's OWN argument
    list -- whatever was written at the use site, following the macro's own
    parameter list -- never the forwarded intrinsic's actual argument list as
    written inside the macro body. Spec Section 4 makes no requirement that a
    forwarding body pass its parameters through faithfully, and real macros
    do not: SVT-AV1's `_mm256_setr_m128i` reverses two operands; its
    `LOAD8_S`-shaped macros record an arity that is not the forwarded
    intrinsic's real one. A rule that reads operand *position* or *arity*
    would be misled by such a call if the alias's confirmed target were ever
    one of that rule's anchors.

    `operand_sensitive_anchors` here is deliberately narrower than "every
    rule this alias's target could match": it is `suboptimal._TARGETS
    (S) | memory._SCALAR_SETS | memory._INSERTS (M) | widening._UNPACK
    | {_mm_mullo_epi16, _mm_mulhi_epi16} (W)` -- the three rules that
    actually read `call.args[N]` or `len(call.args)`. `fusion._*` and
    `pipeline._COMPARES` (F and P) are excluded on purpose, but not merely
    because an operand reversal or arity mismatch cannot mislead a
    membership check (that alone was the P1 gap: it is true of the
    *producer* call, but a rule decides membership by checking a *following*
    call's args, and if that following call is itself a forwarding alias
    that DROPPED a parameter, the call site still carries an operand for it
    -- see `_DROPPED_PARAMETER_SHAPE` and `is_forwarding_alias`'s docstring
    in `macros.py`). F and P are excluded here because `is_forwarding_alias`
    now refuses to register any alias that drops a parameter, which is the
    property that actually keeps their membership judgment sound; that
    refusal is what the assertion below on `_DROPPED_PARAMETER_SHAPE`
    checks, and `_mm_cmpgt_epi64` -- the confirmed target of VVenC's
    `_my_cmpgt_epi64`, which reaches rule P (see docs/verification.md's
    "DepQuant P: 3 vs 3") -- is a real alias that keeps every parameter, not
    an example of "safe regardless."

    This test only checks the hand-picked shapes here against the narrowed
    anchor set using the real `is_forwarding_alias`/`build_alias_map`
    machinery, so it runs without an external checkout and stays fast. It is
    NOT a cross-check against the reference codebases -- `test_verification.py::
    test_no_confirmed_alias_target_over_both_checkouts_reaches_an_operand_sensitive_anchor`
    is the real tripwire, run over SVT-AV1 and VVenC directly, and is what
    the release notes' safety claim is backed by.

    A failure here does not mean new code is wrong: it means one of these
    fixture shapes now resolves to a name inside the narrowed anchor set,
    which would mean S, M or W could be misled by an unfaithfully forwarded
    operand at that call site.
    """
    knowledge = load_knowledge()
    root = parse_source(_ALIAS_SHAPES).root_node
    macros = reparse_macros(root, _ALIAS_SHAPES)
    alias_targets = set(build_alias_map(root, _ALIAS_SHAPES, macros, knowledge).targets.values())
    assert alias_targets == {"_mm256_set_m128i", "_mm256_setr_epi32"}

    operand_sensitive_anchors = (
        suboptimal._TARGETS
        | memory._SCALAR_SETS
        | memory._INSERTS
        | widening._UNPACK
        | {"_mm_mullo_epi16", "_mm_mulhi_epi16"}
    )
    assert alias_targets.isdisjoint(operand_sensitive_anchors)


def test_a_body_that_drops_a_macro_parameter_is_never_registered_as_an_alias():
    """P1: the predicate that keeps F and P's membership judgment sound.

    `WRAP_NARROWED(a, b)` writes `b` in its own parameter list but never
    passes it to `_mm_set1_epi32`. If this were registered as an alias, a
    call site `WRAP_NARROWED(x, y)` would resolve to `_mm_set1_epi32` with
    args `(x, y)` -- the call site's own argument list, in the macro's
    parameter order -- even though the real forwarded call only ever
    receives `x`. A consumer rule checking membership of `y` in that
    resolved call's args would then see a phantom operand: this is exactly
    how `tests/test_rule_pipeline.py::
    test_reports_nothing_when_the_consuming_alias_dropped_the_producers_result`
    and its `test_rule_fusion.py` counterpart reproduce a real false
    positive at HEAD before this predicate existed.
    """
    knowledge = load_knowledge()
    root = parse_source(_DROPPED_PARAMETER_SHAPE).root_node
    macros = reparse_macros(root, _DROPPED_PARAMETER_SHAPE)
    assert len(macros) == 1
    assert is_forwarding_alias(macros[0]) is None
    assert build_alias_map(root, _DROPPED_PARAMETER_SHAPE, macros, knowledge).targets == {}


def test_a_clean_file_reports_no_unparsed_regions():
    source = b"""
#include <simde/x86/sse2.h>
void kernel(const void *p) {
    __m128i v = _mm_loadl_epi64((const __m128i *)p);
    (void)v;
}
"""
    units, unparsed = extract_units_and_diagnostics("clean.c", source, load_knowledge())
    assert unparsed == []
    assert [u.name for u in units] == ["kernel"]


def test_an_unparsable_file_still_yields_units_and_says_where_it_broke():
    # The point of the diagnostic: tree-sitter recovers rather than failing,
    # so a file like this reports findings AND loses some, with nothing in
    # the output to say which. VVdeC's InterpolationFilterX86.h is the real
    # case -- eleven registered-intrinsic call sites past the break were
    # never seen. The contract is only that a break is reported, not that
    # extraction stops.
    source = b"""
void before(const void *p) {
    __m128i a = _mm_loadl_epi64((const __m128i *)p);
    (void)a;
}
struct { ! ) ( ] template<<< >>>
void after(const void *p) {
    __m128i b = _mm_loadl_epi64((const __m128i *)p);
    (void)b;
}
"""
    units, unparsed = extract_units_and_diagnostics("broken.c", source, load_knowledge())
    assert unparsed, "a file tree-sitter cannot parse must report at least one span"
    start, end = unparsed[0]
    assert 1 <= start <= end <= source.count(b"\n") + 1
    assert any(u.name == "before" for u in units)


def test_analyze_reports_an_unparsed_file_as_a_warning_not_a_skip(tmp_path):
    path = tmp_path / "broken.c"
    path.write_text(
        "void kernel(const void *p) {\n"
        "    __m128i a = _mm_loadl_epi64((const __m128i *)p);\n"
        "    (void)a;\n"
        "}\n"
        "struct { ! ) ( ] template<<< >>>\n"
    )
    findings, _, errors = analyze([path])
    assert any("could not be fully parsed" in e for e in errors)
    # The file is warned about, not dropped: the call site before the break
    # is still reported.
    assert any(f.intrinsic == "_mm_loadl_epi64" for f in findings)


def test_an_unparsed_file_does_not_set_the_exit_code(tmp_path, capsys):
    # The documented contract is that the exit code is 0 unless the tool
    # itself errors. tree-sitter recovering from a construct it cannot parse
    # is not the tool erroring, and it is the normal case on preprocessor-
    # heavy C++ -- 362 of SVT-AV1's 561 files at the pinned revision. An
    # exit code that counted it would be 1 on nearly every real sweep.
    path = tmp_path / "broken.c"
    path.write_text(
        "void kernel(const void *p) {\n"
        "    __m128i a = _mm_loadl_epi64((const __m128i *)p);\n"
        "    (void)a;\n"
        "}\n"
        "struct { ! ) ( ] template<<< >>>\n"
    )
    assert cli_main([str(path), "--format", "json"]) == 0
    assert "could not be fully parsed" in capsys.readouterr().err


def test_a_diagnostic_is_still_an_ordinary_message():
    # Diagnostic subclasses str so that every existing consumer -- printing,
    # substring matching, collecting into a list -- keeps working. If that
    # stops being true, callers break silently rather than loudly.
    failure = Diagnostic("x.c: extraction failed: boom", Diagnostic.FAILURE)
    unparsed = Diagnostic("x.c: could not be fully parsed (lines 1-9)", Diagnostic.UNPARSED)
    assert isinstance(failure, str) and isinstance(unparsed, str)
    assert "extraction failed" in failure
    assert is_failure(failure) and not is_failure(unparsed)
    # An unlabelled string predates the distinction; treating it as benign
    # would be the unsafe direction.
    assert is_failure("some older warning")


def test_a_missing_input_path_sets_the_exit_code(tmp_path, capsys):
    # The other half of the exit-code contract. An unparsed file must not set
    # it; an input that is not there must. Both were once exit 0, which meant
    # a sweep over a path that had moved reported success with an empty
    # report -- the failure mode a script cannot see.
    missing = tmp_path / "not-here.c"
    assert cli_main([str(missing), "--format", "json"]) == 1
    assert "no such path" in capsys.readouterr().err


def test_an_unreadable_file_sets_the_exit_code(tmp_path, capsys):
    path = tmp_path / "locked.c"
    path.write_text("void f(void) {}\n")
    path.chmod(0o000)
    try:
        assert cli_main([str(tmp_path), "--format", "json"]) == 1
        assert "cannot read" in capsys.readouterr().err
    finally:
        path.chmod(0o644)


def test_dump_symbols_reports_a_missing_path_too(tmp_path, capsys):
    # --dump-symbols shares read_sources with the analysis path, so it shares
    # the contract: printing a short index over inputs that were not there
    # and calling it success is the same defect wearing a different flag.
    assert cli_main([str(tmp_path / "gone.c"), "--dump-symbols"]) == 1
    assert "no such path" in capsys.readouterr().err


_SUBSCRIPTED_TARGET = b"""
#include <simde/x86/sse4.1.h>

__m128i f(__m128i *v, __m128i a, __m128i b, __m128i acc) {
    v[9] = _mm_mullo_epi32(a, b);
    acc = _mm_add_epi32(acc, v[9]);
    return acc;
}
"""


def test_a_subscripted_target_keeps_result_var_narrow():
    """`result_var` and `result_lvalue` answer different questions.

    `result_var` names the identifier `redefined_between` tracks, so a write
    to `v[9]` reduces to `v`; `result_lvalue` keeps the subscript, because
    rule M asks whether writes landed in the same place and `v[9]` and
    `v[10]` do not. Unifying the function and macro extraction paths put
    both behind one function, which is exactly where someone later
    "completes" `result_var` into the full lvalue.

    That would not stay local to rule M. `v[9]` reaches rule F's operand
    check as `ValueKind.SYMBOL`, which the check ignores; a widened
    `result_var` would make F match subscripted targets and invent findings
    that do not exist today. The corpus comparison catches that, but only
    where the reference checkouts are present -- this pins it without them.
    """
    knowledge = load_knowledge()
    (unit,) = extract_units("sub.c", _SUBSCRIPTED_TARGET, knowledge)
    multiply = next(c for c in unit.calls if c.name == "_mm_mullo_epi32")
    add = next(c for c in unit.calls if c.name == "_mm_add_epi32")

    assert multiply.result_var == "v"
    assert multiply.result_lvalue == "v[9]"

    (operand,) = [arg for arg in add.args if arg.text == "v[9]"]
    assert operand.kind is ValueKind.SYMBOL

    ctx = Context(
        symbols=build_symbol_index([("sub.c", _SUBSCRIPTED_TARGET)], knowledge),
        knowledge=knowledge,
        config={},
    )
    assert list(fusion.FusionRule().match(unit, ctx)) == []
