from simde_lint.finding import Evidence, Finding, Impact, Reason


def _finding(**over) -> Finding:
    base = dict(
        type="S",
        rule="S.pshufb_guard",
        rule_mechanism="pshufb->tbl guard only",
        evidence=Evidence.A,
        impact=Impact.CONFIRMED,
        file="a.c",
        line=7,
        function="f",
        intrinsic="_mm_shuffle_epi8",
        rationale="guard removable",
        simde_insns=3,
        native_insns=1,
        suggestion="vqtbl1q_u8",
    )
    base.update(over)
    return Finding(**base)


def test_to_dict_emits_rule_mechanism_and_plain_enum_values():
    data = _finding().to_dict()
    assert data["rule_mechanism"] == "pshufb->tbl guard only"
    assert data["evidence"] == "A"
    assert data["impact"] == "confirmed"


def test_to_dict_omits_mask_source_when_absent():
    assert "mask_source" not in _finding().to_dict()


def test_to_dict_includes_mask_source_when_present():
    data = _finding(mask_source={"symbol": "t", "defined_at": "b.c:1", "resolution": "all_rows"}).to_dict()
    assert data["mask_source"]["resolution"] == "all_rows"


def test_to_dict_emits_null_reason_for_grade_a_or_b():
    assert _finding().to_dict()["reason"] is None


def test_to_dict_emits_the_reason_string_for_grade_c():
    data = _finding(evidence=Evidence.C, reason=Reason.UNRESOLVED).to_dict()
    assert data["reason"] == "unresolved"


def test_to_dict_omits_raw_name_when_absent():
    assert "raw_name" not in _finding().to_dict()


def test_to_dict_includes_raw_name_when_it_differs_from_the_canonical_spelling():
    data = _finding(raw_name="_my_cmpgt_epi64").to_dict()
    assert data["raw_name"] == "_my_cmpgt_epi64"
