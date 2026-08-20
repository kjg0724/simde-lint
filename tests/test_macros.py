from simde_lint.macros import line_column, original_byte, reparse_macros
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
