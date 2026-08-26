from simde_lint.extract import extract_units
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
    assert build_alias_map(_macros(CHAIN), load_knowledge()).targets == {
        "INNER": "_mm_cmpgt_epi64",
        "OUTER": "_mm_cmpgt_epi64",
    }


def test_a_cycle_resolves_to_nothing():
    assert build_alias_map(_macros(CYCLE), load_knowledge()).targets == {}


def test_a_body_whose_callee_is_not_an_intrinsic_is_not_an_alias():
    source = b"#define WRAP(x) helper_fn(x)\n"
    assert build_alias_map(_macros(source), load_knowledge()).targets == {}


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


# C2: a stray trailing backslash whose continuation target is blank (or
# whitespace-only) must not pull the following source into the macro body.
# `rstrip()` over the whole accumulated range strips whitespace *across*
# newlines, so it cannot tell "the line right after the backslash has no
# content" from "there is more real continuation ahead" -- both fixtures
# below are structural reproductions of the review's repro (a `TRAILING`
# macro whose last content line ends in `\`, followed by a blank line and a
# function containing `_mm_shuffle_epi8`/`_mm_loadl_epi64`).
_TRAILING_BODY = b"#define TRAILING(a) x = _mm_loadl_epi64(a); \\\n"
# Single physical line, matching the review's exact reproduction: the old
# `rstrip()`-over-the-whole-range bug greedily absorbs whatever follows the
# blank continuation target one line at a time, and a one-line function here
# is exactly what turns that into a *duplicate finding* (both units parse
# ok) rather than a body that merely fails to reparse.
_AFTER_TRAILING = (
    b"__m128i after_trailing(const __m128i *p) { "
    b"return _mm_shuffle_epi8(_mm_loadl_epi64(p), "
    b"_mm_setr_epi8(0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15)); }\n"
)

TRAILING_BLANK_LINE = _TRAILING_BODY + b"\n" + _AFTER_TRAILING
TRAILING_WHITESPACE_LINE = _TRAILING_BODY + b"   \t  \n" + _AFTER_TRAILING
NO_CONTINUATION = (
    b"#define PLAIN(a) _mm_loadl_epi64(a)\n"
    b"__m128i after_plain(const __m128i *p) { return _mm_loadl_epi64(p); }\n"
)
CONTINUATION_TO_EOF = b"#define TRAILING_EOF(a) x = _mm_loadl_epi64(a); \\"


def test_a_blank_continuation_target_does_not_pull_in_the_next_line():
    macro = _macros(TRAILING_BLANK_LINE)[0]
    assert macro.ok
    assert macro.name == "TRAILING"
    calls = [
        macro.source[c.child_by_field_name("function").start_byte : c.child_by_field_name("function").end_byte]
        for c in iter_nodes(macro.root, "call_expression")
    ]
    # Only the one call the macro body itself writes -- nothing from the
    # blank line, and nothing from the function that follows it.
    assert calls == [b"_mm_loadl_epi64"]


def test_a_whitespace_only_continuation_target_does_not_pull_in_the_next_line():
    macro = _macros(TRAILING_WHITESPACE_LINE)[0]
    assert macro.ok
    assert macro.name == "TRAILING"
    calls = [
        macro.source[c.child_by_field_name("function").start_byte : c.child_by_field_name("function").end_byte]
        for c in iter_nodes(macro.root, "call_expression")
    ]
    assert calls == [b"_mm_loadl_epi64"]


def test_a_genuine_multi_line_continuation_still_reparses_in_full():
    # Regression guard for the fix's own risk: tightening the continuation
    # check to "only the last physical line" must not stop following a real
    # continuation across several lines. `MACRO` is exactly that shape --
    # every physical line but the last ends in `\`, none of them blank.
    macro = reparse_macros(parse_source(MACRO).root_node, MACRO)[0]
    assert macro.ok
    assert len(list(iter_nodes(macro.root, "call_expression"))) == 3


def test_no_continuation_leaves_the_body_at_a_single_line():
    macro = _macros(NO_CONTINUATION)[0]
    assert macro.ok
    assert macro.name == "PLAIN"
    calls = [
        macro.source[c.child_by_field_name("function").start_byte : c.child_by_field_name("function").end_byte]
        for c in iter_nodes(macro.root, "call_expression")
    ]
    assert calls == [b"_mm_loadl_epi64"]


def test_a_continuation_that_runs_to_end_of_file_does_not_crash():
    # Closes the deferred `newline < 0` branch in `_body_range`: the last
    # line ends in `\` and the file simply ends there, with no newline at
    # all after it -- `source.find(b"\n", end)` returns -1.
    macro = _macros(CONTINUATION_TO_EOF)[0]
    assert macro.ok
    assert macro.name == "TRAILING_EOF"
    calls = [
        macro.source[c.child_by_field_name("function").start_byte : c.child_by_field_name("function").end_byte]
        for c in iter_nodes(macro.root, "call_expression")
    ]
    assert calls == [b"_mm_loadl_epi64"]


