from simde_lint.finding import Evidence, Finding, Reason, file_sort_key, sort_key


def _finding(**over) -> Finding:
    base = dict(
        type="S",
        rule="S.pshufb_guard",
        rule_mechanism="pshufb->tbl guard only",
        evidence=Evidence.A,
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


def test_a_function_finding_carries_no_macro_name():
    data = _finding().to_dict()
    assert data["scope"] == "function"
    assert data["function"] == "f"
    assert data["macro"] is None


def test_a_macro_finding_carries_no_function_name():
    data = _finding(scope="macro", function=None, macro="LOAD4").to_dict()
    assert data["scope"] == "macro"
    assert data["function"] is None
    assert data["macro"] == "LOAD4"


# v1.1: findings are ordered benchmarked-type-first by default (the types
# whose isolated-kernel microbenchmarks showed a speedup before the rest, then
# evidence A before B before C), because a large sweep is dominated by the
# un-benchmarked types and they buried the ones a reader needs to act on.
# --sort file keeps the pre-v1.1 order.

_BACKED_A = _finding(type="S", evidence=Evidence.A, file="a.c", line=20)
_BACKED_B = _finding(type="S", evidence=Evidence.B, file="b.c", line=1)
_BACKED_C = _finding(type="S", evidence=Evidence.C, file="a.c", line=5)
_UNBACKED_A = _finding(type="R", evidence=Evidence.A, file="a.c", line=1)


def test_sort_key_orders_benchmarked_types_before_the_rest():
    mixed = [_UNBACKED_A, _BACKED_C]
    assert sorted(mixed, key=sort_key) == [_BACKED_C, _UNBACKED_A]


def test_sort_key_orders_evidence_a_before_b_before_c_within_one_rank():
    mixed = [_BACKED_C, _BACKED_A, _BACKED_B]
    assert sorted(mixed, key=sort_key) == [_BACKED_A, _BACKED_B, _BACKED_C]


def test_sort_key_falls_back_to_location_within_one_rank_and_evidence():
    # _BACKED_A (a.c:20) and a same-rank-and-evidence sibling at a.c:3 must
    # land in line order once type rank and evidence are tied.
    earlier = _finding(type="S", evidence=Evidence.A, file="a.c", line=3)
    assert sorted([_BACKED_A, earlier], key=sort_key) == [earlier, _BACKED_A]


def test_file_sort_key_reproduces_the_pre_v1_1_location_order():
    # (file, line, type, rule): a.c:5 before a.c:20 before b.c:1, regardless
    # of type rank or evidence.
    ordered = sorted([_BACKED_B, _BACKED_A, _BACKED_C], key=file_sort_key)
    assert ordered == [_BACKED_C, _BACKED_A, _BACKED_B]


# `function` became `str | None` once a finding could sit in a macro body.
# Neither sort key reads `function`, so a `None` must never reach a `<`
# comparison against another finding's `str` function name. The two findings
# below tie on every component either key actually reads — same file, line,
# type, rule, impact, evidence — and differ only in scope/function/macro, so
# both keys compare them as equal. That is deliberate: if `function` were
# ever appended to either key, comparing these two would immediately raise
# `TypeError: '<' not supported between instances of 'NoneType' and 'str'`,
# because every earlier component ties and `function` is the first one that
# differs. A pair that differs in `line` would never reach that comparison —
# tuple comparison stops at the first differing component — so it would stay
# green even after that regression.
_MACRO_FINDING = _finding(scope="macro", function=None, macro="LOAD4")
_FUNCTION_FINDING = _finding(scope="function", function="f", macro=None)


def test_sort_key_ties_a_macro_finding_and_a_function_finding_that_share_every_component():
    # Keys are equal, so a stable sort preserves input order either way.
    assert sorted([_FUNCTION_FINDING, _MACRO_FINDING], key=sort_key) == [
        _FUNCTION_FINDING,
        _MACRO_FINDING,
    ]
    assert sorted([_MACRO_FINDING, _FUNCTION_FINDING], key=sort_key) == [
        _MACRO_FINDING,
        _FUNCTION_FINDING,
    ]


def test_file_sort_key_ties_a_macro_finding_and_a_function_finding_that_share_every_component():
    assert sorted([_FUNCTION_FINDING, _MACRO_FINDING], key=file_sort_key) == [
        _FUNCTION_FINDING,
        _MACRO_FINDING,
    ]
    assert sorted([_MACRO_FINDING, _FUNCTION_FINDING], key=file_sort_key) == [
        _MACRO_FINDING,
        _FUNCTION_FINDING,
    ]
