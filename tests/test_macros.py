from simde_lint.knowledge import load_knowledge
from simde_lint.macros import (
    build_alias_map,
    is_forwarding_alias,
    line_column,
    original_byte,
    reparse_macros,
)
from simde_lint.parser import iter_nodes, parse_source

MACRO = (
    b"#define LOAD4(BASE, OFF) \\\n"
    b"    _mm_unpacklo_epi64(_mm_loadl_epi64((const __m128i*)((BASE)+(OFF))), \\\n"
    b"                       _mm_loadl_epi64((const __m128i*)((BASE)+(OFF)+8)))\n"
)


def test_reparsed_body_exposes_calls_the_original_cst_hides():
    root = parse_source(MACRO).root_node
    hidden = next(iter_nodes(root, "preproc_arg"))
    assert len(list(iter_nodes(hidden, "call_expression"))) == 0

    macro = reparse_macros(root, MACRO)[0]
    assert macro.ok
    assert macro.name == "LOAD4"
    assert len(list(iter_nodes(macro.root, "call_expression"))) == 3


def test_positions_map_back_to_the_original_source():
    root = parse_source(MACRO).root_node
    macro = reparse_macros(root, MACRO)[0]
    seen = []
    for call in iter_nodes(macro.root, "call_expression"):
        fn = call.child_by_field_name("function")
        name = macro.source[fn.start_byte : fn.end_byte].decode()
        if not name.startswith("_mm"):
            continue
        byte = original_byte(macro, fn.start_byte)
        seen.append((name, MACRO[byte : byte + len(name)].decode(), line_column(MACRO, byte)))
    assert [(n, r) for n, r, _ in seen] == [
        ("_mm_unpacklo_epi64", "_mm_unpacklo_epi64"),
        ("_mm_loadl_epi64", "_mm_loadl_epi64"),
        ("_mm_loadl_epi64", "_mm_loadl_epi64"),
    ]
    assert [lc for _, _, lc in seen] == [(2, 5), (2, 24), (3, 24)]


def test_an_unparseable_body_is_marked_not_ok():
    # Token pasting does not survive reparsing as an expression.
    source = b"#define GLUE(a, b) a ## b ## _mm_add_epi32(\n"
    macros = reparse_macros(parse_source(source).root_node, source)
    assert macros == [] or all(not m.ok for m in macros)


# `preproc_arg` stops at the first backslash-newline boundary of this shape —
# a `do {` opened on the `#define` line, followed by a comment on its own
# continuation line — and hands back a 43-byte fragment with no closing brace.
# This reproduces the real defect: `FILTER_SRC` in SVT-AV1's
# variance_avx512.c truncates the same way, for the same reason (verified
# directly against that macro while diagnosing this bug).
DO_WHILE_MACRO = (
    b"#define FILTER_TWO(a, b) do {                                 \\\n"
    b"    /* filter the source */                                   \\\n"
    b"        a = _mm_add_epi32(a, b);                                \\\n"
    b"        b = _mm_sub_epi32(a, b);                                \\\n"
    b"                                                               \\\n"
    b"        /* add 8 to source */                                  \\\n"
    b"    } while (0)\n"
)


def test_backslash_continued_do_while_body_is_not_truncated():
    root = parse_source(DO_WHILE_MACRO).root_node
    # Documents the bug this guards against: tree-sitter's own `preproc_arg`
    # node stops right after the first backslash-newline, with no closing
    # brace. `macros.py` must recover the full body despite that, not depend
    # on this node alone.
    hidden = next(iter_nodes(root, "preproc_arg"))
    truncated = DO_WHILE_MACRO[hidden.start_byte : hidden.end_byte]
    assert truncated.rstrip().endswith(b"\\")
    assert b"}" not in truncated
    assert len(list(iter_nodes(hidden, "call_expression"))) == 0

    macro = reparse_macros(root, DO_WHILE_MACRO)[0]
    assert macro.ok
    calls = [
        macro.source[call.child_by_field_name("function").start_byte : call.child_by_field_name("function").end_byte]
        for call in iter_nodes(macro.root, "call_expression")
    ]
    assert calls == [b"_mm_add_epi32", b"_mm_sub_epi32"]


