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


def test_exclude_pattern_works_against_an_absolute_root(tmp_path):
    # `tests/*` is what a user naturally writes. fnmatch anchors to the whole
    # string, so without root-relative matching this excludes nothing when the
    # root is absolute — and does so silently.
    (tmp_path / "tests").mkdir()
    (tmp_path / "a.c").write_text("")
    (tmp_path / "tests" / "b.c").write_text("")
    names = {p.name for p in discover_files([tmp_path.resolve()], exclude=["tests/*"])}
    assert names == {"a.c"}


def test_warns_and_continues_on_a_path_that_does_not_exist(tmp_path, capsys):
    # A typo'd path would otherwise be indistinguishable from a clean sweep.
    (tmp_path / "a.c").write_text("")
    found = discover_files([tmp_path / "nope", tmp_path], exclude=[])
    assert {p.name for p in found} == {"a.c"}
    assert "no such path" in capsys.readouterr().err
