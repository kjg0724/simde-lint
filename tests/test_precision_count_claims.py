"""The census's quantitative claims, aimed at a false number.

`docs/precision/verify.py` is the independent checker for the precision
census, so it is loaded by path rather than imported. Four of its checks read
a number out of the finding's rationale and three of them went on to ignore
it: how many inserts a chain holds, how many of a `set` call's arguments are
runtime values, and the line each of F's and W's producers sits on. Parsing a
number and returning agreement regardless leaves the only check that reads it
unable to reject a wrong one, and a census at 100% says nothing about it.
Review found them one at a time, each after the previous was fixed.

The insert-chain check had a second form of the same weakness: it tested the
rule's threshold against the longest run in the span rather than against the
claimed target's own, so two inserts on `dd[0]` passed where `dd[1]` happened
to have three.

Correct corpus output cannot reach the rejection branches, so the rationale
here is written false on purpose.
"""

import importlib.util
from pathlib import Path

import tree_sitter_cpp
from tree_sitter import Language, Parser

_SCRIPT = Path(__file__).resolve().parents[1] / "docs" / "precision" / "verify.py"
_PARSER = Parser(Language(tree_sitter_cpp.language()))

_CHAIN = b"""
void f(__m128i v, int a, int b, int c) {
    v = _mm_insert_epi32(v, a, 0);
    v = _mm_insert_epi32(v, b, 1);
    v = _mm_insert_epi32(v, c, 2);
    (void)v;
}
"""

_SET = b"""
void g(long long m) {
    __m128i p = _mm_set_epi64x(0, m);
    (void)p;
}
"""


