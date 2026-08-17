import json

from simde_lint.finding import Evidence, Finding, Impact, Reason
from simde_lint.report.json import render_json
from simde_lint.report.text import render_text

FINDINGS = [
    Finding(
        type="S", rule="S.pshufb_guard", rule_mechanism="pshufb->tbl guard only",
        evidence=Evidence.A, impact=Impact.CONFIRMED, file="a.c", line=7,
        function="kernel", intrinsic="_mm_shuffle_epi8", rationale="guard is dead work",
        simde_insns=3, native_insns=1, suggestion="vqtbl1q_u8",
    ),
    Finding(
        type="R", rule="R.zero_init_partial_load", rule_mechanism="zero-init before partial load",
        evidence=Evidence.A, impact=Impact.DIAGNOSTIC, file="a.c", line=7,
        function="kernel", intrinsic="_mm_loadu_si32", rationale="zero vector then lane load",
        simde_insns=2, native_insns=1, suggestion="vld1q_lane_s32",
    ),
]


def test_text_shows_the_mechanism_next_to_the_type_on_every_line():
    output = render_text(FINDINGS)
    assert "S (pshufb->tbl guard only)" in output
    assert "R (zero-init before partial load)" in output


def test_text_summary_annotates_each_type_with_its_mechanism():
    output = render_text(FINDINGS)
    summary = output.split("Summary")[1]
    assert "pshufb->tbl guard only" in summary
    assert "zero-init before partial load" in summary


def test_text_keeps_both_findings_reported_at_the_same_location():
    output = render_text(FINDINGS)
    assert output.count("a.c:7") == 2


def test_json_is_parseable_and_carries_the_mechanism():
    data = json.loads(render_json(FINDINGS, simde_version="0.8.4"))
    assert data["simde_version"] == "0.8.4"
    assert len(data["findings"]) == 2
    # Findings are sorted by (file, line, type, rule), not input order, so
    # look the entry up by rule id rather than assuming a fixed index.
    pshufb_entry = next(f for f in data["findings"] if f["rule"] == "S.pshufb_guard")
    assert pshufb_entry["rule_mechanism"] == "pshufb->tbl guard only"


def test_json_summary_counts_by_rule_with_its_mechanism():
    data = json.loads(render_json(FINDINGS, simde_version="0.8.4"))
    assert data["summary"]["by_type"]["S"] == 1
    entry = data["summary"]["by_rule"]["S.pshufb_guard"]
    assert entry["count"] == 1
    assert entry["type"] == "S"
    assert entry["mechanism"] == "pshufb->tbl guard only"
    assert data["summary"]["by_evidence"]["A"] == 2


def test_summaries_keep_two_mechanisms_of_one_type_apart():
    # Type M has two implemented mechanisms; grouping by type alone would show
    # only one of them.
    both = FINDINGS + [
        Finding(
            type="M", rule="M.scalar_set_build",
            rule_mechanism="vector built from runtime scalars",
            evidence=Evidence.A, impact=Impact.DIAGNOSTIC, file="a.c", line=9,
            function="kernel", intrinsic="_mm_set_epi64x", rationale="spilled to stack",
            simde_insns=2, native_insns=2, suggestion="vsetq_lane_s64",
        ),
        Finding(
            type="M", rule="M.scalar_insert_chain",
            rule_mechanism="scalar insert chain",
            evidence=Evidence.A, impact=Impact.DIAGNOSTIC, file="a.c", line=11,
            function="kernel", intrinsic="_mm_insert_epi16", rationale="insert chain",
            simde_insns=6, native_insns=3, suggestion="vld1q_lane_s16",
        ),
    ]
    text = render_text(both)
    assert "vector built from runtime scalars" in text
    assert "scalar insert chain" in text
    data = json.loads(render_json(both, simde_version="0.8.4"))
    assert data["summary"]["by_type"]["M"] == 2
    assert set(data["summary"]["by_rule"]) >= {"M.scalar_set_build", "M.scalar_insert_chain"}


def test_empty_input_renders_without_error():
    assert "0 findings" in render_text([])
    assert json.loads(render_json([], simde_version="0.8.4"))["findings"] == []


UNKNOWN_COST_FINDING = Finding(
    type="F", rule="F.mul_add_no_fuse", rule_mechanism="multiply-add not fused",
    evidence=Evidence.A, impact=Impact.CONFIRMED, file="a.c", line=3,
    function="kernel", intrinsic="_mm_madd_epi16",
    rationale="no fused multiply-accumulate form is established for this intrinsic",
    simde_insns=4, native_insns=None, suggestion=None,
)


