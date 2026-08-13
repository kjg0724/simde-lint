from simde_lint.ir import Definition, FunctionUnit, ValueKind, ValueRef


def _unit() -> FunctionUnit:
    unit = FunctionUnit(name="f", file="a.c", start_line=1, end_line=20)
    unit.add_definition(Definition("m", 3, ValueRef(ValueKind.LITERAL_VECTOR, "setr", lanes=(0, 1))))
    unit.add_definition(Definition("m", 9, ValueRef(ValueKind.UNKNOWN, "load")))
    return unit


def test_definition_before_returns_latest_earlier_definition():
    unit = _unit()
    assert unit.definition_before("m", 5).line == 3
    assert unit.definition_before("m", 12).line == 9


def test_definition_before_returns_none_when_no_earlier_definition():
    assert _unit().definition_before("m", 2) is None
    assert _unit().definition_before("zzz", 99) is None


def test_redefined_between_detects_intervening_definition():
    unit = _unit()
    assert unit.redefined_between("m", 3, 12) is True
    assert unit.redefined_between("m", 3, 8) is False
