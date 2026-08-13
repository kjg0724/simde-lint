from simde_lint.finding import Evidence, Finding, Impact


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