def test_text_renders_an_unknown_cost_as_unknown_not_as_a_number():
    output = render_text([UNKNOWN_COST_FINDING])
    assert "None" not in output
    assert "instruction count unknown" in output
    assert "no suggestion offered" in output


def test_json_emits_null_for_an_unknown_cost():
    data = json.loads(render_json([UNKNOWN_COST_FINDING], simde_version="0.8.4"))
    finding = data["findings"][0]
    assert finding["native_insns"] is None
    assert finding["suggestion"] is None
    assert finding["simde_insns"] == 4


C_GUARD_REQUIRED_FINDING = Finding(
    type="S", rule="S.pshufb_guard", rule_mechanism="pshufb->tbl guard only",
    evidence=Evidence.C, reason=Reason.GUARD_REQUIRED, impact=Impact.CONFIRMED,
    file="a.c", line=12, function="kernel", intrinsic="_mm_shuffle_epi8",
    rationale="inline mask has a lane in the unsafe [16,127] middle range",
    simde_insns=None, native_insns=None, suggestion=None,
)


def test_text_shows_the_reason_beside_grade_c():
    output = render_text([C_GUARD_REQUIRED_FINDING])
    assert "evidence=C (guard_required)" in output


def test_text_shows_no_reason_suffix_for_a_or_b():
    output = render_text(FINDINGS)
    assert "evidence=A (" not in output


def test_json_carries_the_reason_next_to_evidence():
    data = json.loads(render_json([C_GUARD_REQUIRED_FINDING], simde_version="0.8.4"))
    finding = data["findings"][0]
    assert finding["evidence"] == "C"
    assert finding["reason"] == "guard_required"


def test_json_reason_is_null_for_grade_a():
    data = json.loads(render_json(FINDINGS, simde_version="0.8.4"))
    assert all(f["reason"] is None for f in data["findings"])


RAW_NAME_FINDING = Finding(
    type="P", rule="P.cmp_immediate_use", rule_mechanism="compare consumed by the next call",
    evidence=Evidence.A, impact=Impact.DIAGNOSTIC, file="a.c", line=4,
    function="kernel", intrinsic="_mm_cmpgt_epi64", raw_name="_my_cmpgt_epi64",
    rationale="consumed by the next call",
    simde_insns=1, native_insns=1, suggestion=None,
)


def test_text_shows_the_raw_spelling_when_it_differs_from_the_canonical_name():
    output = render_text([RAW_NAME_FINDING])
    assert "_mm_cmpgt_epi64 (source spelling: _my_cmpgt_epi64)" in output


def test_text_omits_the_raw_spelling_when_it_matches_the_canonical_name():
    output = render_text(FINDINGS)
    assert "source spelling" not in output


def test_json_carries_raw_name_only_when_it_differs():
    data = json.loads(render_json([RAW_NAME_FINDING] + FINDINGS, simde_version="0.8.4"))
    by_rule = {f["rule"]: f for f in data["findings"]}
    assert by_rule["P.cmp_immediate_use"]["raw_name"] == "_my_cmpgt_epi64"
    assert "raw_name" not in by_rule["S.pshufb_guard"]


def test_both_renderers_order_a_tie_at_one_location_identically():
    # Two Type M mechanisms on one statement share file, line and type, so
    # only the rule id separates them. Order must not depend on how the caller
    # assembled the list.
    def m(rule, mechanism):
        return Finding(
            type="M", rule=rule, rule_mechanism=mechanism,
            evidence=Evidence.A, impact=Impact.DIAGNOSTIC, file="a.c", line=9,
            function="kernel", intrinsic="_mm_set_epi64x", rationale="r",
            simde_insns=2, native_insns=2, suggestion="vsetq_lane_s64",
        )

    chain = m("M.scalar_insert_chain", "scalar insert chain")
    build = m("M.scalar_set_build", "vector built from runtime scalars")

    forward = json.loads(render_json([chain, build], simde_version="0.8.4"))["findings"]
    reverse = json.loads(render_json([build, chain], simde_version="0.8.4"))["findings"]
    assert [f["rule"] for f in forward] == [f["rule"] for f in reverse]
    assert render_text([chain, build]) == render_text([build, chain])
