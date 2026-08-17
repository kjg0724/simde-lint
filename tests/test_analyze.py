"""End-to-end coverage of analyze() itself, not any single rule.

test_report.py pins "one location may produce multiple findings" with
hand-built Finding objects; nothing exercised the real pipeline (extract +
every rule + no merging) to confirm it holds there too.
"""

from __future__ import annotations

from pathlib import Path

from simde_lint.analyze import analyze

FIXTURE = Path(__file__).parent / "fixtures" / "analyze" / "multi_rule_one_line.c"


def test_two_different_rules_fire_at_the_same_source_line():
    # `_mm_cmpgt_epi64` and `_mm_shuffle_epi8(mask, ...)` sit on the same
    # physical line: the compare's result is consumed by the very next call
    # (rule P), and that same call is a shuffle with a safe inline mask
    # (rule S). Neither rule may be dropped in favor of the other.
    findings, _ = analyze([FIXTURE])
    same_line = [f for f in findings if f.file == str(FIXTURE) and f.line == 2]
    types = {f.type for f in same_line}
    assert {"P", "S"} <= types
    rule_ids = {f.rule for f in same_line}
    assert {"P.cmp_immediate_use", "S.pshufb_guard"} <= rule_ids
