from simde_lint.discover import discover_files


def test_collects_c_and_cpp_sources_recursively(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.c").write_text("")
    (tmp_path / "sub" / "b.hpp").write_text("")
    (tmp_path / "notes.txt").write_text("")
    names = {p.name for p in discover_files([tmp_path], exclude=[])}
    assert names == {"a.c", "b.hpp"}


def test_applies_exclude_globs(tmp_path):
    (tmp_path / "build").mkdir()
    (tmp_path / "a.c").write_text("")
    (tmp_path / "build" / "gen.c").write_text("")
    names = {p.name for p in discover_files([tmp_path], exclude=["*/build/*"])}
    assert names == {"a.c"}


def test_accepts_a_single_file_path(tmp_path):
    target = tmp_path / "a.c"
    target.write_text("")
    assert discover_files([target], exclude=[]) == [target]
