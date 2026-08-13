from simde_lint.knowledge import load_knowledge


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
    patterns = load_knowledge().patterns
    assert set(patterns) == {
        "S.pshufb_guard",
        "W.mul16_widen_roundtrip",
        "F.mul_add_no_fuse",
        "M.scalar_insert_chain",
        "P.cmp_immediate_use",
    }


def test_every_cost_entry_cites_a_simde_source_line():
    knowledge = load_knowledge()
    for entry in list(knowledge.redundant.values()) + list(knowledge.patterns.values()):
        assert entry.source.startswith("x86/")
        assert entry.source.split(":")[-1].isdigit()
        assert entry.suggestion


def test_pattern_costs_carry_the_expected_values():
    patterns = load_knowledge().patterns
    assert patterns["S.pshufb_guard"].suggestion == "vqtbl1q_u8"
    assert patterns["W.mul16_widen_roundtrip"].suggestion == "vmull_s16"
    assert patterns["F.mul_add_no_fuse"].suggestion == "vmlal_s32"