def test_position_on_third_physical_line_of_a_continued_body():
    root = parse_source(DO_WHILE_MACRO).root_node
    macro = reparse_macros(root, DO_WHILE_MACRO)[0]
    calls = list(iter_nodes(macro.root, "call_expression"))
    fn = calls[0].child_by_field_name("function")
    name = macro.source[fn.start_byte : fn.end_byte].decode()
    assert name == "_mm_add_epi32"

    byte = original_byte(macro, fn.start_byte)
    assert DO_WHILE_MACRO[byte : byte + len(name)].decode() == name
    assert line_column(DO_WHILE_MACRO, byte) == (3, 13)


FORWARDING = b"#define _my_cmpgt_epi64(a, b) simde_mm_cmpgt_epi64(a, b)\n"
WRAPPED = b"#define LOADP(p) ((__m128i)_mm_loadl_epi64((const __m128i*)(p)))\n"
MULTI = (
    b"#define PAIR(a, b) \\\n"
    b"    _mm_unpacklo_epi64(_mm_loadl_epi64(a), _mm_loadl_epi64(b))\n"
)
CHAIN = (
    b"#define INNER(a, b) _mm_cmpgt_epi64(a, b)\n"
    b"#define OUTER(a, b) INNER(a, b)\n"
)
CYCLE = (
    b"#define PING(a) PONG(a)\n"
    b"#define PONG(a) PING(a)\n"
)


def _macros(source):
    return reparse_macros(parse_source(source).root_node, source)


def test_single_call_body_is_a_forwarding_alias():
    assert is_forwarding_alias(_macros(FORWARDING)[0]) == "simde_mm_cmpgt_epi64"


def test_transparent_wrappers_are_stripped():
    assert is_forwarding_alias(_macros(WRAPPED)[0]) == "_mm_loadl_epi64"


def test_a_multi_call_body_is_not_an_alias():
    assert is_forwarding_alias(_macros(MULTI)[0]) is None


def test_alias_map_resolves_a_chain_to_its_end():
    assert build_alias_map(_macros(CHAIN), load_knowledge()) == {
        "INNER": "_mm_cmpgt_epi64",
        "OUTER": "_mm_cmpgt_epi64",
    }


def test_a_cycle_resolves_to_nothing():
    assert build_alias_map(_macros(CYCLE), load_knowledge()) == {}


def test_a_body_whose_callee_is_not_an_intrinsic_is_not_an_alias():
    source = b"#define WRAP(x) helper_fn(x)\n"
    assert build_alias_map(_macros(source), load_knowledge()) == {}


def test_a_trailing_semicolon_still_resolves_as_a_single_call_alias():
    # The synthetic wrapper appends its own `;`, so a body already ending in
    # `;` reparses with a doubled semicolon: the real call, followed by an
    # empty `expression_statement` that is an artifact of the wrapper, not
    # anything the macro's source contained. That artifact must not count as
    # a second statement.
    with_semicolon = b"#define M(a) f(a);\n"
    without_semicolon = b"#define M(a) f(a)\n"
    assert is_forwarding_alias(_macros(with_semicolon)[0]) == is_forwarding_alias(
        _macros(without_semicolon)[0]
    )
    assert is_forwarding_alias(_macros(with_semicolon)[0]) == "f"


def test_a_genuinely_two_statement_body_is_still_rejected():
    # Two real calls, each terminated with its own semicolon: this must stay
    # rejected even after empty artifact statements are dropped.
    source = b"#define M(a) f(a); g(a);\n"
    assert is_forwarding_alias(_macros(source)[0]) is None
