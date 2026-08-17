import json
import os

import pytest

from simde_lint.cli import main

SOURCE = """
void kernel(const int *src, __m128i data) {
    __m128i a = _mm_loadu_si32(src);
    __m128i b = _mm_shuffle_epi8(data, _mm_loadu_si128((const __m128i *)src));
    (void)a; (void)b;
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
    assert data["findings"]
    assert all(f["evidence"] == "A" for f in data["findings"])


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


def test_impact_confirmed_drops_diagnostic_findings(tmp_path, capsys):
    main([_write(tmp_path), "--format", "json", "--impact", "confirmed"])
    data = json.loads(capsys.readouterr().out)
    # Same trap as above: all(...) over an empty list is vacuously true.
    assert data["findings"]
    assert all(f["impact"] == "confirmed" for f in data["findings"])


def test_text_output_is_the_default(tmp_path, capsys):
    main([_write(tmp_path)])
    assert "Summary:" in capsys.readouterr().out


def test_exit_code_is_zero_even_with_findings(tmp_path):
    assert main([_write(tmp_path)]) == 0


def test_dump_symbols_survives_an_unreadable_file(tmp_path):
    # --dump-symbols must not crash a whole sweep over one file it cannot
    # read, exactly like the analysis path already survives one.
    readable = tmp_path / "ok.c"
    readable.write_text("static const unsigned char m[1] = {0};")
    blocked = tmp_path / "blocked.c"
    blocked.write_text("static const unsigned char n[1] = {1};")
    os.chmod(blocked, 0o000)
    try:
        code = main([str(tmp_path), "--dump-symbols"])
    finally:
        os.chmod(blocked, 0o644)
    assert code == 0
