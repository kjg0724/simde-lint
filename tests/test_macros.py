import pytest

from simde_lint.extract import extract_units
from simde_lint.knowledge import load_knowledge
from simde_lint.macros import (
    AliasMap,
    _call_shape,
    _forwarding_call,
    _marker,
    _normalized_tokens,
    _tokenize,
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


def _alias_map(source, knowledge=None):
    root = parse_source(source).root_node
    macros = reparse_macros(root, source)
    return build_alias_map(root, source, macros, knowledge or load_knowledge())


def test_single_call_body_is_a_forwarding_alias():
    assert is_forwarding_alias(_macros(FORWARDING)[0]) == "simde_mm_cmpgt_epi64"


def test_transparent_wrappers_are_stripped():
    assert is_forwarding_alias(_macros(WRAPPED)[0]) == "_mm_loadl_epi64"


def test_a_multi_call_body_is_not_an_alias():
    assert is_forwarding_alias(_macros(MULTI)[0]) is None


def test_alias_map_resolves_a_chain_to_its_end():
    assert _alias_map(CHAIN).targets == {
        "INNER": "_mm_cmpgt_epi64",
        "OUTER": "_mm_cmpgt_epi64",
    }


def test_a_cycle_resolves_to_nothing():
    assert _alias_map(CYCLE).targets == {}


def test_a_body_whose_callee_is_not_an_intrinsic_is_not_an_alias():
    source = b"#define WRAP(x) helper_fn(x)\n"
    assert _alias_map(source).targets == {}


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
    """Success-path regression guard, not a mutation-sensitive check on its own.

    Both `#if` branches here are the *same* shape, so this fixture cannot
    distinguish real per-definition agreement-checking from a naive
    "whichever definition is processed last wins" implementation — both
    reach the same visible outcome (zero macro units, the call resolves).
    `test_agreeing_duplicate_alias_registers_both_definitions_not_only_the_last`,
    below, is this test's mutation-sensitive companion: it checks the one
    thing a last-wins implementation gets wrong even on an agreeing pair.
    """
    knowledge = load_knowledge()
    units = extract_units("dup.c", _DUP_ALIAS_SAME_TARGET_SAME_MAPPING, knowledge)
    assert [u.scope for u in units] == ["function"]
    (use,) = units
    assert [c.name for c in use.calls] == ["_mm_loadl_epi64"]
    assert use.calls[0].is_macro_alias


def test_agreeing_duplicate_alias_registers_both_definitions_not_only_the_last():
    """Mutation-sensitive companion to the test above.

    `AliasMap.definitions` — what `extract.py`'s unit skip is keyed on — must
    contain *every* one of `LD`'s two definitions once the name registers,
    not only whichever one a last-wins implementation happened to keep.
    """
    knowledge = load_knowledge()
    root = parse_source(_DUP_ALIAS_SAME_TARGET_SAME_MAPPING).root_node
    macros = reparse_macros(root, _DUP_ALIAS_SAME_TARGET_SAME_MAPPING)
    ld_macros = [m for m in macros if m.name == "LD"]
    assert len(ld_macros) == 2
    alias_map = build_alias_map(root, _DUP_ALIAS_SAME_TARGET_SAME_MAPPING, macros, knowledge)
    assert alias_map.definitions == frozenset(m.start_byte for m in ld_macros)


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
    """Success-path regression guard — see the note on the test above; this
    fixture is likewise unable to distinguish real agreement-checking from
    last-wins on its own, since both branches ultimately name the same
    intrinsic. `test_spelling_normalized_duplicate_alias_registers_both_definitions_not_only_the_last`,
    below, is its mutation-sensitive companion.
    """
    knowledge = load_knowledge()
    units = extract_units("dup.c", _DUP_ALIAS_SAME_TARGET_DIFFERENT_SPELLING, knowledge)
    assert [u.scope for u in units] == ["function"]
    (use,) = units
    assert [c.name for c in use.calls] == ["_mm_cmpgt_epi64"]


def test_spelling_normalized_duplicate_alias_registers_both_definitions_not_only_the_last():
    knowledge = load_knowledge()
    root = parse_source(_DUP_ALIAS_SAME_TARGET_DIFFERENT_SPELLING).root_node
    macros = reparse_macros(root, _DUP_ALIAS_SAME_TARGET_DIFFERENT_SPELLING)
    cmp_macros = [m for m in macros if m.name == "CMP"]
    assert len(cmp_macros) == 2
    alias_map = build_alias_map(root, _DUP_ALIAS_SAME_TARGET_DIFFERENT_SPELLING, macros, knowledge)
    assert alias_map.definitions == frozenset(m.start_byte for m in cmp_macros)


def test_a_single_definition_alias_is_still_registered_and_keyed_by_its_own_definition():
    # Regression pin for the ordinary, single-definition path once
    # registration moves from per-name to per-definition agreement.
    root = parse_source(FORWARDING).root_node
    macros = reparse_macros(root, FORWARDING)
    alias_map = build_alias_map(root, FORWARDING, macros, load_knowledge())
    assert alias_map.targets == {"_my_cmpgt_epi64": "_mm_cmpgt_epi64"}
    assert alias_map.definitions == frozenset({macros[0].start_byte})


def test_alias_map_targets_cannot_be_mutated_by_a_caller():
    """`AliasMap` claims its two fields cannot drift apart; this is the part
    of that claim that must be enforced, not merely documented — `targets`
    is a `MappingProxyType` view, not a plain dict a caller could edit out
    from under `definitions`. Checked every way a caller could try: item
    assignment, item deletion, and every mutating dict method — `clear`,
    `update`, `pop`, `popitem`, `setdefault` are not merely blocked, they do
    not exist on the proxy at all, which is a stronger guarantee than one
    that raises on the attempt.
    """
    alias_map = _alias_map(FORWARDING)
    with pytest.raises(TypeError):
        alias_map.targets["_my_cmpgt_epi64"] = "tampered"
    with pytest.raises(TypeError):
        del alias_map.targets["_my_cmpgt_epi64"]
    for method in ("clear", "update", "pop", "popitem", "setdefault", "__setitem__", "__delitem__"):
        assert not hasattr(alias_map.targets, method)


# --- Critical: an empty-bodied sibling definition must never be invisible --
#
# `#define LD(p)` with nothing after the parameter list has `value=None` in
# tree-sitter's own tree; `reparse_macros` skips it (there is no body byte
# range to reparse), so it never becomes a `ReparsedMacro`. If
# `build_alias_map` only ever looked at `reparse_macros`'s output, a name
# with an alias-shaped definition in one `#if` branch and an empty
# definition in another would never learn the empty one exists, and would
# register the name as if every definition had agreed -- vacuously, over a
# definition it never saw.

_DUP_ALIAS_AND_EMPTY_BODY = (
    b"#ifdef A\n"
    b"#define LD(p) _mm_loadl_epi64(p)\n"
    b"#else\n"
    b"#define LD(p)\n"
    b"#endif\n"
)


def test_an_empty_bodied_sibling_definition_is_never_registered():
    # Checked through the stable `extract_units` entry point first: under
    # the pre-this-fix implementation, `reparse_macros` (unchanged here)
    # still only ever sees the one alias-shaped `LD` definition -- the empty
    # one was never a `ReparsedMacro` to begin with -- so a per-name check
    # that only groups `reparse_macros`'s own output sees exactly one
    # definition, "agrees with itself" trivially, and registers `LD`. That
    # wrongly skips its unit, leaving zero macro units instead of one.
    knowledge = load_knowledge()
    units = extract_units("dup.c", _DUP_ALIAS_AND_EMPTY_BODY, knowledge)
    macro_units = [u for u in units if u.scope == "macro"]
    assert len(macro_units) == 1
    assert macro_units[0].name == "LD"
    assert [c.name for c in macro_units[0].calls] == ["_mm_loadl_epi64"]

    root = parse_source(_DUP_ALIAS_AND_EMPTY_BODY).root_node
    reparsed = reparse_macros(root, _DUP_ALIAS_AND_EMPTY_BODY)
    # The empty branch genuinely produces no `ReparsedMacro` -- confirms the
    # defect's actual mechanism, not just its outcome.
    assert len(reparsed) == 1
    alias_map = build_alias_map(root, _DUP_ALIAS_AND_EMPTY_BODY, reparsed, knowledge)
    assert "LD" not in alias_map.targets


# --- Chain composition: different intermediates, target + mapping compared -

_DUP_CHAIN_SAME_FINAL_SEMANTICS = (
    b"#define X(p) _mm_loadl_epi64(p)\n"
    b"#define Y(q) _mm_loadl_epi64(q)\n"
    b"#ifdef A\n"
    b"#define CHAINED(a) X(a)\n"
    b"#else\n"
    b"#define CHAINED(a) Y(a)\n"
    b"#endif\n"
    b"__m128i use(const __m128i *p) { return CHAINED(p); }\n"
)


def test_duplicate_definitions_chaining_through_different_but_equivalent_intermediates_register():
    """Owner's ruling: different intermediate callee names are fine when the
    final target and the composed call semantics agree. `X` and `Y` are
    different macros, but both forward their one parameter straight through
    to `_mm_loadl_epi64`, so `CHAINED`'s two branches compose to the same
    result and the name registers -- `X` and `Y` each register too, as
    ordinary single-definition aliases in their own right.
    """
    knowledge = load_knowledge()
    alias_map = _alias_map(_DUP_CHAIN_SAME_FINAL_SEMANTICS, knowledge)
    assert alias_map.targets["CHAINED"] == "_mm_loadl_epi64"
    assert alias_map.targets["X"] == "_mm_loadl_epi64"
    assert alias_map.targets["Y"] == "_mm_loadl_epi64"

    units = extract_units("dup.c", _DUP_CHAIN_SAME_FINAL_SEMANTICS, knowledge)
    assert [u.scope for u in units] == ["function"]
    (use,) = units
    assert [c.name for c in use.calls] == ["_mm_loadl_epi64"]


_DUP_CHAIN_DIFFERENT_COMPOSED_MAPPING = (
    b"#define X(p, q) _mm_add_epi32(p, q)\n"
    b"#define Y(p, q) _mm_add_epi32(q, p)\n"
    b"#ifdef A\n"
    b"#define CHAINED(a, b) X(a, b)\n"
    b"#else\n"
    b"#define CHAINED(a, b) Y(a, b)\n"
    b"#endif\n"
    b"__m128i use(__m128i x, __m128i y) { return CHAINED(x, y); }\n"
)


def test_duplicate_definitions_chaining_through_intermediates_with_a_reversed_operand_order_are_rejected():
    """Owner's ruling, the other half: `X` and `Y` both resolve to
    `_mm_add_epi32`, and `CHAINED`'s two *immediate* calls (`X(a, b)` /
    `Y(a, b)`) have identical immediate mappings -- comparing final targets
    alone would register `CHAINED`. Composing each branch's mapping through
    `X`'s (unswapped) and `Y`'s (swapped) own forwarding catches that the
    real operands end up reversed between the two branches, and rejects it.
    """
    knowledge = load_knowledge()
    alias_map = _alias_map(_DUP_CHAIN_DIFFERENT_COMPOSED_MAPPING, knowledge)
    assert "CHAINED" not in alias_map.targets
    # X and Y are each single-definition and internally faithful -- only
    # CHAINED, composing through them, disagrees.
    assert alias_map.targets["X"] == "_mm_add_epi32"
    assert alias_map.targets["Y"] == "_mm_add_epi32"

    units = extract_units("dup.c", _DUP_CHAIN_DIFFERENT_COMPOSED_MAPPING, knowledge)
    macro_units = [u for u in units if u.scope == "macro"]
    assert len(macro_units) == 2
    assert {u.name for u in macro_units} == {"CHAINED"}


_DUP_CHAIN_INTERMEDIATE_INSERTS_A_CONSTANT = (
    b"#define X(p, q) _mm_add_epi32(p + 1, q)\n"
    b"#ifdef A\n"
    b"#define CHAINED(a, b) X(a, b)\n"
    b"#else\n"
    b"#define CHAINED(a, b) _mm_add_epi32(a, b)\n"
    b"#endif\n"
)


def test_duplicate_definitions_where_one_chains_through_a_constant_inserting_intermediate_are_rejected():
    """Owner's ruling: composition must carry the *full token structure*, not
    just a positional permutation, or an intermediate that inserts a
    constant slips through. `X` adds `+ 1` to its first parameter before
    forwarding; composing that into `CHAINED`'s first branch yields
    `a + 1, b`, which does not match the second branch's plain `a, b`.
    """
    knowledge = load_knowledge()
    alias_map = _alias_map(_DUP_CHAIN_INTERMEDIATE_INSERTS_A_CONSTANT, knowledge)
    assert "CHAINED" not in alias_map.targets
    assert alias_map.targets["X"] == "_mm_add_epi32"


_DUP_CHAIN_UNRESOLVED_INTERMEDIATE = (
    b"#ifdef A\n"
    b"#define CHAINED(a) _mm_loadl_epi64(a)\n"
    b"#else\n"
    b"#define CHAINED(a) UNDEFINED_HELPER(a)\n"
    b"#endif\n"
)


def test_duplicate_definitions_where_one_chains_through_an_unresolved_name_are_rejected():
    """Owner's ruling: an unresolved name anywhere in the chain means the
    outer alias is not registered. `UNDEFINED_HELPER` is neither a
    recognized intrinsic nor a macro defined anywhere in this file, so the
    `#else` branch's chain dead-ends, and `CHAINED` as a whole does not
    register even though its other branch is a perfectly good alias.
    """
    knowledge = load_knowledge()
    alias_map = _alias_map(_DUP_CHAIN_UNRESOLVED_INTERMEDIATE, knowledge)
    assert "CHAINED" not in alias_map.targets


def test_a_cycle_within_duplicate_definitions_is_rejected():
    knowledge = load_knowledge()
    root = parse_source(CYCLE).root_node
    macros = reparse_macros(root, CYCLE)
    alias_map = build_alias_map(root, CYCLE, macros, knowledge)
    assert alias_map.targets == {}
    assert alias_map.definitions == frozenset()


# --- Whitespace, comments and formatting must not affect agreement ---------

_DUP_ALIAS_WHITESPACE_ONLY_DIFFERENCE = (
    b"#ifdef A\n"
    b"#define B(a) _mm_loadl_epi64(a)\n"
    b"#else\n"
    b"#define B(z)   _mm_loadl_epi64(  z  )  \n"
    b"#endif\n"
    b"__m128i use(const __m128i *p) { return B(p); }\n"
)


def test_duplicate_aliases_differing_only_in_whitespace_register():
    knowledge = load_knowledge()
    alias_map = _alias_map(_DUP_ALIAS_WHITESPACE_ONLY_DIFFERENCE, knowledge)
    assert alias_map.targets["B"] == "_mm_loadl_epi64"


def test_internal_whitespace_within_one_argument_is_insignificant():
    """The fixture above only exercises whitespace *around* one argument
    (between the parens and the call), which tree-sitter's own argument-node
    boundaries already trim before `_tokenize` ever sees the text -- it does
    not by itself prove this tokenizer drops whitespace. Whitespace *inside*
    one argument's own span (between an identifier and an operator) only
    ever reaches `_tokenize` directly, and this is what actually caught a
    real bug during development: three of this module's byte-membership
    sets (`_WHITESPACE` among them) were built by iterating a `bytes`
    literal directly (`frozenset(b" \\t\\n")`), which yields `int`s, not the
    length-1 `bytes` slices every check here compares against -- so
    whitespace was silently never recognized and fell through to becoming
    its own token instead of being dropped.
    """
    assert _tokenize(b"a+b") == _tokenize(b"a + b") == [("ident", b"a"), ("other", b"+"), ("ident", b"b")]


_DUP_ALIAS_COMMENT_ONLY_DIFFERENCE = (
    b"#ifdef A\n"
    b"#define C(a) _mm_loadl_epi64(a)\n"
    b"#else\n"
    b"#define C(a) \\\n"
    b"    /* load */ \\\n"
    b"    _mm_loadl_epi64(a)\n"
    b"#endif\n"
)


def test_duplicate_aliases_differing_only_by_a_comment_in_a_legal_position_register():
    """A comment placed *inside* the forwarded call's own argument list --
    `_mm_loadl_epi64(/* load */ a)` -- is not used here: tree-sitter's
    macro-body scanner fails to parse it at all (`has_error` on the
    original file, before this project's own reparsing ever runs; verified
    directly while writing this fixture, and unrelated to this fix). A
    comment on its own leading line, backslash-continued -- the same shape
    `DO_WHILE_MACRO` elsewhere in this file already relies on parsing
    cleanly -- is the "legal position" being exercised here instead;
    `test_a_comment_inside_one_argument_is_dropped_before_comparison`,
    below, is the white-box test of `_tokenize` itself for the in-argument
    case tree-sitter cannot get this fixture to reach.
    """
    knowledge = load_knowledge()
    alias_map = _alias_map(_DUP_ALIAS_COMMENT_ONLY_DIFFERENCE, knowledge)
    assert alias_map.targets["C"] == "_mm_loadl_epi64"


def test_a_comment_inside_one_argument_is_dropped_before_comparison():
    assert _normalized_tokens(b"a /* mid */ + 0", ()) == _normalized_tokens(b"a + 0", ())


_DUP_ALIAS_MULTILINE_CONTINUATION = (
    b"#ifdef A\n"
    b"#define M(a, b) _mm_add_epi32(a, b)\n"
    b"#else\n"
    b"#define M(a, b) _mm_add_epi32(a, \\\n"
    b"                              b)\n"
    b"#endif\n"
)


def test_duplicate_aliases_differing_only_by_a_backslash_continuation_register():
    """The reparsed body keeps the raw `\\` and newline bytes verbatim (see
    `_splice_lines`'s docstring) -- without splicing them away before
    lexing, this branch would carry a stray `\\` token the single-line
    branch does not have, and the two would compare unequal for a reason
    that has nothing to do with what either macro forwards.
    """
    knowledge = load_knowledge()
    alias_map = _alias_map(_DUP_ALIAS_MULTILINE_CONTINUATION, knowledge)
    assert alias_map.targets["M"] == "_mm_add_epi32"


# --- String/character literal contents are opaque, never substituted ------

_DUP_ALIAS_STRING_LITERAL_CONTENT_DIFFERS = (
    b'#ifdef A\n'
    b'#define D(a, b) _mm_set_epi32(a, b, sizeof("a"), 0)\n'
    b"#else\n"
    b'#define D(x, y) _mm_set_epi32(x, y, sizeof("x"), 0)\n'
    b"#endif\n"
)


def test_duplicate_aliases_whose_string_literal_contents_differ_are_rejected():
    """The dangerous-direction bug the review found: a naive text-substitution
    normalizer would rewrite the `a` inside `sizeof("a")` because it spells
    the first definition's own parameter name, and likewise `x` for the
    second -- making two definitions with genuinely different literal
    content compare as agreeing. `_tokenize` keeps a string literal as one
    opaque token and never inspects its contents, so `sizeof("a")` and
    `sizeof("x")` are different tokens, and this name must not register.
    """
    knowledge = load_knowledge()
    alias_map = _alias_map(_DUP_ALIAS_STRING_LITERAL_CONTENT_DIFFERS, knowledge)
    assert "D" not in alias_map.targets


_DUP_ALIAS_CHAR_LITERAL_CONTENT_DIFFERS = (
    b"#ifdef A\n"
    b"#define E(a) _mm_add_epi32(a, 'a')\n"
    b"#else\n"
    b"#define E(x) _mm_add_epi32(x, 'x')\n"
    b"#endif\n"
)


def test_duplicate_aliases_whose_character_literal_contents_differ_are_rejected():
    """`'a'`/`'x'` deliberately sit *directly* in the forwarded call's own
    argument list (not behind a nested call like `_mm_set1_epi32('a')`) --
    `is_forwarding_alias` rejects any body containing more than one
    `call_expression`, nested ones included, so a nested-call fixture would
    be rejected for that unrelated reason and never actually exercise
    whether a character literal's contents get substituted.
    """
    knowledge = load_knowledge()
    alias_map = _alias_map(_DUP_ALIAS_CHAR_LITERAL_CONTENT_DIFFERS, knowledge)
    assert "E" not in alias_map.targets


def test_identifiers_inside_string_and_char_literals_are_never_substituted():
    """Direct, white-box confirmation of the mechanism the two tests above
    rely on: the literal's own bytes pass through `_normalized_tokens`
    completely unchanged, and only the bare `a` outside it is substituted.
    """
    tokens = _normalized_tokens(b'sizeof("a") + (a)', ("a",))
    assert tokens is not None
    assert b'"a"' in tokens
    assert tokens.count(_marker(0)) == 1


def test_escaped_quotes_do_not_terminate_a_string_literal_early():
    r"""`"\""` is one token -- a string literal containing one escaped `"` --
    not a literal that ends at the escaped quote followed by a stray bare
    `"` token. Written as bytes: opening quote, `\`, `"`, closing quote.
    """
    text = b'"' + b'\\"' + b'"'
    tokens = _tokenize(text)
    assert tokens == [("other", text)]


def test_a_lone_backslash_before_a_letter_is_not_treated_as_a_line_splice():
    r"""`_splice_lines` must only delete a `\` immediately (mod trailing
    whitespace) followed by a newline -- not any `\`, or a string escape
    like `\n` inside a literal would be corrupted before it ever reaches the
    literal scanner.
    """
    from simde_lint.macros import _splice_lines

    text = b'"\\n"'
    assert _splice_lines(text) == text


# --- Identifier boundaries and the CST cast/type-identifier ambiguity ------


def test_parameter_substitution_respects_identifier_boundaries():
    tokens = _normalized_tokens(b"aa + a", ("a",))
    assert tokens == (b"aa", b"+", _marker(0))


def test_cast_ambiguous_parameters_are_substituted_by_lexical_spelling_not_node_type():
    """SVT-AV1's `LOAD8_S`/`LOAD4W_S` write `(BASE) + (0 * (S))`, which
    tree-sitter's C/C++ grammar resolves as a *cast* -- `BASE` read as a
    `type_descriptor`'s `type_identifier`, not a parenthesized variable
    reference (see `_identifiers`'s docstring). `_tokenize` is a plain
    byte-level lexer, so this ambiguity cannot affect it: `BASE` and `S`
    substitute correctly regardless of what tree-sitter would have called
    the node.
    """
    tokens = _normalized_tokens(b"(BASE) + (0 * (S))", ("BASE", "S"))
    assert tokens is not None
    assert _marker(0) in tokens
    assert _marker(1) in tokens
    assert b"BASE" not in tokens
    assert b"S" not in tokens


# --- Parameter omitted (and duplicated in its place) -----------------------

_DUP_ALIAS_PARAMETER_OMITTED_AND_DUPLICATED = (
    b"#ifdef A\n"
    b"#define G(a, b) _mm_add_epi32(a, b)\n"
    b"#else\n"
    b"#define G(a, b) _mm_add_epi32(a, a)\n"
    b"#endif\n"
)


def test_duplicate_aliases_where_one_definition_omits_and_duplicates_a_parameter_are_rejected():
    """The `#else` branch never uses `b` at all -- `is_forwarding_alias`
    already refuses to register a body that drops a parameter's use
    entirely (see its own docstring), so this whole name fails to register,
    the same as the plain "one alias, one multi-call body" shape.
    """
    knowledge = load_knowledge()
    alias_map = _alias_map(_DUP_ALIAS_PARAMETER_OMITTED_AND_DUPLICATED, knowledge)
    assert "G" not in alias_map.targets

    units = extract_units("dup.c", _DUP_ALIAS_PARAMETER_OMITTED_AND_DUPLICATED, knowledge)
    macro_units = [u for u in units if u.scope == "macro"]
    assert len(macro_units) == 2


# --- Round 3: arity at a chain step, raw string literals, AliasMap's own ---
# --- constructor invariant ---------------------------------------------

_SURPLUS_ARITY_CHAIN = (
    b"#define INNER(p) _mm_loadl_epi64(p)\n"
    b"#define OUTER(a, b) INNER(a, b)\n"
)


def test_a_chain_step_passing_more_arguments_than_the_intermediate_declares_is_rejected():
    """`INNER` takes one parameter; `OUTER`'s forwarding call passes two.

    Before this fix, `_substitute_shape` only checked for a *missing*
    operand (a marker index with no corresponding entry in `replacements`)
    -- it never compared the number of arguments a definition actually
    supplies against the callee's own declared parameter count, so the
    surplus second argument was silently discarded during composition and
    `OUTER` registered as though it faithfully forwarded to
    `_mm_loadl_epi64`. `INNER` is a perfectly good alias on its own and
    still registers; only `OUTER`, whose call to it is malformed, must not.
    """
    assert _alias_map(_SURPLUS_ARITY_CHAIN).targets == {"INNER": "_mm_loadl_epi64"}


_DEFICIT_ARITY_CHAIN = (
    b"#define INNER(p, q) _mm_add_epi32(p, q)\n"
    b"#define OUTER(a) INNER(a, a)\n"
    b"#define ALSO_OUTER(a) INNER(a)\n"
)


def test_a_chain_step_passing_fewer_arguments_than_the_intermediate_declares_is_rejected():
    """The mirror direction: `INNER` takes two parameters, `ALSO_OUTER`'s
    call supplies only one. `OUTER`, which supplies two (both `a`), is the
    control -- it must still register, so the fix is arity-checking, not
    merely rejecting any call to `INNER`.
    """
    knowledge = load_knowledge()
    alias_map = _alias_map(_DEFICIT_ARITY_CHAIN, knowledge)
    assert alias_map.targets["OUTER"] == "_mm_add_epi32"
    assert "ALSO_OUTER" not in alias_map.targets


_ARITY_MISMATCH_AT_AN_INNER_CHAIN_STEP = (
    b"#define C(p) _mm_loadl_epi64(p)\n"
    b"#define B(a, b) C(a, b)\n"
    b"#define A(x, y) B(x, y)\n"
)


def test_arity_mismatch_two_chain_steps_away_from_the_final_target_is_still_rejected():
    """The arity check must apply at *every* step of a chain, not only the
    call a name makes directly: `A` calls `B` with matching arity (two
    arguments, `B` declares two parameters) -- the mismatch is one level
    further in, at `B`'s own call to `C`. `B` must not register (so
    `A`'s chain through it cannot resolve either), while `C` is fine on
    its own.
    """
    knowledge = load_knowledge()
    alias_map = _alias_map(_ARITY_MISMATCH_AT_AN_INNER_CHAIN_STEP, knowledge)
    assert alias_map.targets == {"C": "_mm_loadl_epi64"}


# Raw string literals: a bare or prefixed `R"..."` must tokenize as one
# opaque literal token, never as an identifier `R` (or `u8R`/`uR`/`UR`/`LR`)
# immediately followed by a separate literal starting at the quote.

def test_raw_string_literals_are_tokenized_as_a_single_opaque_token():
    assert _tokenize(b'R"(x)"') == [("other", b'R"(x)"')]


def test_prefixed_raw_string_literals_are_tokenized_as_a_single_opaque_token():
    assert _tokenize(b'u8R"(x)"') == [("other", b'u8R"(x)"')]


def test_a_raw_string_with_a_named_delimiter_terminates_at_the_matching_delimiter_only():
    # The delimiter is "foo"; the raw string's own content contains a `)bar`
    # that is not the closing sequence and must not be mistaken for one.
    text = b'R"foo(a)bar)foo"'
    assert _tokenize(text) == [("other", text)]


def test_an_unterminated_raw_string_fails_closed():
    assert _tokenize(b'R"(unterminated') is None


_DUP_ALIAS_RAW_STRING_PREFIX_COLLIDES_WITH_PARAM_NAME = (
    b'#ifdef A\n'
    b'#define M(R) _mm_add_epi32(R, R"(x)")\n'
    b"#else\n"
    b'#define M(a) _mm_add_epi32(a, R"(x)")\n'
    b"#endif\n"
)


def test_duplicate_aliases_whose_raw_string_argument_shares_a_letter_with_a_parameter_name_register():
    """The exact reproduction from review: one branch's own parameter is
    named `R`, the same letter as the raw-string prefix in its second
    argument, `R"(x)"`. Before this fix, `_tokenize` split `R"(x)"` into an
    `ident` token `R` (which this branch's substitution then rewrote into a
    marker, because its parameter really is named `R`) followed by a
    separate literal token `"(x)"` -- corrupting the raw string's own
    spelling and making two branches that forward identically compare as
    disagreeing.
    """
    knowledge = load_knowledge()
    alias_map = _alias_map(_DUP_ALIAS_RAW_STRING_PREFIX_COLLIDES_WITH_PARAM_NAME, knowledge)
    assert alias_map.targets["M"] == "_mm_add_epi32"


# --- AliasMap's own constructor must be immutable, not only the factory ---


def test_alias_map_takes_a_defensive_copy_of_a_caller_supplied_mapping():
    """`test_alias_map_targets_cannot_be_mutated_by_a_caller` (above) only
    proves `build_alias_map`'s own `MappingProxyType` wrapping is immutable
    -- it says nothing about `AliasMap`'s own constructor, which any caller
    can invoke directly with a plain, mutable dict. `AliasMap.__post_init__`
    must take its own defensive copy so mutating the dict a caller passed in
    cannot change `targets` (or `definitions`) after construction.
    """
    mutable_targets = {"A": "_mm_loadl_epi64", "C": "_mm_loadu_si128"}
    mutable_definitions = {10, 20}
    alias_map = AliasMap(targets=mutable_targets, definitions=mutable_definitions)

    mutable_targets["A"] = "tampered"
    mutable_targets["B"] = "also tampered"
    del mutable_targets["C"]
    mutable_definitions.add(30)
    mutable_definitions.clear()

    assert alias_map.targets == {"A": "_mm_loadl_epi64", "C": "_mm_loadu_si128"}
    assert alias_map.definitions == frozenset({10, 20})
    with pytest.raises(TypeError):
        alias_map.targets["A"] = "tampered again"
    with pytest.raises(TypeError):
        del alias_map.targets["A"]
    for method in ("clear", "update", "pop", "popitem", "setdefault"):
        assert not hasattr(alias_map.targets, method)


def test_alias_map_constructor_copy_also_protects_against_a_mutable_definitions_set():
    """The `frozenset(...)` coercion in `__post_init__` is the same
    defensive-copy story as `targets`, for the other field: a caller
    passing a plain, mutable `set` for `definitions` must not be able to
    mutate `AliasMap.definitions` afterwards, or add to it after the fact.
    """
    mutable_definitions = {10, 20}
    alias_map = AliasMap(targets={}, definitions=mutable_definitions)
    assert isinstance(alias_map.definitions, frozenset)
    mutable_definitions.add(30)
    assert alias_map.definitions == frozenset({10, 20})
    with pytest.raises(AttributeError):
        alias_map.definitions.add(40)


# --- Round 4: empty-argument arity, variadic packs, more literal prefixes --

# `B()` is byte-identical whether `B` takes zero or one parameter -- C
# resolves the ambiguity from the *callee's own* declared arity, never from
# the call's own text alone. `A` itself is always zero-parameter in these
# fixtures; what varies is `B`'s arity, which is what the empty `B()` call
# must be read against.

_EMPTY_CALL_TO_ONE_PARAMETER_INTERMEDIATE = b"#define B(x) _mm_loadl_epi64(x)\n#define A() B()\n"


def test_an_empty_call_to_a_one_parameter_intermediate_is_one_empty_argument():
    """Before this fix, `_call_shape` always read `()`'s zero named children
    as zero arguments regardless of context, so `A`'s call `B()` mismatched
    `B`'s own one-parameter arity and `A` never registered.
    """
    knowledge = load_knowledge()
    alias_map = _alias_map(_EMPTY_CALL_TO_ONE_PARAMETER_INTERMEDIATE, knowledge)
    assert dict(alias_map.targets) == {"A": "_mm_loadl_epi64", "B": "_mm_loadl_epi64"}


_EMPTY_CALL_TO_ZERO_PARAMETER_INTERMEDIATE = b"#define B() _mm_setzero_si128()\n#define A() B()\n"


def test_an_empty_call_to_a_zero_parameter_intermediate_is_zero_arguments():
    knowledge = load_knowledge()
    alias_map = _alias_map(_EMPTY_CALL_TO_ZERO_PARAMETER_INTERMEDIATE, knowledge)
    assert dict(alias_map.targets) == {"A": "_mm_setzero_si128", "B": "_mm_setzero_si128"}


_EMPTY_CALL_TO_TWO_PARAMETER_INTERMEDIATE = b"#define B(x, y) _mm_add_epi32(x, y)\n#define A() B()\n"


def test_an_empty_call_to_a_two_parameter_intermediate_fails_closed():
    """Two or more fixed parameters against an empty call list has no single
    agreed-on meaning in real C either (a straightforward too-few-arguments
    error at preprocessing time) — this project does not try to guess at
    one, unlike the clean one-parameter and zero-parameter cases above.
    """
    knowledge = load_knowledge()
    alias_map = _alias_map(_EMPTY_CALL_TO_TWO_PARAMETER_INTERMEDIATE, knowledge)
    # `B` itself is a perfectly good, ordinary alias on its own -- only
    # `A`'s empty call to it is the malformed part.
    assert dict(alias_map.targets) == {"B": "_mm_add_epi32"}


_EMPTY_CALL_DIRECTLY_TO_AN_INTRINSIC = b"#define Z() _mm_setzero_si128()\n"


def test_an_empty_call_directly_to_an_intrinsic_is_always_zero_arguments():
    """Unlike a macro callee, a real function call's own syntax settles
    `f()` unambiguously as zero arguments — there is no declared parameter
    list on this side for this project to read `()` against, regardless of
    what `Z` itself declares.
    """
    knowledge = load_knowledge()
    alias_map = _alias_map(_EMPTY_CALL_DIRECTLY_TO_AN_INTRINSIC, knowledge)
    assert dict(alias_map.targets) == {"Z": "_mm_setzero_si128"}


# --- A genuinely empty *middle* argument is unrepresentable and fails closed

_MIDDLE_EMPTY_ARGUMENT = b"#define B(x, y, z) _mm_add_epi32(x, y)\n#define A(x, z) B(x,,z)\n"


def test_a_middle_empty_argument_is_unrepresentable_and_fails_closed():
    """`B(x,,z)` — a genuinely empty *middle* argument — does not parse at
    all in this project's grammar (confirmed directly: it produces an
    `ERROR` node inside the argument list, not two empty `argument_list`
    children), so `A`'s own body fails to reparse cleanly
    (`ReparsedMacro.ok` is False) and `A` is rejected well before arity
    ever enters into it. There is no attempt made to give this shape a
    successful registration through some other, more permissive route —
    the boundary is that it fails closed, and that is what is pinned here,
    not any particular internal mechanism.
    """
    knowledge = load_knowledge()
    root = parse_source(_MIDDLE_EMPTY_ARGUMENT).root_node
    reparsed = reparse_macros(root, _MIDDLE_EMPTY_ARGUMENT)
    a_macro = next(m for m in reparsed if m.name == "A")
    assert a_macro.ok is False
    alias_map = build_alias_map(root, _MIDDLE_EMPTY_ARGUMENT, reparsed, knowledge)
    assert "A" not in alias_map.targets
    assert dict(alias_map.targets) == {}


_NESTED_PARENS_ARGUMENT = b"#define B(a, b) _mm_add_epi32(a, b)\n#define A(p, q, r) B(p, (q, r))\n"


def test_a_comma_inside_nested_parentheses_is_not_an_argument_separator():
    """Pinning what was already correct before this round, so the new
    empty-argument/variadic handling above and below cannot silently break
    it: `B(p, (q, r))` is two arguments to `B` — `p`, and the whole
    parenthesized `(q, r)` — not three, because a comma nested inside
    parentheses is not itself an argument separator.
    """
    knowledge = load_knowledge()
    alias_map = _alias_map(_NESTED_PARENS_ARGUMENT, knowledge)
    assert alias_map.targets["A"] == "_mm_add_epi32"


# --- Variadic packs: standard `...` and GNU named (`args...`), zero/one/ ---
# --- several arguments, and composition through an intermediate -----------
#
# Each of the three shapes below is a `#if`-duplicate pair: one branch
# reaches the target *through* the variadic intermediate, the other writes
# the equivalent call *directly*. Registration itself is the shape-equality
# proof — two branches whose composed shapes differ are rejected — so
# "the pair registers" pins the actual claim ("this composition produces
# the same shape as the equivalent hand-written call"), not merely "some
# composition happened without erroring." A bare
# `alias_map.targets["A"] == target` check (what this section originally
# had) cannot tell a correct composed shape apart from a differently-wrong
# one when there is no sibling definition to disagree with it — exactly
# the gap that made the zero-argument case below inert until this round:
# it passed even under the pre-round-4 implementation, where `__VA_ARGS__`
# was an ordinary, unsubstituted literal token that never expanded to
# anything at all, because `A0` had no `#if` sibling to catch the wrong
# shape.

_VARIADIC_ZERO_EXTRA_ARGS_MATCHES_DIRECT = (
    b"#define V(...) _mm_setzero_si128(__VA_ARGS__)\n"
    b"#ifdef X\n"
    b"#define A() _mm_setzero_si128()\n"
    b"#else\n"
    b"#define A() V()\n"
    b"#endif\n"
)


def test_composing_through_a_variadic_intermediate_with_zero_extra_arguments_matches_the_direct_call():
    """Also the exact reproduction of the review's own repro: before this
    round's fix, an argument slot written as *only* the pack
    (`_mm_setzero_si128(__VA_ARGS__)`) composed to one argument with empty
    tokens when the pack was empty, rather than to zero arguments — so
    `V()`'s composed shape (one empty-token argument) disagreed with
    `_mm_setzero_si128()` written directly (zero arguments, per
    `_EMPTY_ARGS`'s own resolution), and this pair did not register.
    """
    knowledge = load_knowledge()
    alias_map = _alias_map(_VARIADIC_ZERO_EXTRA_ARGS_MATCHES_DIRECT, knowledge)
    assert alias_map.targets["A"] == "_mm_setzero_si128"
    assert alias_map.targets["V"] == "_mm_setzero_si128"


_VARIADIC_ONE_EXTRA_ARG_MATCHES_DIRECT = (
    b"#define B(x, ...) _mm_add_epi32(x, __VA_ARGS__)\n"
    b"#ifdef X\n"
    b"#define A1(x, y) _mm_add_epi32(x, y)\n"
    b"#else\n"
    b"#define A1(x, y) B(x, y)\n"
    b"#endif\n"
)


def test_composing_through_a_variadic_intermediate_with_one_extra_argument_matches_the_direct_call():
    knowledge = load_knowledge()
    alias_map = _alias_map(_VARIADIC_ONE_EXTRA_ARG_MATCHES_DIRECT, knowledge)
    assert alias_map.targets["A1"] == "_mm_add_epi32"
    assert alias_map.targets["B"] == "_mm_add_epi32"


_VARIADIC_SEVERAL_EXTRA_ARGS_MATCHES_DIRECT = (
    b"#define B(x, ...) _mm_add_epi32(x, __VA_ARGS__)\n"
    b"#ifdef X\n"
    b"#define A2(x, y, z) _mm_add_epi32(x, y, z)\n"
    b"#else\n"
    b"#define A2(x, y, z) B(x, y, z)\n"
    b"#endif\n"
)


def test_composing_through_a_variadic_intermediate_with_several_extra_arguments_matches_the_direct_call():
    """Pins that the excess arguments are comma-joined in the composed
    shape, not merely concatenated or otherwise malformed: `B(x, y, z)`
    must compose to the same three-argument shape as `_mm_add_epi32(x, y,
    z)` written directly, which only holds if the join between `y` and `z`
    inside the pack's expansion is exactly one comma token, matching what
    the direct call's own parser produced for the boundary between its own
    second and third arguments.
    """
    knowledge = load_knowledge()
    alias_map = _alias_map(_VARIADIC_SEVERAL_EXTRA_ARGS_MATCHES_DIRECT, knowledge)
    assert alias_map.targets["A2"] == "_mm_add_epi32"
    assert alias_map.targets["B"] == "_mm_add_epi32"


_VARIADIC_EMPTY_PACK_THROUGH_TWO_HOPS_MATCHES_DIRECT = (
    b"#define V(...) _mm_setzero_si128(__VA_ARGS__)\n"
    b"#define V2(...) V(__VA_ARGS__)\n"
    b"#ifdef X\n"
    b"#define A() _mm_setzero_si128()\n"
    b"#else\n"
    b"#define A() V2()\n"
    b"#endif\n"
)


def test_composing_through_two_variadic_hops_with_an_empty_pack_matches_the_direct_call():
    """The empty-pack slot collapse must hold at every hop, not only a
    single one: `A` reaches the target through *two* variadic
    intermediates (`V2` forwards its own empty pack to `V`, which forwards
    its own — now composed — empty pack to the target), and each hop's own
    composition must independently collapse the vanished slot for the next
    hop to see a clean, already-empty pack rather than a leftover
    empty-token argument.
    """
    knowledge = load_knowledge()
    alias_map = _alias_map(_VARIADIC_EMPTY_PACK_THROUGH_TWO_HOPS_MATCHES_DIRECT, knowledge)
    assert alias_map.targets["A"] == "_mm_setzero_si128"
    assert alias_map.targets["V"] == "_mm_setzero_si128"
    assert alias_map.targets["V2"] == "_mm_setzero_si128"


_VARIADIC_SEVERAL_ARGS_THROUGH_TWO_HOPS_MATCHES_DIRECT = (
    b"#define V(x, ...) _mm_add_epi32(x, __VA_ARGS__)\n"
    b"#define V2(x, ...) V(x, __VA_ARGS__)\n"
    b"#ifdef X\n"
    b"#define A(x, y, z) _mm_add_epi32(x, y, z)\n"
    b"#else\n"
    b"#define A(x, y, z) V2(x, y, z)\n"
    b"#endif\n"
)


def test_composing_through_two_variadic_hops_with_several_arguments_matches_the_direct_call():
    """The mirror case: several excess arguments must still land as
    separate argument slots (not one slot joined by an internal comma
    token) after passing through *two* variadic hops, each of which
    re-packs its own pack into the next.
    """
    knowledge = load_knowledge()
    alias_map = _alias_map(_VARIADIC_SEVERAL_ARGS_THROUGH_TWO_HOPS_MATCHES_DIRECT, knowledge)
    assert alias_map.targets["A"] == "_mm_add_epi32"
    assert alias_map.targets["V"] == "_mm_add_epi32"
    assert alias_map.targets["V2"] == "_mm_add_epi32"


_DUP_VARIADIC_STANDARD_AND_GNU_NAMED_AGREE = (
    b"#define TARGET1(x, ...) _mm_add_epi32(x, __VA_ARGS__)\n"
    b"#define TARGET2(x, rest...) _mm_add_epi32(x, rest)\n"
    b"#ifdef A\n"
    b"#define CHAINED(a, b) TARGET1(a, b)\n"
    b"#else\n"
    b"#define CHAINED(a, b) TARGET2(a, b)\n"
    b"#endif\n"
)


def test_duplicate_definitions_chaining_through_a_standard_and_a_gnu_named_variadic_that_agree_register():
    """`TARGET1` (standard `...`) and `TARGET2` (GNU named `rest...`) both
    forward their pack to `_mm_add_epi32`'s second position, faithfully —
    different variadic *forms*, same real correspondence. `CHAINED`'s two
    `#if` branches, one routing through each, must still be recognized as
    agreeing.
    """
    knowledge = load_knowledge()
    alias_map = _alias_map(_DUP_VARIADIC_STANDARD_AND_GNU_NAMED_AGREE, knowledge)
    assert alias_map.targets["CHAINED"] == "_mm_add_epi32"
    assert alias_map.targets["TARGET1"] == "_mm_add_epi32"
    assert alias_map.targets["TARGET2"] == "_mm_add_epi32"


_DUP_VARIADIC_PACK_POSITION_CONFLICTS = (
    b"#define TARGET1(x, ...) _mm_add_epi32(x, __VA_ARGS__)\n"
    b"#define TARGET3(x, ...) _mm_add_epi32(__VA_ARGS__, x)\n"
    b"#ifdef A\n"
    b"#define CHAINED2(a, b) TARGET1(a, b)\n"
    b"#else\n"
    b"#define CHAINED2(a, b) TARGET3(a, b)\n"
    b"#endif\n"
)


def test_duplicate_definitions_chaining_through_variadic_intermediates_whose_pack_position_conflicts_are_rejected():
    """`TARGET1` puts the pack second; `TARGET3` puts it first. Composed
    through `CHAINED2`'s two branches this is a genuine operand-order
    disagreement — the same "two sides read differently" case as a
    fixed-parameter reversal, just with a pack instead of a single
    parameter — and must be rejected, not registered.
    """
    knowledge = load_knowledge()
    alias_map = _alias_map(_DUP_VARIADIC_PACK_POSITION_CONFLICTS, knowledge)
    assert "CHAINED2" not in alias_map.targets
    assert alias_map.targets["TARGET1"] == "_mm_add_epi32"
    assert alias_map.targets["TARGET3"] == "_mm_add_epi32"


# --- Zero-parameter chains, several links deep -----------------------------

_ZERO_PARAMETER_CHAIN = (
    b"#define C() _mm_setzero_si128()\n"
    b"#define B() C()\n"
    b"#define A() B()\n"
)


def test_a_zero_parameter_chain_several_links_deep_registers_every_link():
    knowledge = load_knowledge()
    alias_map = _alias_map(_ZERO_PARAMETER_CHAIN, knowledge)
    assert dict(alias_map.targets) == {
        "A": "_mm_setzero_si128",
        "B": "_mm_setzero_si128",
        "C": "_mm_setzero_si128",
    }


# --- More literal prefixes: regular (non-raw) string and character forms --
# Raw strings (`R"..."`/`u8R"..."`) are covered above; these are the plain
# `u8`/`u`/`U`/`L` string and character prefixes `_STRING_PREFIXES` names,
# plus the two raw-string prefix combinations not yet exercised directly.

@pytest.mark.parametrize(
    "text",
    [
        b'u8"x"',
        b'u"x"',
        b'U"x"',
        b'L"x"',
        b"u8'x'",
        b"u'x'",
        b"U'x'",
        b"L'x'",
    ],
)
def test_prefixed_string_and_character_literals_are_tokenized_as_a_single_opaque_token(text):
    assert _tokenize(text) == [("other", text)]


@pytest.mark.parametrize("text", [b'uR"(x)"', b'UR"(x)"', b'LR"(x)"'])
def test_the_remaining_prefixed_raw_string_forms_are_tokenized_as_a_single_opaque_token(text):
    assert _tokenize(text) == [("other", text)]


def test_an_unprefixed_character_literal_is_tokenized_as_a_single_opaque_token():
    assert _tokenize(b"'x'") == [("other", b"'x'")]