def test_the_same_call_is_never_attributed_to_both_a_macro_and_a_function():
    # End-to-end reproduction of the review's exact defect report: before the
    # fix, `_mm_shuffle_epi8`/`_mm_loadl_epi64` in `after_trailing` were
    # counted once under the function and a second time under `TRAILING`, a
    # macro whose own body never contains either call.
    knowledge = load_knowledge()
    units = extract_units("probe.c", TRAILING_BLANK_LINE, knowledge)

    macro_unit = next(u for u in units if u.scope == "macro" and u.name == "TRAILING")
    function_unit = next(u for u in units if u.scope == "function" and u.name == "after_trailing")

    assert [c.name for c in macro_unit.calls] == ["_mm_loadl_epi64"]
    assert {c.name for c in function_unit.calls} == {"_mm_shuffle_epi8", "_mm_loadl_epi64", "_mm_setr_epi8"}

    # No call site (identified by its own start_byte, the position tests
    # elsewhere in this file already trust) is shared between the two units.
    macro_bytes = {c.start_byte for c in macro_unit.calls}
    function_bytes = {c.start_byte for c in function_unit.calls}
    assert macro_bytes.isdisjoint(function_bytes)

    # And the macro unit's one call is the `a` argument inside the #define,
    # strictly before the function even starts in the source.
    assert max(macro_bytes) < min(function_bytes)


# --- v1.3: alias registration keyed per definition, not per macro name -----
#
# A macro name can have several definitions under different `#if` branches,
# and `reparse_macros` reads all of them regardless of which branch a real
# build would actually take (see the `UNPACKX` fixture below, and the
# existing "known limitation" note in README.md/docs/verification.md).
# Before this fix, `build_alias_map` folded every definition of one name
# into a single `candidates[name]` entry -- last definition in the file
# silently wins -- and `extract.py`'s unit skip dropped a *name*, not a
# specific definition, so a single alias-shaped `#if` branch made every
# other same-named branch's calls invisible, whether or not that branch was
# itself an alias. These fixtures each define one name twice in one file to
# reproduce that.

_DUP_ALIAS_SAME_TARGET_SAME_MAPPING = (
    b"#ifdef A\n"
    b"#define LD(p) _mm_loadl_epi64(p)\n"
    b"#else\n"
    b"#define LD(p) _mm_loadl_epi64(p)\n"
    b"#endif\n"
    b"__m128i use(const __m128i *p) { return LD(p); }\n"
)

_DUP_ALIAS_DIFFERENT_TARGETS = (
    b"#ifdef A\n"
    b"#define LD(p) _mm_loadl_epi64(p)\n"
    b"#else\n"
    b"#define LD(p) _mm_loadu_si128(p)\n"
    b"#endif\n"
    b"__m128i use(const __m128i *p) { return LD(p); }\n"
)

# Defect A's own reproduction: one branch is a forwarding alias, the other a
# genuinely different, two-call body.
_DUP_ALIAS_AND_MULTI_CALL_BODY = (
    b"#ifdef A\n"
    b"#define LD(p) _mm_loadl_epi64(p)\n"
    b"#else\n"
    b"#define LD(p) _mm_loadl_epi64(p); _mm_loadu_si128(p);\n"
    b"#endif\n"
)

_DUP_ALIAS_DIFFERENT_PARAM_COUNT = (
    b"#ifdef A\n"
    b"#define ADD(a) _mm_add_epi32(a, a)\n"
    b"#else\n"
    b"#define ADD(a, b) _mm_add_epi32(a, b)\n"
    b"#endif\n"
)

_DUP_ALIAS_REVERSED_MAPPING = (
    b"#ifdef A\n"
    b"#define ADD(a, b) _mm_add_epi32(a, b)\n"
    b"#else\n"
    b"#define ADD(a, b) _mm_add_epi32(b, a)\n"
    b"#endif\n"
)

# The real shape from VVenC's `Lib/CommonLib/x86/RdCostX86.h`: `UNPACKX`
# defined twice, in separate `#ifdef USE_AVX2` blocks, neither body a single
# forwarding call. Never registered as an alias before this fix either --
# pinned here so per-definition keying cannot change this one's outcome.
_DUP_NON_ALIAS = (
    b"#ifdef USE_AVX2\n"
    b"#define UNPACKX(a, b, c) do { c = _mm_unpacklo_epi8(a, b); } while (0)\n"
    b"#else\n"
    b"#define UNPACKX(a, b, c) do { c = _mm_unpackhi_epi8(a, b); } while (0)\n"
    b"#endif\n"
)