def _module():
    spec = importlib.util.spec_from_file_location("verify", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ctx(module, tmp_path, source, name):
    path = tmp_path / name
    path.write_bytes(source)
    return module, module.read_calls(str(path), _PARSER, {})


def _chain_claim(count, target="v", first=3, last=5):
    return {
        "rationale": (
            f"{count} scalar insert operations assemble {target} between lines "
            f"{first} and {last}; consider whether a native load or "
            f"vector-construction idiom better expresses the surrounding access "
            f"pattern (x86/sse4.1.h:1598)"
        ),
    }


def _set_claim(runtime, total, line=3):
    return {
        "line": line,
        "intrinsic": "_mm_set_epi64x",
        "rationale": (
            f"_mm_set_epi64x assembles {runtime} runtime scalar argument(s) of "
            f"{total} into one vector through SIMDe's set-constructor path; "
            f"emitted cost depends on argument shape and compiler optimization "
            f"(x86/sse2.h:5811)"
        ),
    }


def test_the_true_insert_count_agrees(tmp_path):
    module, ctx = _ctx(_module(), tmp_path, _CHAIN, "chain.c")
    ok, why = module.check_insert_chain(_chain_claim(3), ctx)
    assert ok is True, why


def test_a_wrong_insert_count_is_a_disagreement(tmp_path):
    module, ctx = _ctx(_module(), tmp_path, _CHAIN, "chain.c")
    ok, why = module.check_insert_chain(_chain_claim(5), ctx)
    assert ok is False
    assert "counted 3" in why


def test_an_unparsed_insert_claim_is_unreadable(tmp_path):
    module, ctx = _ctx(_module(), tmp_path, _CHAIN, "chain.c")
    ok, why = module.check_insert_chain({"rationale": "three inserts, in words"}, ctx)
    assert ok is None
    assert "not parsed" in why


def test_the_true_runtime_count_agrees(tmp_path):
    module, ctx = _ctx(_module(), tmp_path, _SET, "set.c")
    ok, why = module.check_set_build(_set_claim(1, 2), ctx)
    assert ok is True, why


def test_a_wrong_runtime_count_is_a_disagreement(tmp_path):
    module, ctx = _ctx(_module(), tmp_path, _SET, "set.c")
    ok, why = module.check_set_build(_set_claim(2, 2), ctx)
    assert ok is False
    assert "counted 1 of 2" in why


def test_a_wrong_argument_total_is_a_disagreement(tmp_path):
    module, ctx = _ctx(_module(), tmp_path, _SET, "set.c")
    ok, why = module.check_set_build(_set_claim(1, 4), ctx)
    assert ok is False


def test_an_unparsed_set_claim_is_unreadable(tmp_path):
    module, ctx = _ctx(_module(), tmp_path, _SET, "set.c")
    claim = _set_claim(1, 2)
    claim["rationale"] = "_mm_set_epi64x assembles some runtime scalars"
    ok, why = module.check_set_build(claim, ctx)
    assert ok is None
    assert "not parsed" in why

# `dd[0]` and `dd[1]` are different vectors sharing a prefix, which is the
# shape the checker's target matching exists to keep apart: two inserts on
# the first, three on the second, in one span.
_TWO_TARGETS = b"""
void h(__m128i dd[2], int w, int x, int y, int z) {
    dd[0] = _mm_insert_epi32(dd[0], w, 0);
    dd[0] = _mm_insert_epi32(dd[0], x, 1);
    dd[1] = _mm_insert_epi32(dd[1], y, 0);
    dd[1] = _mm_insert_epi32(dd[1], z, 1);
    dd[1] = _mm_insert_epi32(dd[1], w, 2);
    (void)dd;
}
"""

_FUSION = b"""
void p(__m128i u, __m128i v, __m128i acc) {
    __m128i prod = _mm_mullo_epi32(u, v);
    acc = _mm_add_epi32(acc, prod);
    (void)acc;
}
"""


def _fusion_claim(mul_line, add_line=4):
    return {
        "line": 3,
        "intrinsic": "_mm_mullo_epi32",
        "rationale": (
            f"_mm_mullo_epi32 at line {mul_line} reaches _mm_add_epi32 at line "
            f"{add_line}; SIMDe emits them separately (x86/sse4.1.h:1)"
        ),
    }


def test_a_claim_on_a_target_below_the_threshold_is_a_disagreement(tmp_path):
    # Two inserts on `dd[0]`, three on `dd[1]`, in one span. The claim names
    # `dd[0]`, so `dd[1]`'s run is irrelevant: `dd[0]` is not a chain the rule
    # may report. The threshold was tested against the longest run in the
    # span, which `dd[1]` met.
    module, ctx = _ctx(_module(), tmp_path, _TWO_TARGETS, "two.c")
    ok, why = module.check_insert_chain(_chain_claim(2, target="dd[0]", first=3, last=7), ctx)
    assert ok is False
    assert "below the threshold" in why


def test_a_claim_on_the_qualifying_target_of_two_agrees(tmp_path):
    # The control for the above: same span, the claim names the target that
    # does meet the threshold, and the other run is reported beside it.
    module, ctx = _ctx(_module(), tmp_path, _TWO_TARGETS, "two.c")
    ok, why = module.check_insert_chain(_chain_claim(3, target="dd[1]", first=3, last=7), ctx)
    assert ok is True, why
    assert "also holds" in why


def test_a_fusion_claim_naming_another_line_is_a_disagreement(tmp_path):
    # The rationale states the multiply's line and the finding carries one.
    # The checker located the multiply by the field, so the sentence could
    # name any line and still agree.
    module, ctx = _ctx(_module(), tmp_path, _FUSION, "fuse.c")
    ok, why = module.check_fusion(_fusion_claim(99), ctx)
    assert ok is False
    assert "claims line 99, the finding is at line 3" in why


def test_a_fusion_claim_naming_its_own_line_agrees(tmp_path):
    module, ctx = _ctx(_module(), tmp_path, _FUSION, "fuse.c")
    ok, why = module.check_fusion(_fusion_claim(3), ctx)
    assert ok is True, why

_WIDENING = b"""
void q(__m128i u, __m128i v) {
    __m128i lo = _mm_mullo_epi16(u, v);
    __m128i hi = _mm_mulhi_epi16(u, v);
    __m128i r = _mm_unpacklo_epi16(lo, hi);
    (void)r;
}
"""


def _widening_claim(lo_line):
    return {
        "line": 3,
        "intrinsic": "_mm_mullo_epi16",
        "rationale": (
            f"_mm_mullo_epi16 at line {lo_line} and _mm_mulhi_epi16 at line 4 "
            f"share operands and feed _mm_unpacklo_epi16 at line 5 "
            f"(x86/sse2.h:1)"
        ),
    }


def test_a_widening_claim_naming_another_line_is_a_disagreement(tmp_path):
    module, ctx = _ctx(_module(), tmp_path, _WIDENING, "widen.c")
    ok, why = module.check_widening(_widening_claim(99), ctx)
    assert ok is False
    assert "claims line 99, the finding is at line 3" in why


def test_a_widening_claim_naming_its_own_line_agrees(tmp_path):
    module, ctx = _ctx(_module(), tmp_path, _WIDENING, "widen.c")
    ok, why = module.check_widening(_widening_claim(3), ctx)
    assert ok is True, why

_PIPELINE = b"""
void r(__m128i u, __m128i v) {
    __m128i m = _mm_cmpgt_epi64(u, v);
    __m128i s = _mm_blendv_epi8(u, v, m);
    (void)s;
}
"""

_ALIASED = b"""
#define _my_cmpgt_epi64(a, b) _mm_cmpgt_epi64((a), (b))
void t(__m128i u, __m128i v) {
    __m128i m = _my_cmpgt_epi64(u, v);
    __m128i s = _mm_blendv_epi8(u, v, m);
    (void)s;
}
"""


def _pipeline_claim(cmp_name="_mm_cmpgt_epi64", cmp_line=3, intrinsic=None, raw=None):
    claim = {
        "line": cmp_line if intrinsic is None else 4,
        "intrinsic": intrinsic or "_mm_cmpgt_epi64",
        "rationale": (
            f"{cmp_name} at line {cmp_line} is consumed by _mm_blendv_epi8 at "
            f"line {cmp_line + 1} with no independent work between them; source "
            f"order approximates scheduling order (x86/sse4.2.h:1)"
        ),
    }
    if raw:
        claim["raw_name"] = raw
    return claim


def test_a_pipeline_claim_naming_another_producer_is_a_disagreement(tmp_path):
    # P's rationale states the compare and its line, and the checker read
    # only the consumer half of the sentence.
    module, ctx = _ctx(_module(), tmp_path, _PIPELINE, "pipe.c")
    ok, why = module.check_pipeline(_pipeline_claim(cmp_name="_mm_cmpeq_epi64"), ctx)
    assert ok is False
    assert "claims _mm_cmpeq_epi64" in why


def test_a_pipeline_claim_naming_another_line_is_a_disagreement(tmp_path):
    module, ctx = _ctx(_module(), tmp_path, _PIPELINE, "pipe.c")
    claim = _pipeline_claim()
    claim["line"] = 9
    ok, why = module.check_pipeline(claim, ctx)
    assert ok is False
    assert "claims line 3" in why


def test_a_pipeline_claim_naming_its_own_producer_agrees(tmp_path):
    module, ctx = _ctx(_module(), tmp_path, _PIPELINE, "pipe.c")
    ok, why = module.check_pipeline(_pipeline_claim(), ctx)
    assert ok is True, why


def test_a_macro_aliased_producer_is_compared_by_its_resolved_name(tmp_path):
    # The rationale names the resolved intrinsic and the source text spells
    # the file-local alias. Comparing the claim against the spelling made
    # three real VVenC findings disagree; the lookup still needs the spelling.
    module, ctx = _ctx(_module(), tmp_path, _ALIASED, "alias.c")
    claim = _pipeline_claim(cmp_line=4)
    claim["raw_name"] = "_my_cmpgt_epi64"
    ok, why = module.check_pipeline(claim, ctx)
    assert ok is True, why


def test_a_fusion_claim_naming_another_producer_is_a_disagreement(tmp_path):
    module, ctx = _ctx(_module(), tmp_path, _FUSION, "fuse.c")
    claim = _fusion_claim(3)
    claim["rationale"] = claim["rationale"].replace(
        "_mm_mullo_epi32 at line", "_mm_mullo_epi16 at line", 1)
    ok, why = module.check_fusion(claim, ctx)
    assert ok is False
    assert "claims _mm_mullo_epi16" in why


def test_a_fusion_claim_naming_a_hop_that_is_absent_is_a_disagreement(tmp_path):
    # The hop is optional in the sentence and was examined only after the
    # direct branches had already returned agreement.
    module, ctx = _ctx(_module(), tmp_path, _FUSION, "fuse.c")
    claim = _fusion_claim(3)
    # The hop phrase the rule appends, with a line nothing is on.
    claim["rationale"] = claim["rationale"].replace(
        "at line 4;", "at line 4 through _mm_cvtepi16_epi32 at line 99;", 1)
    ok, why = module.check_fusion(claim, ctx)
    assert ok is False
    assert "the hop" in why


def test_a_widening_grade_c_claim_is_read_rather_than_skipped(tmp_path):
    # The two C forms say "feed ... but ..." where the A form says "share
    # operands and feed". Parsing only the A form reported the others
    # unreadable, so their names and lines went unchecked.
    module, ctx = _ctx(_module(), tmp_path, _WIDENING, "widen.c")
    claim = _widening_claim(3)
    claim["rationale"] = (
        "_mm_mullo_epi16 at line 3 and _mm_mulhi_epi16 at line 4 feed "
        "_mm_unpacklo_epi16 at line 5, but an operand is reassigned between "
        "them, so the two halves are not two halves of one product"
    )
    ok, why = module.check_widening(claim, ctx)
    assert ok is True, why
    assert "both halves feed" in why


def test_a_widening_grade_c_claim_naming_another_producer_is_a_disagreement(tmp_path):
    module, ctx = _ctx(_module(), tmp_path, _WIDENING, "widen.c")
    claim = _widening_claim(3)
    claim["rationale"] = (
        "_mm_mullo_epi32 at line 3 and _mm_mulhi_epi16 at line 4 feed "
        "_mm_unpacklo_epi16 at line 5, but an operand is reassigned between them"
    )
    ok, why = module.check_widening(claim, ctx)
    assert ok is False
    assert "claims _mm_mullo_epi32" in why


def test_a_set_claim_naming_another_intrinsic_is_a_disagreement(tmp_path):
    module, ctx = _ctx(_module(), tmp_path, _SET, "set.c")
    claim = _set_claim(1, 2)
    claim["rationale"] = claim["rationale"].replace("_mm_set_epi64x assembles",
                                                    "_mm_set_epi32 assembles", 1)
    ok, why = module.check_set_build(claim, ctx)
    assert ok is False
    assert "claims _mm_set_epi32" in why
