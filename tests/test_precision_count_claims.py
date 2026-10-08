"""The census's two quantitative checks, aimed at a false number.

`docs/precision/verify.py` is the independent checker for the precision
census, so it is loaded by path rather than imported. Two of its checks read
a number out of the finding's rationale: how many inserts a chain holds, and
how many of a `set` call's arguments are runtime values. Both parsed the
number and returned agreement regardless, which left the only check that
reads those numbers unable to reject a wrong one -- a census at 100% said
nothing about them. An external review found the set-build half, then the
insert-chain half after the first was fixed.

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