def test_agreeing_duplicate_aliases_are_registered_and_produce_no_units():
    knowledge = load_knowledge()
    units = extract_units("dup.c", _DUP_ALIAS_SAME_TARGET_SAME_MAPPING, knowledge)
    assert [u.scope for u in units] == ["function"]
    (use,) = units
    assert [c.name for c in use.calls] == ["_mm_loadl_epi64"]
    assert use.calls[0].is_macro_alias


def test_disagreeing_duplicate_alias_targets_are_not_registered():
    knowledge = load_knowledge()
    units = extract_units("dup.c", _DUP_ALIAS_DIFFERENT_TARGETS, knowledge)
    macro_units = [u for u in units if u.scope == "macro"]
    assert len(macro_units) == 2
    (function_unit,) = [u for u in units if u.scope == "function"]
    # Neither `LD` definition was registered, so the call site's raw name
    # never normalizes to a recognized intrinsic and the function unit sees
    # no call at all.
    assert function_unit.calls == []


def test_one_alias_shaped_and_one_multi_call_definition_are_not_registered():
    knowledge = load_knowledge()
    root = parse_source(_DUP_ALIAS_AND_MULTI_CALL_BODY).root_node
    macros = reparse_macros(root, _DUP_ALIAS_AND_MULTI_CALL_BODY)
    assert len(macros) == 2

    units = extract_units("dup.c", _DUP_ALIAS_AND_MULTI_CALL_BODY, knowledge)
    macro_units = [u for u in units if u.scope == "macro"]
    # Defect A: both definitions must survive as units, including the
    # multi-call `#else` branch that is not itself an alias.
    assert len(macro_units) == 2


def test_duplicate_aliases_with_different_parameter_counts_are_not_registered():
    knowledge = load_knowledge()
    units = extract_units("dup.c", _DUP_ALIAS_DIFFERENT_PARAM_COUNT, knowledge)
    macro_units = [u for u in units if u.scope == "macro"]
    assert len(macro_units) == 2


def test_duplicate_aliases_with_a_reversed_parameter_mapping_are_not_registered():
    knowledge = load_knowledge()
    units = extract_units("dup.c", _DUP_ALIAS_REVERSED_MAPPING, knowledge)
    macro_units = [u for u in units if u.scope == "macro"]
    assert len(macro_units) == 2


def test_non_alias_duplicate_definitions_are_unaffected():
    knowledge = load_knowledge()
    units = extract_units("dup.c", _DUP_NON_ALIAS, knowledge)
    macro_units = [u for u in units if u.scope == "macro"]
    assert len(macro_units) == 2
    assert {u.name for u in macro_units} == {"UNPACKX"}


# A real corpus case, found while verifying this fix against VVenC:
# `DepQuantX86.h` defines `_my_cmpgt_epi64` twice, guarded by
# `#if USE_SSE41 && defined(REAL_TARGET_X86)` -- one branch's callee is
# spelled `simde_mm_cmpgt_epi64`, the other `_mm_cmpgt_epi64`. Different
# written names, but `knowledge.normalize` maps the first to the second, so
# they are the *same* target intrinsic under SIMDe's own naming convention,
# not a genuine disagreement -- see `knowledge/aliases.yaml`. Comparing raw
# callee text here (rather than each callee's own `knowledge.normalize`
# result) would reject this and regress a real, previously-confirmed alias.
_DUP_ALIAS_SAME_TARGET_DIFFERENT_SPELLING = (
    b"#ifdef A\n"
    b"#define CMP(a, b) simde_mm_cmpgt_epi64(a, b)\n"
    b"#else\n"
    b"#define CMP(a, b) _mm_cmpgt_epi64(a, b)\n"
    b"#endif\n"
    b"__m128i use(__m128i a, __m128i b) { return CMP(a, b); }\n"
)


def test_duplicate_aliases_agreeing_only_after_simde_spelling_normalization_are_registered():
    knowledge = load_knowledge()
    units = extract_units("dup.c", _DUP_ALIAS_SAME_TARGET_DIFFERENT_SPELLING, knowledge)
    assert [u.scope for u in units] == ["function"]
    (use,) = units
    assert [c.name for c in use.calls] == ["_mm_cmpgt_epi64"]


def test_a_single_definition_alias_is_still_registered_and_keyed_by_its_own_definition():
    # Regression pin for the ordinary, single-definition path once
    # registration moves from per-name to per-definition agreement.
    macros = reparse_macros(parse_source(FORWARDING).root_node, FORWARDING)
    alias_map = build_alias_map(macros, load_knowledge())
    assert alias_map.targets == {"_my_cmpgt_epi64": "_mm_cmpgt_epi64"}
    assert alias_map.definitions == frozenset({macros[0].body_start_byte})
