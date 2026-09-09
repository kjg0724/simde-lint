import json
import os
import re
from importlib.metadata import version as metadata_version
from pathlib import Path

import pytest

from simde_lint.cli import main
from simde_lint.finding import BENCHMARK_BACKED_TYPES

SOURCE = """
void kernel(const int *src, __m128i data) {
    __m128i a = _mm_loadu_si32(src);
    __m128i b = _mm_shuffle_epi8(data, _mm_loadu_si128((const __m128i *)src));
    /* Grades A, and is here so the --min-evidence filter has something to
       keep. R and S both grade C on this fixture, so without an A finding
       that test can only assert over an empty list. */
    __m128i p = _mm_mullo_epi32(data, data);
    __m128i s = _mm_add_epi32(p, data);
    (void)a; (void)b; (void)s;
}
"""


def _write(tmp_path):
    target = tmp_path / "k.c"
    target.write_text(SOURCE)
    return str(target)


def test_reports_findings_as_json(tmp_path, capsys):
    code = main([_write(tmp_path), "--format", "json"])
    data = json.loads(capsys.readouterr().out)
    assert code == 0
    assert data["summary"]["total"] >= 2


def test_min_evidence_a_drops_lower_grades(tmp_path, capsys):
    main([_write(tmp_path), "--format", "json", "--min-evidence", "A"])
    data = json.loads(capsys.readouterr().out)
    # An empty findings list would satisfy all(...) trivially and hide a
    # filter that dropped everything, so require it to have kept something.
    # Pins all three facts the filter depends on: something survived, exactly
    # what survived, and that it is the F finding rather than "whatever was
    # left happened to be A". R and S grade C on this fixture and are the
    # findings being dropped.
    assert [(f["type"], f["evidence"]) for f in data["findings"]] == [("F", "A")]


def test_type_filter_restricts_output(tmp_path, capsys):
    main([_write(tmp_path), "--format", "json", "--type", "R"])
    data = json.loads(capsys.readouterr().out)
    assert {f["type"] for f in data["findings"]} == {"R"}


def test_an_unknown_type_letter_is_rejected(tmp_path, capsys):
    # "Z" isn't one of the six taxonomy types; silently matching nothing
    # would look identical to a typo-free filter that happens to find
    # nothing, so this must fail loudly instead.
    with pytest.raises(SystemExit) as excinfo:
        main([_write(tmp_path), "--type", "Z"])
    assert excinfo.value.code == 2
    assert "unknown taxonomy type" in capsys.readouterr().err


def test_a_known_type_mixed_with_an_unknown_one_is_still_rejected(tmp_path):
    with pytest.raises(SystemExit):
        main([_write(tmp_path), "--type", "R,Z"])




def test_text_output_is_the_default(tmp_path, capsys):
    main([_write(tmp_path)])
    assert "Summary:" in capsys.readouterr().out


def test_exit_code_is_zero_even_with_findings(tmp_path):
    assert main([_write(tmp_path)]) == 0


def test_sort_defaults_to_benchmarked_types_first(tmp_path, capsys):
    main([_write(tmp_path), "--format", "json"])
    data = json.loads(capsys.readouterr().out)
    ranks = [
        0 if f["type"] in BENCHMARK_BACKED_TYPES else 1 for f in data["findings"]
    ]
    # Every benchmarked-type entry must precede every other one; this fixture
    # mixes S (benchmarked) and R (not) findings at the same file, so a
    # location-first sort would interleave them instead.
    assert ranks == sorted(ranks)


def test_sort_file_restores_the_pre_v1_1_location_order(tmp_path, capsys):
    main([_write(tmp_path), "--format", "json", "--sort", "file"])
    data = json.loads(capsys.readouterr().out)
    locations = [(f["file"], f["line"]) for f in data["findings"]]
    assert locations == sorted(locations)


def test_both_formats_agree_on_order_under_the_default_sort(tmp_path, capsys):
    path = _write(tmp_path)
    main([path, "--format", "json"])
    json_order = [(f["file"], f["line"], f["rule"]) for f in json.loads(capsys.readouterr().out)["findings"]]
    main([path, "--format", "text"])
    text_locations = re.findall(r"^(\S+):(\d+)  \S+ \(", capsys.readouterr().out, re.MULTILINE)
    assert [(loc[0], int(loc[1])) for loc in text_locations] == [
        (path, line) for path, line, _ in json_order
    ]


def test_dump_symbols_survives_an_unreadable_file(tmp_path, capsys):
    # --dump-symbols must not crash a whole sweep over one file it cannot
    # read, exactly like the analysis path already survives one. Surviving
    # is not succeeding, though: the readable file's symbols still come out,
    # and the exit code still says the run was incomplete. Asserting 0 here
    # is what let a sweep over a moved path report success with a short
    # index.
    readable = tmp_path / "ok.c"
    readable.write_text("static const unsigned char m[1] = {0};")
    blocked = tmp_path / "blocked.c"
    blocked.write_text("static const unsigned char n[1] = {1};")
    os.chmod(blocked, 0o000)
    try:
        code = main([str(tmp_path), "--dump-symbols"])
    finally:
        os.chmod(blocked, 0o644)
    assert code == 1
    assert "m" in capsys.readouterr().out


