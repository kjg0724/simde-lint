"""The precision census's own alias predicate, checked for over-crediting.

`docs/precision/verify_r.py` is not part of the package -- it is the
independent checker for the rule-R census, and it must stay independent, so
it is loaded by path rather than imported. What it must never do is credit a
call site to an intrinsic that is not actually reached from it: that inflates
a precision figure the paper reports, which is the one direction of error
that matters here.
"""

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "docs" / "precision" / "verify_r.py"


def _load():
    spec = importlib.util.spec_from_file_location("verify_r", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "source, expected, why",
    [
        (
            b"#define _mm_loadu_si64(p) _mm_loadl_epi64((__m128i const*)(p))",
            {"_mm_loadu_si64": "_mm_loadl_epi64"},
            "the shape the predicate exists for: one call, one forward",
        ),
        (
            b"#define _mm_cont(p) \\\n    _mm_loadl_epi64(p)",
            {"_mm_cont": "_mm_loadl_epi64"},
            "a body split across a line continuation is still one call",
        ),
        (
            b"// #define _mm_loadu_si64(p) _mm_loadl_epi64(p)",
            {},
            "a commented-out define is not a define",
        ),
        (
            b"#define _mm_foo(p) _mm_foo(p)",
            {},
            "a name forwarding to itself resolves nothing",
        ),
        (
            b"#if A\n#define _mm_x(p) _mm_a(p)\n#else\n#define _mm_x(p) _mm_b(p)\n#endif",
            {},
            "which branch is live depends on configuration this checker "
            "cannot see; taking the last silently credits the wrong intrinsic",
        ),
        (
            b"#define _mm_bar(p) (_mm_a(p) + _mm_b(p))",
            {},
            "two calls is a composition, not a forward",
        ),
        (
            b"#define _mm256_cvtsi256_si32(a) _mm_cvtsi128_si32(_mm256_castsi256_si128(a))",
            {},
            "SVT-AV1's real nested case -- crediting a call site to the "
            "outermost callee would invent a fact",
        ),
    ],
)
def test_only_a_true_single_call_forward_is_registered(source, expected, why):
    assert _load().local_aliases(source) == expected, why
