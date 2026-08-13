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
    assert definition.value.kind == ValueKind.CALL_RESULT


def test_records_the_result_variable_of_a_call():
    call = next(c for c in _unit().calls if c.name == "_mm_loadu_si32")
    assert call.result_var == "data"
