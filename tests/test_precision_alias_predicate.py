"""The precision census's own alias predicate, checked for over-crediting.

`docs/precision/verify_r.py` is not part of the package -- it is the
independent checker for the rule-R census, and it must stay independent, so
it is loaded by path rather than imported. What it must never do is credit a
call site to an intrinsic that is not actually reached from it: that inflates
a precision figure the paper reports, which is the one direction of error
that matters here.

Every rejection below was a real acceptance in an earlier draft. An external
review found the first three; the rest came from working out what else the
same weakness allowed.
"""

import importlib.util
from pathlib import Path

import pytest
import tree_sitter_cpp
from tree_sitter import Language, Parser

_SCRIPT = Path(__file__).resolve().parents[1] / "docs" / "precision" / "verify.py"
_PARSER = Parser(Language(tree_sitter_cpp.language()))


def _load():
    spec = importlib.util.spec_from_file_location("verify", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _defines(source):
    module = _load()
    return module.single_call_defines(_PARSER.parse(source).root_node, source, _PARSER)


@pytest.mark.parametrize(
    "source, expected, why",
    [
        (
            b"#define _mm_loadu_si64(p) _mm_loadl_epi64((__m128i const*)(p))",
            {"_mm_loadu_si64": "_mm_loadl_epi64"},
            "the shape the predicate exists for: one call, one forward",
        ),
        (
            b"#define _mm_loadu_si32(p) _mm_cvtsi32_si128(*(unsigned int const*)(p))",
            {"_mm_loadu_si32": "_mm_cvtsi32_si128"},
            "SVT-AV1's other real alias, in ssim_avx2.c",
        ),
        (
            b"#define _mm_paren(p) (_mm_loadl_epi64(p))",
            {"_mm_paren": "_mm_loadl_epi64"},
            "a body wrapped in its own parentheses is still one call",
        ),
        (
            b"/*\n#define _mm_outer(p) _mm_loadl_epi64(p)\n*/\n",
            {},
            "a define inside a block comment is not a define -- the parser "
            "already decided that, and a regex over raw text did not",
        ),
        (
            b"#define _mm_x(p) _mm_loadl_epi64(p) + side_effect(p)",
            {},
            "one intrinsic call plus a call to something else is not a forward",
        ),
        (
            b"#define _mm_y(p) _mm_loadl_epi64(p) + 1",
            {},
            "one call that is not the whole body is not a forward either",
        ),
        (
            b"#define _mm256_cvtsi256_si32(a) _mm_cvtsi128_si32(_mm256_castsi256_si128(a))",
            {},
            "SVT-AV1's real nested case -- crediting a call site to the "
            "outermost callee would invent a fact",
        ),
        (
            b"#if A\n#define _mm_q(p) _mm_a(p)\n#else\n#define _mm_q(p) _mm_b(p)\n#endif",
            {},
            "which branch is live depends on configuration this checker "
            "cannot see; taking the last silently credits the wrong intrinsic",
        ),
    ],
)
def test_only_a_true_single_call_forward_is_registered(source, expected, why):
    assert _defines(source) == expected, why


def test_an_aliased_finding_is_not_credited_without_its_definition():
    # A finding that says it reached the intrinsic through a spelling this
    # file cannot confirm forwards there must not be credited on the
    # strength of the call being present. Taking the tool's own resolution
    # on trust is checking the tool with the tool.
    module = _load()
    source = b"void f(void *p) {\n    _mm_alias(p);\n}\n"
    calls, by_line, _ = [], {2: []}, None
    tree = _PARSER.parse(source)
    ctx = (calls, {2: [module.Call("_mm_alias", 2, ["p"], None, 0, 0)]}, source, {})
    finding = {"line": 2, "intrinsic": "_mm_loadl_epi64", "raw_name": "_mm_alias"}
    ok, detail = module.check_name_only(finding, ctx)
    assert ok is False and "forwards it to" in detail

    ctx_defined = (calls, ctx[1], source, {"_mm_alias": "_mm_loadl_epi64"})
    ok, detail = module.check_name_only(finding, ctx_defined)
    assert ok is True and "forwarded" in detail
