from pathlib import Path

import pytest

from simde_lint.knowledge import load_knowledge
from simde_lint.rules import fusion, memory, pipeline, suboptimal, widening


def test_loads_redundant_intrinsics_with_source_citation():
    knowledge = load_knowledge()
    info = knowledge.redundant["_mm_loadu_si32"]
    assert info.simde_insns == 2
    assert info.native_insns == 1
    assert info.suggestion == "vld1q_lane_s32"
    assert info.source.startswith("x86/sse2.h:")


def test_records_the_simde_version_the_tables_were_derived_from():
    assert load_knowledge().simde_version == "0.8.4"


def test_resolves_a_native_alias_to_its_simde_name():
    assert load_knowledge().aliases["simde_mm_shuffle_epi8"] == "_mm_shuffle_epi8"


def test_wrapper_macros_record_the_declarator_argument_index():
    assert load_knowledge().wrapper_macros["DECLARE_ALIGNED"] == 2


def test_every_rule_that_reports_costs_has_a_pattern_entry():
    # Five rules match a set of intrinsics and are keyed per intrinsic; W
    # matches a fixed call sequence rather than a registered intrinsic and
    # stays a single rule-level entry (design spec, W's cost data note).
    knowledge = load_knowledge()
    assert set(knowledge.patterns) == {
        "S.pshufb_guard",
        "F.mul_add_no_fuse",
        "M.scalar_insert_chain",
        "M.scalar_set_build",
        "P.cmp_immediate_use",
    }
    assert set(knowledge.rule_costs) == {"W.mul16_widen_roundtrip"}


def test_every_cost_entry_cites_a_simde_source_line():
    knowledge = load_knowledge()
    entries = list(knowledge.redundant.values()) + list(knowledge.rule_costs.values())
    for table in knowledge.patterns.values():
        entries.extend(table.values())
    for entry in entries:
        assert entry.source.startswith("x86/")
        assert entry.source.split(":")[-1].isdigit()


def test_pattern_costs_carry_the_expected_values():
    knowledge = load_knowledge()
    assert knowledge.patterns["S.pshufb_guard"]["_mm_shuffle_epi8"].suggestion == "vqtbl1q_u8"
    assert knowledge.rule_costs["W.mul16_widen_roundtrip"].suggestion == "vmull_s16"
    assert knowledge.patterns["F.mul_add_no_fuse"]["_mm_mul_epi32"].suggestion == "vmlal_s32"


def test_unknown_cost_and_suggestion_load_as_none():
    # AArch64 has no pairwise 16-to-32 multiply-accumulate, so this
    # intrinsic's native cost and suggested fused instruction cannot be
    # established (cost-data.md, Rule F). `unknown` in the YAML must load as
    # None, not as the literal string "unknown" or a zero.
    madd = load_knowledge().patterns["F.mul_add_no_fuse"]["_mm_madd_epi16"]
    assert madd.simde_insns == 4
    assert madd.native_insns is None
    assert madd.suggestion is None


def test_an_uncountable_expansion_still_records_its_established_fused_form():
    # _mm256_mullo_epi32 falls through to SIMDe's portable per-element loop.
    # The loop carries SIMDE_VECTORIZE, so what is emitted is the compiler's
    # choice and neither count can be read from the source. That is a
    # separate fact from whether a fused form exists: mullo_epi32 does not
    # widen, so the established 128-bit vmlaq_s32 case applies twice. The
    # schema must be able to say "no count, but a known replacement" --
    # collapsing the two would report an established transform as
    # unresolved.
    entry = load_knowledge().patterns["F.mul_add_no_fuse"]["_mm256_mullo_epi32"]
    assert entry.simde_insns is None
    assert entry.native_insns is None
    assert entry.suggestion == "vmlaq_s32"


