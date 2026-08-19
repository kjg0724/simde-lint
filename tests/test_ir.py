from simde_lint.ir import Definition, FunctionUnit, ValueKind, ValueRef


def _unit() -> FunctionUnit:
    # `available_after_byte` — not `line` — is what the ordering methods
    # compare on, so the two definitions are placed at distinct byte offsets
    # (35 and 95) even though `line` is kept only as an identifying label.
    unit = FunctionUnit(name="f", file="a.c", start_line=1, end_line=20)
    unit.add_definition(
        Definition(
            "m", line=3, start_byte=30, available_after_byte=35,
            value=ValueRef(ValueKind.LITERAL_VECTOR, "setr", lanes=(0, 1)),
        )
    )
    unit.add_definition(
        Definition(
            "m", line=9, start_byte=90, available_after_byte=95,
            value=ValueRef(ValueKind.UNKNOWN, "load"),
        )
    )
    return unit


def test_definition_before_returns_latest_earlier_definition():
    unit = _unit()
    assert unit.definition_before("m", 50).line == 3
    assert unit.definition_before("m", 120).line == 9


def test_definition_before_returns_none_when_no_earlier_definition():
    assert _unit().definition_before("m", 20) is None
    assert _unit().definition_before("zzz", 999) is None


def test_redefined_between_detects_intervening_definition():
    unit = _unit()
    assert unit.redefined_between("m", 35, 120) is True
    assert unit.redefined_between("m", 35, 80) is False


def test_definition_before_excludes_a_definition_on_the_query_position():
    # The only assertions that distinguish `<` from `<=`. Rules ask whether a
    # value survived from one call to another, so a definition on the query
    # position itself must not count as reaching it.
    unit = _unit()
    assert unit.definition_before("m", 35) is None
    assert unit.definition_before("m", 95).line == 3


def test_redefined_between_excludes_definitions_on_either_boundary():
    # Definitions available at exactly byte 35 and byte 95 sit on the
    # boundaries and must not count.
    unit = _unit()
    assert unit.redefined_between("m", 35, 95) is False
    assert unit.redefined_between("m", 20, 100) is True


def test_definition_is_not_available_to_its_own_right_hand_side():
    # `res = f(res, ...)` — the `res` inside the call is the previous value,
    # so the new definition must not be visible at the call's own position.
    unit = FunctionUnit(name="f", file="a.c", start_line=1, end_line=9)
    unit.add_definition(
        Definition("res", line=3, start_byte=40, available_after_byte=80,
                   value=ValueRef(ValueKind.CALL_RESULT, "f", call_id=1))
    )
    assert unit.definition_before("res", 50) is None
    assert unit.definition_before("res", 90).available_after_byte == 80


def test_two_definitions_on_one_line_are_ordered():
    # Line numbers cannot separate these; byte offsets can.
    unit = FunctionUnit(name="f", file="a.c", start_line=1, end_line=9)
    unit.add_definition(
        Definition("m", line=5, start_byte=10, available_after_byte=20,
                   value=ValueRef(ValueKind.UNKNOWN, "first"))
    )
    unit.add_definition(
        Definition("m", line=5, start_byte=30, available_after_byte=40,
                   value=ValueRef(ValueKind.UNKNOWN, "second"))
    )
    assert unit.definition_before("m", 35).value.text == "first"
    assert unit.definition_before("m", 45).value.text == "second"
    assert unit.redefined_between("m", 20, 45) is True
    assert unit.redefined_between("m", 20, 35) is False
