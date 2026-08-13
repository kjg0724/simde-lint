import json

from simde_lint.finding import Evidence, Finding, Impact
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
    assert data["findings"][0]["rule_mechanism"] == "pshufb->tbl guard only"


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