def test_cost_lookup_by_rule_and_intrinsic_returns_the_matching_entry():
    knowledge = load_knowledge()
    shuffle_128 = knowledge.cost("S.pshufb_guard", "_mm_shuffle_epi8")
    shuffle_256 = knowledge.cost("S.pshufb_guard", "_mm256_shuffle_epi8")
    # The bug this schema fixes: a 256-bit finding must not silently receive
    # the 128-bit entry's numbers or citation.
    assert (shuffle_128.simde_insns, shuffle_128.native_insns) == (3, 1)
    assert (shuffle_256.simde_insns, shuffle_256.native_insns) == (6, 2)
    assert shuffle_128.source != shuffle_256.source


def test_cost_lookup_for_a_rule_level_rule_ignores_the_intrinsic_argument():
    knowledge = load_knowledge()
    assert knowledge.cost("W.mul16_widen_roundtrip") == knowledge.rule_costs["W.mul16_widen_roundtrip"]


def test_cost_lookup_without_an_intrinsic_raises_for_a_per_intrinsic_rule():
    with pytest.raises(KeyError):
        load_knowledge().cost("S.pshufb_guard")


def test_every_intrinsic_a_rule_can_match_has_a_cost_entry_citing_that_intrinsic():
    """Schema guard for C1: a finding's cost must describe the intrinsic it
    was matched against, never a sibling width's.

    The matched set for each rule is read from the rule module's own
    constants rather than copied here by hand, so a rule that grows to cover
    a new intrinsic without adding a cost entry (or vice versa) fails this
    test instead of silently printing a borrowed citation.

    R.zero_init_partial_load is not listed below: RedundantRule looks up
    `ctx.knowledge.redundant[call.name]` directly with no separate constant,
    so its matched set is redundant.yaml's own keys by construction and
    cannot drift from it — covered by the redundant.yaml tests above.
    """
    knowledge = load_knowledge()
    matched_by_rule = {
        "S.pshufb_guard": suboptimal._TARGETS,
        "F.mul_add_no_fuse": fusion._MULTIPLIES,
        "M.scalar_insert_chain": memory._INSERTS,
        "M.scalar_set_build": memory._SCALAR_SETS,
        "P.cmp_immediate_use": pipeline._COMPARES,
    }
    for rule_id, intrinsics in matched_by_rule.items():
        table = knowledge.patterns[rule_id]
        assert set(table) == set(intrinsics), f"{rule_id} entries do not match what the rule matches"
        for intrinsic, cost in table.items():
            assert cost.key == intrinsic


def test_consumed_operands_carry_no_cost_entry():
    """fusion._ADDS, fusion._WIDENING and widening._UNPACK are operands a
    match consumes on the way to a finding, not the intrinsic the finding is
    reported against — F's and W's findings are anchored at the multiply, not
    the add/widen/unpack. Requiring a cost entry for them would be requiring
    data nothing ever reads. Explicit here so the exclusion is a documented
    decision rather than a gap this test happens not to notice.
    """
    all_intrinsics = {
        intrinsic for table in load_knowledge().patterns.values() for intrinsic in table
    }
    assert fusion._ADDS.isdisjoint(all_intrinsics)
    assert fusion._WIDENING.isdisjoint(all_intrinsics)
    assert widening._UNPACK.isdisjoint(all_intrinsics)


def test_disagreeing_simde_versions_fail_loudly(tmp_path):
    # The tables describe one SIMDe version. Loading a mismatched set would
    # report counts from one version against source lines from another, so it
    # must raise rather than return the inconsistent result.
    source = Path(__file__).parent.parent / "src" / "simde_lint" / "knowledge"
    for name in ("redundant.yaml", "patterns.yaml", "aliases.yaml", "wrapper_macros.yaml"):
        (tmp_path / name).write_text(
            (source / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    stale = (tmp_path / "aliases.yaml").read_text(encoding="utf-8")
    (tmp_path / "aliases.yaml").write_text(
        stale.replace('simde_version: "0.8.4"', 'simde_version: "0.8.3"'), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="simde_version"):
        load_knowledge(tmp_path)