def test_version_flag_prints_the_version_and_exits_zero(capsys):
    import simde_lint

    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert simde_lint.__version__ in capsys.readouterr().out


def test_json_reports_the_tool_version_alongside_the_simde_version(tmp_path, capsys):
    import simde_lint

    main([_write(tmp_path), "--format", "json"])
    data = json.loads(capsys.readouterr().out)
    assert data["simde_lint_version"] == simde_lint.__version__


# The current text output over the module-level SOURCE fixture, with the temp
# file's absolute path swapped for a placeholder (the path itself is not
# stable across runs).
#
# This is a snapshot of what the renderer produces now, not a historical
# baseline that must never move. It was written for the version-provenance
# change, where the contract genuinely was "not a single byte", and the rule R
# grading correction has since replaced it deliberately -- R's grade, reason,
# rationale and cost line all changed, and the fixture gained an F call site.
# Regenerating it is the right response to an intended output change; the test
# exists so an *unintended* one has to be looked at rather than absorbed.
#
# The three findings cover the three suggestion-line shapes: an established
# replacement, both counts unknown, and one side known.
_TEXT_BASELINE = """<FILE>:8  F (multiply-add not fused)  evidence=A
    _mm_mullo_epi32 in kernel
    _mm_mullo_epi32 at line 8 reaches _mm_add_epi32 at line 9; the multiply and the accumulate are emitted as separate instructions; NEON fuses this into vmlaq_s32 for some accumulator shapes (x86/sse4.1.h:2077)
    suggestion: vmlaq_s32 (2 -> 1 instructions)

<FILE>:4  S (pshufb->tbl guard only)  evidence=C (unresolved)
    _mm_shuffle_epi8 in kernel
    SIMDe 0.8.4 guards the tbl index on every call; mask is produced by a call with unknown lanes (x86/ssse3.h:346)
    no suggestion offered (instruction count unknown)

<FILE>:3  R (zero-init before partial load)  evidence=C (transform_requires_context)
    _mm_loadu_si32 in kernel
    SIMDe 0.8.4 implements _mm_loadu_si32 as follows: vsetq_lane_s32(*ptr, vdupq_n_s32(0), 0) zeroes the vector before a lane load (x86/sse2.h:5760). That explicitly constructs the zero-valued lanes the intrinsic is defined to produce; removing the work may be lower-cost where those lanes are dead in the consuming code, but this rule does not analyse the consumer and so offers no replacement
    no suggestion offered (SIMDe expansion: 2 instructions; replacement count unknown)

Summary: 3 findings
  F (multiply-add not fused) [F.mul_add_no_fuse]: 1
  R (zero-init before partial load) [R.zero_init_partial_load]: 1
  S (pshufb->tbl guard only) [S.pshufb_guard]: 1
  evidence A: 1
  evidence C: 2
"""


def test_text_output_matches_the_current_snapshot(tmp_path, capsys):
    path = _write(tmp_path)
    main([path])
    output = capsys.readouterr().out.replace(path, "<FILE>")
    assert output == _TEXT_BASELINE


def test_the_declared_version_matches_the_package_metadata():
    """`__version__` drifted from 0.1.0 through four releases unnoticed.

    Nothing read it, so nothing caught it, and the v2.1.0 tag would have
    shipped a package whose metadata said 2.1.0 while `simde_lint.__version__`
    said 0.1.0. A release that disagrees with itself is worse for a cited
    artifact than one that is merely out of date.
    """
    import simde_lint

    assert simde_lint.__version__ == metadata_version("simde-lint")


def test_overlapping_paths_do_not_double_the_reported_findings(tmp_path, capsys):
    # The issue's own repro, at the level the user sees: `.` and the file
    # inside it name the same call sites, and the totals must not move.
    target = _write(tmp_path)
    main([target, "--format", "json"])
    alone = json.loads(capsys.readouterr().out)

    main([str(tmp_path), target, "--format", "json"])
    overlapping = json.loads(capsys.readouterr().out)

    assert alone["summary"]["total"] > 0
    assert overlapping["summary"]["total"] == alone["summary"]["total"]
    locations = [(f["file"], f["line"], f["rule"]) for f in overlapping["findings"]]
    assert len(locations) == len(set(locations))


def test_every_file_carrying_a_version_string_agrees_with_the_package():
    """`CITATION.cff` shipped `2.3.1` inside the `v2.3.2` tag.

    The release check reads the version out of the tool, which is the right
    check for the files the tool loads and no check at all for the ones it
    does not. `CITATION.cff` is read by citation tooling and by anyone
    following the repository from a paper, and it went a whole release
    without being noticed. Enumerating the files here means a new one is a
    deliberate addition to this list rather than a silent omission.
    """
    root = Path(__file__).resolve().parent.parent
    expected = metadata_version("simde-lint")

    citation = (root / "CITATION.cff").read_text()
    declared = re.search(r"^version: (.+)$", citation, re.MULTILINE)
    assert declared is not None, "CITATION.cff declares no version"
    assert declared.group(1).strip() == expected

    pyproject = (root / "pyproject.toml").read_text()
    declared = re.search(r'^version = "(.+)"$', pyproject, re.MULTILINE)
    assert declared is not None, "pyproject.toml declares no version"
    assert declared.group(1) == expected
