from simde_lint.parser import parse_source, iter_nodes, node_text

SRC = b"""
void f(void) {
    __m128i a = _mm_shuffle_epi8(x, _mm_setr_epi8(0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,-1));
}
"""


def test_parses_without_error():
    tree = parse_source(SRC)
    assert tree.root_node.type == "translation_unit"
    assert not tree.root_node.has_error


def test_finds_call_expressions():
    tree = parse_source(SRC)
    calls = list(iter_nodes(tree.root_node, "call_expression"))
    names = {node_text(c.child_by_field_name("function"), SRC) for c in calls}
    assert "_mm_shuffle_epi8" in names
    assert "_mm_setr_epi8" in names


def test_parses_unparseable_input_without_raising():
    tree = parse_source(b"this is ((( not c++")
    assert tree.root_node is not None
