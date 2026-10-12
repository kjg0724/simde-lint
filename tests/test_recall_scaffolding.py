"""The recall enumerators' frozen tables and syntax helpers.

`docs/precision/recall/` is the implementation side of
`docs/precision/grammar.md`, and like the other precision checkers it is
loaded by path rather than imported: it must not become a package the tool
can reach, and it must not reach the tool.

Two things are checked here that nothing else can check. The frozen tables
have to agree with the markdown that declares them -- not with
`simde_lint`, which they are forbidden to read -- so a name added to one and
not the other is a failure. And the syntax helpers have to behave as the
grammar's definitions say, since every count the enumerators report is built
on them.
"""

import importlib.util
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_RECALL = _ROOT / "docs" / "precision" / "recall"
_GRAMMAR = _ROOT / "docs" / "precision" / "grammar.md"


def _load(name):
    # The modules import each other by bare name, the way the enumerator's
    # entry point runs them, so the directory goes on the path rather than
    # the package becoming importable as part of the tool.
    if str(_RECALL) not in sys.path:
        sys.path.insert(0, str(_RECALL))
    spec = importlib.util.spec_from_file_location(name, _RECALL / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def tables():
    return _load("tables")


@pytest.fixture(scope="module")
def syntax():
    return _load("syntax")


def _declared(bullet):
    """The intrinsic names the grammar's bullet for `bullet` lists."""
    text = _GRAMMAR.read_text()
    start = text.index(f"- **{bullet}**")
    end = text.index("\n- **", start + 1) if "\n- **" in text[start + 1:] else len(text)
    return set(re.findall(r"`(_mm\w+)`", text[start:end]))


@pytest.mark.parametrize(
    "bullet, attribute",
    [
        ("F multiplies", "F_MULTIPLIES"),
        ("F adds", "F_ADDS"),
        ("F widening conversions", "F_WIDENING"),
        ("M inserts", "M_INSERTS"),
        ("P compares", "P_COMPARES"),
    ],
)
def test_each_frozen_table_matches_the_grammar_that_declares_it(tables, bullet, attribute):
    # The markdown is the declaration and this module is the implementation.
    # A name in one and not the other is the failure this catches; neither is
    # allowed to be checked against the tool, which would make them agree by
    # construction on the population the figures are over.
    assert getattr(tables, attribute) == frozenset(_declared(bullet)), bullet


def test_the_w_table_matches_the_grammar(tables):
    declared = _declared("W")
    assert declared == {tables.W_PRODUCER, tables.W_PARTNER} | set(tables.W_CONSUMERS)


def test_recognized_is_the_prefix_test_the_grammar_describes(tables):
    # Rule P orders over every recognized call, and the rule's own notion of
    # one is every intrinsic call. A union of the registered families was the
    # first definition and made the enumeration diverge by construction:
    # `_mm_blendv_epi8` consumes a compare in VVenC and belongs to no family,
    # so calling it unrecognized excluded a relation the rule reports.
    for name in (
        "_mm_blendv_epi8", "_mm_add_epi32", "_mm256_shuffle_epi8",
        "_mm512_add_ps", "_mm_undocumented_thing",
    ):
        assert tables.recognized(name), name
    for name in ("memcpy", "vaddq_s32", "mm_add_epi32", "_mmx_add", ""):
        assert not tables.recognized(name), name


def test_every_frozen_family_is_recognized(tables):
    # The families are a subset of what P orders over, which is what makes
    # the prefix test a widening of the union rather than a different thing.
    families = (
        tables.F_MULTIPLIES | tables.F_ADDS | tables.F_WIDENING
        | {tables.W_PRODUCER, tables.W_PARTNER} | tables.W_CONSUMERS
        | tables.M_INSERTS | tables.P_COMPARES
        | tables.S_SHUFFLES | tables.R_PARTIAL_LOADS
    )
    assert all(tables.recognized(name) for name in families)
    # Rule R's and rule S's families are transcribed for completeness and
    # belong to no relation grammar: nothing anchors or consumes through them.
    assert not (tables.S_SHUFFLES | tables.R_PARTIAL_LOADS) & (
        tables.F_MULTIPLIES | tables.M_INSERTS | tables.P_COMPARES
    )


_IMPORTS_THE_TOOL = re.compile(
    r"^\s*(?:import\s+simde_lint|from\s+simde_lint)", re.MULTILINE
)


def test_nothing_in_the_recall_directory_imports_the_tool():
    # The independence clause, checked rather than promised. A figure produced
    # by code that reads the tool's tables agrees with the tool by
    # construction on the population it is a figure over.
    #
    # Matched against import statements, not the string: the first version
    # searched for `simde_lint` anywhere and failed on the docstring that
    # promises not to import it.
    for path in sorted(_RECALL.glob("*.py")):
        assert not _IMPORTS_THE_TOOL.search(path.read_text()), path.name


def test_the_threshold_is_a_constant_here(tables):
    # Reading the tool's configuration for it would make the enumerator agree
    # on the one number that decides whether a run is a finding.
    assert tables.M_THRESHOLD == 3


def test_normalized_removes_comments_and_collapses_whitespace(syntax):
    source = b"int  x   =  /* why */ 1 ;"
    assert syntax.normalized(syntax.parse(source).root_node, source) == "int x = 1 ;"


def test_normalized_keeps_every_token(syntax):
    # No case folding, no parenthesis removal, no reordering, nothing elided.
    # Tokens are joined by one space, so the result is not the source text.
    source = b"int X = (1) + f(A, b);"
    assert syntax.normalized(syntax.parse(source).root_node, source) == (
        "int X = ( 1 ) + f ( A , b ) ;"
    )


def test_normalized_makes_two_spellings_of_one_argument_list_equal(syntax):
    # What the definition is for. Rule W's pair test is over argument lists
    # "equal as written", and a definition that distinguished `(a, b)` from
    # `(a,b)` would fail it on formatting.
    first = b"__m128i p = _mm_mullo_epi16(a, b);"
    second = b"__m128i q = _mm_mulhi_epi16(a,b);"
    lists = []
    for source in (first, second):
        root = syntax.parse(source).root_node
        call = next(n for n in syntax.walk(root) if n.type == "call_expression")
        lists.append(syntax.normalized(call.child_by_field_name("arguments"), source))
    assert lists[0] == lists[1] == "( a , b )"


def test_normalized_refuses_a_node_from_another_buffer(syntax):
    source = b"void f(__m128i a, __m128i b) { __m128i r = _mm_add_epi32(a, b); (void)r; }"
    root = syntax.parse(source).root_node
    with pytest.raises(ValueError, match="different buffer"):
        syntax.normalized(root, b"short")


def test_the_position_key_orders_an_enclosing_call_before_a_nested_one(syntax):
    # The grammar's measured claim about P's ordering: in `outer(inner())`
    # the enclosing call starts first, so an enclosing call is never "next"
    # after a compare nested in its own arguments.
    source = b"void f(__m128i a, __m128i b, __m128i acc) {\n    acc = _mm_add_epi32(acc, _mm_madd_epi16(a, b));\n}\n"
    root = syntax.parse(source).root_node
    index = syntax.index_preorder(root)
    calls = [n for n in syntax.walk(root) if n.type == "call_expression"]
    ordered = sorted(calls, key=lambda c: syntax.Position(c.start_byte, c.end_byte, index[c.id]))
    names = [syntax.normalized(c.child_by_field_name("function"), source) for c in ordered]
    assert names == ["_mm_add_epi32", "_mm_madd_epi16"]


def test_the_position_key_is_total_for_equal_starts(syntax):
    # Equal start bytes are ranked, not abstained from: which of two
    # equally-positioned anchors owns an add does not change the instance
    # count, so the key has to answer rather than tie.
    a = syntax.Position(10, 20, 3)
    b = syntax.Position(10, 30, 4)
    c = syntax.Position(10, 20, 5)
    assert a < b and a < c and not (b < a)


@pytest.mark.parametrize(
    "text",
    [
        b"__m128i r = (_mm_add_epi32(a, b));",
        b"__m128i r = ((_mm_add_epi32(a, b)));",
        b"__m128i r = (__m128i)_mm_add_epi32(a, b);",
        b"__m128i r = static_cast<__m128i>(_mm_add_epi32(a, b));",
        b"__m128i r = reinterpret_cast<__m128i>(_mm_add_epi32(a, b));",
        b"__m128i r = const_cast<__m128i&>(_mm_add_epi32(a, b));",
        b"__m128i r = static_cast<__m128i>((_mm_add_epi32(a, b)));",
    ],
)
def test_strip_wrappers_reduces_parentheses_and_every_promised_cast(syntax, text):
    # The three C++ casts parse as a call expression whose function is a
    # `template_function`, so an earlier version looking for a node type named
    # after the cast could never reach them and returned the outer call.
    source = b"void f(__m128i a, __m128i b) { " + text + b" (void)r; }"
    root = syntax.parse(source).root_node
    declarator = next(n for n in syntax.walk(root) if n.type == "init_declarator")
    value = declarator.child_by_field_name("value")
    reduced = syntax.strip_wrappers(value)
    assert reduced.type == "call_expression"
    name = reduced.child_by_field_name("function")
    assert syntax.normalized(name, source) == "_mm_add_epi32"


def test_strip_wrappers_does_not_mistake_a_similarly_named_function(syntax):
    # The identifier is compared exactly, so a codebase helper whose name
    # begins like a cast is not unwrapped.
    source = (
        b"void f(__m128i a, __m128i b) { "
        b"__m128i r = static_cast_helper<__m128i>(_mm_add_epi32(a, b)); (void)r; }"
    )
    root = syntax.parse(source).root_node
    declarator = next(n for n in syntax.walk(root) if n.type == "init_declarator")
    value = declarator.child_by_field_name("value")
    assert syntax.strip_wrappers(value).id == value.id


def test_strip_wrappers_leaves_a_proper_subexpression_alone(syntax):
    # A call that survives as a sub-expression is not a binding: the grammar
    # admits it only as a nesting relation with respect to the enclosing call.
    source = b"void f(__m128i a, __m128i b) { __m128i r = _mm_add_epi32(a, b) ; (void)r; }"
    root = syntax.parse(source).root_node
    declarator = next(n for n in syntax.walk(root) if n.type == "init_declarator")
    value = declarator.child_by_field_name("value")
    assert syntax.strip_wrappers(value).id == value.id


def test_a_lambda_body_is_its_own_compound_statement(syntax):
    # Clause 6: a call inside a lambda is never a sibling of a call outside.
    source = (
        b"void f(__m128i a, __m128i b) {\n"
        b"    __m128i p = _mm_mullo_epi16(a, b);\n"
        b"    auto g = [&]{ __m128i q = _mm_add_epi16(p, p); (void)q; };\n"
        b"    g();\n"
        b"}\n"
    )
    root = syntax.parse(source).root_node
    calls = {
        syntax.normalized(c.child_by_field_name("function"), source): c
        for c in syntax.walk(root)
        if c.type == "call_expression"
    }
    outer = syntax.enclosing_body(calls["_mm_mullo_epi16"])
    inner = syntax.enclosing_body(calls["_mm_add_epi16"])
    assert outer is not None and inner is not None
    assert outer.id != inner.id


def test_a_call_outside_any_function_has_no_enclosing_function(syntax):
    # Such a call is not an anchor at all -- outside the population rather
    # than counted as an exclusion.
    source = b"__m128i g = _mm_add_epi32(a, b);\n"
    root = syntax.parse(source).root_node
    call = next(n for n in syntax.walk(root) if n.type == "call_expression")
    assert syntax.enclosing_function(call) is None


def test_has_parse_error_sees_an_error_node(syntax):
    broken = b"void f( { __m128i r = _mm_add_epi32(a, b); }\n"
    assert syntax.has_parse_error(syntax.parse(broken).root_node)
    clean = b"void f(__m128i a, __m128i b) { __m128i r = _mm_add_epi32(a, b); (void)r; }\n"
    assert not syntax.has_parse_error(syntax.parse(clean).root_node)


@pytest.fixture(scope="module")
def relations():
    _load("tables")
    return _load("relations")


_REBUILD = b"""
void f(__m128i x8top, __m128i wt8) {
    __m128i tmplo8 = _mm_mullo_epi16(x8top, wt8);
    __m128i tmphi8 = _mm_mulhi_epi16(x8top, wt8);
    __m128i toplo8 = _mm_unpacklo_epi16(tmplo8, tmphi8);
    __m128i tophi8 = _mm_unpackhi_epi16(tmplo8, tmphi8);
    (void)toplo8; (void)tophi8;
}
"""

_UNKNOWN_CALL_BETWEEN = b"""
void f(__m128i x8top, __m128i wt8) {
    __m128i tmplo8 = _mm_mullo_epi16(x8top, wt8);
    __m128i tmphi8 = _mm_mulhi_epi16(x8top, wt8);
    scramble(tmplo8);
    __m128i tophi8 = _mm_unpackhi_epi16(tmplo8, tmphi8);
    (void)tophi8;
}
"""


def _edge_between(syntax, relations, source, producer_name, consumer_name):
    root = syntax.parse(source).root_node
    calls = {}
    for node in syntax.walk(root):
        if node.type != "call_expression":
            continue
        function = node.child_by_field_name("function")
        if function is None or function.type != "identifier":
            continue
        calls.setdefault(syntax.normalized(function, source), node)
    return relations.edge(calls[producer_name], calls[consumer_name], source)


def test_an_intervening_intrinsic_call_does_not_block_the_relation(syntax, relations):
    # The canonical eight-lane rebuild: `unpacklo` sits between the `mullo`
    # and the `unpackhi` and passes the binding to a call. The rule's unit is
    # one consuming unpack, so this shape is two findings, and without the
    # by-value allowlist the second was excluded every time -- nine of W's
    # thirty prospective relations on the holdout, all the high half.
    edge = _edge_between(
        syntax, relations, _REBUILD, "_mm_mullo_epi16", "_mm_unpackhi_epi16"
    )
    assert edge.admitted, sorted(edge.reasons)
    assert edge.kind == "binding"


def test_an_intervening_unknown_call_still_blocks_the_relation(syntax, relations):
    # Anything not on the allowlist still excludes: whether it mutates its
    # argument needs overload resolution, which the grammar does not do.
    edge = _edge_between(
        syntax, relations, _UNKNOWN_CALL_BETWEEN, "_mm_mullo_epi16", "_mm_unpackhi_epi16"
    )
    assert not edge.admitted
    assert "passed_to_a_call_between" in edge.reasons


def test_the_by_value_list_is_separate_from_the_family_tables(tables):
    # It holds the same names today and answers a different question: the
    # families say what anchors and consumes, this says what cannot mutate an
    # argument. Relying on one for the other would give a table maintained
    # for one purpose a second meaning nobody checks when it changes.
    assert tables.BY_VALUE is not tables.F_MULTIPLIES
    assert tables.F_MULTIPLIES <= tables.BY_VALUE
    assert tables.W_CONSUMERS <= tables.BY_VALUE
    assert "scramble" not in tables.BY_VALUE
