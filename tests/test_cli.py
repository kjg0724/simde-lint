import json

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
    assert all(f["evidence"] == "A" for f in data["findings"])


def test_type_filter_restricts_output(tmp_path, capsys):
    main([_write(tmp_path), "--format", "json", "--type", "R"])
    data = json.loads(capsys.readouterr().out)
    assert {f["type"] for f in data["findings"]} == {"R"}


def test_impact_confirmed_drops_diagnostic_findings(tmp_path, capsys):
    main([_write(tmp_path), "--format", "json", "--impact", "confirmed"])
    data = json.loads(capsys.readouterr().out)
    assert all(f["impact"] == "confirmed" for f in data["findings"])


def test_text_output_is_the_default(tmp_path, capsys):
    main([_write(tmp_path)])
    assert "Summary:" in capsys.readouterr().out


def test_exit_code_is_zero_even_with_findings(tmp_path):
    assert main([_write(tmp_path)]) == 0
