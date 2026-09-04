"""`--config` validation: what the tool refuses to act on, and why.

The defect these pin: a config the tool could not honour produced a report
anyway. A wrong-typed threshold raised inside rule M once per unit, leaving a
well-formed but empty report; an unknown key and a negative threshold were
accepted silently, so a typo'd config produced output identical to a correct
run. That last shape is the worst of them -- nothing distinguishes it from
success.
"""

import json

import pytest

from simde_lint.analyze import analyze
from simde_lint.cli import main
from simde_lint.rules import ALL_RULES, ConfigError, validate_config

SOURCE = """
void kernel(__m128i d, short v) {
    d = _mm_insert_epi16(d, v, 0);
    d = _mm_insert_epi16(d, v, 1);
    d = _mm_insert_epi16(d, v, 2);
    (void)d;
}
"""


def _write(tmp_path, config_text=None):
    src = tmp_path / "k.c"
    src.write_text(SOURCE)
    if config_text is None:
        return [str(src)]
    cfg = tmp_path / "c.json"
    cfg.write_text(config_text)
    return [str(src), "--config", str(cfg)]


@pytest.mark.parametrize(
    "text, fragment",
    [
        ('{"memory_chain_threshold": "3"}', "must be int, not str"),
        ('{"memory_chain_threshold": 3.0}', "must be int, not float"),
        # bool is a subclass of int, and `true` is not a threshold.
        ('{"memory_chain_threshold": true}', "must be int, not bool"),
        ('{"memory_chain_threshold": 0}', "at least 1"),
        ('{"memory_chain_threshold": -1}', "at least 1"),
        ('{"typo_key": 5}', "unsupported option"),
        ("[1, 2]", "must be a JSON object"),
        ("null", "must be a JSON object"),
        ('"three"', "must be a JSON object"),
    ],
)
def test_the_cli_rejects_a_config_it_cannot_honour(tmp_path, capsys, text, fragment):
    with pytest.raises(SystemExit) as excinfo:
        main(_write(tmp_path, text))
    # 2, the argparse usage-error code: this is a bad invocation, not a
    # failed analysis. 1 would be indistinguishable from a run that found
    # unreadable inputs.
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert fragment in err
    assert "Traceback" not in err


def test_a_missing_or_malformed_config_file_is_one_controlled_error(tmp_path, capsys):
    src = tmp_path / "k.c"
    src.write_text(SOURCE)

    with pytest.raises(SystemExit) as missing:
        main([str(src), "--config", str(tmp_path / "absent.json")])
    assert missing.value.code == 2
    assert "cannot read" in capsys.readouterr().err

    bad = tmp_path / "bad.json"
    bad.write_text("{ not json")
    with pytest.raises(SystemExit) as malformed:
        main([str(src), "--config", str(bad)])
    assert malformed.value.code == 2
    err = capsys.readouterr().err
    assert "not valid JSON" in err
    assert "Traceback" not in err


def test_an_invalid_config_produces_no_report_at_all(tmp_path, capsys):
    """The failure mode that looked like success.

    A wrong-typed threshold used to raise inside the rule, once per unit,
    after discovery and extraction had already run -- so stdout carried a
    well-formed report with an empty findings list. Nothing may be printed on
    stdout now, because a report is a claim about the code and this run made
    no analysis to claim anything from.
    """
    with pytest.raises(SystemExit):
        main(_write(tmp_path, '{"memory_chain_threshold": "3"}') + ["--format", "json"])
    assert capsys.readouterr().out == ""


def test_an_invalid_config_is_rejected_before_any_file_is_opened(monkeypatch, tmp_path):
    """Empty output is not enough: it holds however late the check runs.

    Validating after discovery would still print nothing, because the raise
    happens before the report is rendered either way. What distinguishes the
    two is whether the tool read the source at all -- and reading a tree only
    to throw the result away is work done on a request it was never going to
    honour. `read_sources` is the boundary, so it must not be reached.
    """
    import simde_lint.analyze as analyze_module

    def fail(*args, **kwargs):
        raise AssertionError("read_sources reached with an invalid config")

    monkeypatch.setattr(analyze_module, "read_sources", fail)
    src = tmp_path / "k.c"
    src.write_text(SOURCE)
    with pytest.raises(ConfigError):
        analyze([src], config={"memory_chain_threshold": "3"})


def test_a_valid_threshold_changes_which_chains_qualify(tmp_path, capsys):
    # Both directions: a test that only raised the threshold would pass with
    # validation that silently dropped the value.
    main(_write(tmp_path, '{"memory_chain_threshold": 3}') + ["--format", "json"])
    assert len(json.loads(capsys.readouterr().out)["findings"]) == 1

    main(_write(tmp_path, '{"memory_chain_threshold": 9}') + ["--format", "json"])
    assert json.loads(capsys.readouterr().out)["findings"] == []


def test_an_omitted_option_gets_its_declared_default(tmp_path, capsys):
    main(_write(tmp_path) + ["--format", "json"])
    without = json.loads(capsys.readouterr().out)["findings"]
    main(_write(tmp_path, '{"memory_chain_threshold": 3}') + ["--format", "json"])
    assert json.loads(capsys.readouterr().out)["findings"] == without


def test_analyze_validates_too_rather_than_trusting_the_cli(tmp_path):
    """`analyze` is a public entry point with the same exposure as the CLI.

    Validating only in `cli.py` would leave every library caller with the
    per-unit failure this change removes.
    """
    src = tmp_path / "k.c"
    src.write_text(SOURCE)
    with pytest.raises(ConfigError):
        analyze([src], config={"memory_chain_threshold": "3"})
    with pytest.raises(ConfigError):
        analyze([src], config={"typo_key": 5})


def test_every_registered_rule_declares_its_options(tmp_path):
    """Including the rules that take none.

    `validate_config` builds the accepted set from these declarations, so a
    rule that omitted the attribute would have its options rejected as
    unknown -- and one that reads a key it never declared would be worse: the
    key would be rejected before the rule ever saw it.
    """
    for rule in ALL_RULES:
        assert hasattr(rule, "options"), rule.rule_id
        assert isinstance(rule.options, tuple), rule.rule_id


def test_no_two_rules_declare_the_same_key():
    names = [option.name for rule in ALL_RULES for option in rule.options]
    assert len(names) == len(set(names))

    class Clashing:
        rule_id = "X.clash"
        options = tuple(
            option for rule in ALL_RULES for option in rule.options
        )

    if names:
        with pytest.raises(ConfigError, match="more than one rule"):
            validate_config({}, list(ALL_RULES) + [Clashing()])
