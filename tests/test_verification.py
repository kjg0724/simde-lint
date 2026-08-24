"""Verification against the two reference codebases the taxonomy was built from.

These tests document measured behaviour; they are not exploratory. Every
assertion here pins a number that was independently re-run against the
current build (see docs/verification.md for the full comparison and the
established cause of every divergence from the paper).

Tests that need a reference checkout skip cleanly when it is absent, so the
suite stays runnable for an outside contributor who has neither clone.
"""

from __future__ import annotations

import os
import subprocess
from collections import Counter
from pathlib import Path

import pytest

from simde_lint.analyze import analyze, read_sources
from simde_lint.finding import Evidence
from simde_lint.knowledge import load_knowledge
from simde_lint.macros import build_alias_map, reparse_macros
from simde_lint.parser import parse_source
from simde_lint.rules import memory, suboptimal, widening

# Reference checkout roots, read only from the environment (see
# CONTRIBUTING.md for SIMDE_LINT_SVT_AV1 / SIMDE_LINT_VVENC). There is
# deliberately no fallback to a local path here: this file is public, and a
# default checkout location would publish the author's own directory layout
# for no verification benefit -- a contributor without the variable set gets
# a clean skip, exactly as one without a clone at all does.
_SVT_AV1_ENV = os.environ.get("SIMDE_LINT_SVT_AV1")
_VVENC_ENV = os.environ.get("SIMDE_LINT_VVENC")
SVT_AV1 = Path(_SVT_AV1_ENV) / "Source" if _SVT_AV1_ENV else Path("/nonexistent-svt-av1-checkout")
VVENC_X86 = (
    Path(_VVENC_ENV) / "source/Lib/CommonLib/x86" if _VVENC_ENV else Path("/nonexistent-vvenc-checkout")
)

requires_svt = pytest.mark.skipif(not SVT_AV1.exists(), reason="SVT-AV1 checkout not present")
requires_vvenc = pytest.mark.skipif(not VVENC_X86.exists(), reason="VVenC checkout not present")


def _grep_count(root: Path, needle: str) -> int:
    result = subprocess.run(
        ["grep", "-r", "-o", needle, str(root)], capture_output=True, text=True, check=False
    )
    return len(result.stdout.splitlines())


def _recognized_intrinsic_names() -> set[str]:
    """Every name the knowledge tables treat as an x86 intrinsic.

    Derived from the tables rather than listed literally, so a rule that
    registers a new intrinsic family widens this set with it and the caller
    below keeps testing the property rather than a snapshot of it.
    """
    knowledge = load_knowledge()
    names = set(knowledge.redundant)
    for table in knowledge.patterns.values():
        names |= set(table)
    # An alias's canonical target is what a normalized call site reports.
    names |= set(knowledge.aliases.values())
    return names


@requires_svt
def test_rule_s_matches_the_grep_count_of_shuffle_epi8_call_sites():
    """The plan's primary acceptance gate: 204 call sites, exact equality.

    Both sides count source call sites, not assembly instances, so this is
    the one place absolute agreement is required rather than merely expected.
    """
    findings, _, _ = analyze([SVT_AV1], types=["S"])
    tool_count = sum(1 for f in findings if f.intrinsic == "_mm_shuffle_epi8")
    assert tool_count == _grep_count(SVT_AV1, r"_mm_shuffle_epi8")


@requires_svt
def test_macro_findings_are_reported_with_their_macro_name():
    """Macro-scoped findings name the macro they sit in, and no function.

    v1.2 analyses `#define` bodies, so a finding no longer always belongs to
    a function. `scope` says which kind of unit produced it and `function` /
    `macro` are mutually exclusive (spec Section 9); docs/verification.md
    Section 5 records the 28 SVT-AV1 macro findings this walks over.
    """
    findings, _, _ = analyze([SVT_AV1])
    macro = [f for f in findings if f.scope == "macro"]
    assert macro, "expected findings inside macro bodies"
    assert all(f.macro and f.function is None for f in macro)


@requires_svt
def test_every_reported_intrinsic_is_a_name_the_knowledge_tables_recognize():
    """No macro name may leak into a finding's `intrinsic` field.

    Before v1.2 a macro was registered as a forwarding alias for whichever
    identifier appeared first in its body, so a call site of a multi-call
    macro was reported as a call to an intrinsic it merely happened to
    mention first. `is_forwarding_alias` now admits only single-call bodies
    whose callee normalizes to a recognized intrinsic, and macro bodies that
    fail that test become units of their own instead.

    The property is checked against the recognized set derived from the
    knowledge tables, not against a couple of macro-name prefixes: a
    misattribution can carry any spelling, including one that looks like an
    intrinsic (SVT-AV1 defines macros literally named `_mm_loadu_si64` and
    `_mm256_setr_m128i`), so a prefix heuristic would pass while the field
    was wrong.

    The old defect was silent rather than visible: the 15 misregistrations
    measured across the two reference checkouts all pointed at names outside
    every rule's anchor set (`_mm256_inserti128_si256`, `_mm_unpacklo_epi64`
    and the like), so no finding was emitted on them and the totals did not
    move. This assertion is what turns "no rule happens to anchor on a
    misattributed name" into an enforced invariant: register one of those
    names in `knowledge/` under a rule, and a resurfaced misattribution
    fails here instead of being reported as a real call site.
    """
    findings, _, _ = analyze([SVT_AV1])
    recognized = _recognized_intrinsic_names()
    unrecognized = sorted({f.intrinsic for f in findings} - recognized)
    assert unrecognized == []


@requires_svt
def test_symbol_index_lifts_table_backed_masks_to_grade_a():
    """even_odd_mask_x resolves through the cross-file symbol index.

    Three _mm_shuffle_epi8 call sites index this table at runtime
    (`even_odd_mask_x[base_shift]`); the all-rows check still grades them A
    because every row's lanes lie in [0,15].
    """
    findings, _, _ = analyze([SVT_AV1], types=["S"])
    graded_a = [f for f in findings if f.evidence is Evidence.A and f.mask_source]
    assert graded_a
    assert any(f.mask_source["symbol"] == "even_odd_mask_x" for f in graded_a)


@requires_vvenc
def test_depquant_reports_the_types_its_source_can_carry():
    """DepQuantX86.h pins to the measured call-site counts, not the paper's ranking.

    At assembly-instance granularity the paper's Table III ranks DepQuant's
    dominant type as S (12). At call-site granularity — the unit this tool
    uses (spec Section 3) — R leads: R 40, S 22, P 3. W, F and M are absent
    because the file carries no x86 multiply intrinsic at all and no insert
    chain (see docs/verification.md for the traced cause of each zero). R's
    26 -> 40 jump (v1.1) comes from `_mm_loadu_si64`, added to
    `knowledge/redundant.yaml` after the paper's R=4 undercounted DepQuant's
    14 call sites of it.
    """
    findings, _, _ = analyze([VVENC_X86 / "DepQuantX86.h"])
    counts = Counter(f.type for f in findings)
    assert counts["R"] == 40
    assert counts["S"] == 22
    assert counts["P"] == 3
    assert counts["W"] == 0
    assert counts["F"] == 0
    assert counts["M"] == 0


@requires_vvenc
def test_loopfilter_reports_no_type_s_as_the_spec_declares():
    """Declared exclusion, not a miss: rule S implements only the pshufb guard.

    LoopFilterX86.h's Type S instances in the paper are transpose and blend
    sequences; it contains zero _mm_shuffle_epi8 call sites, so reporting
    nothing here is the expected outcome (spec Section 2), not a defect.
    """
    findings, _, _ = analyze([VVENC_X86 / "LoopFilterX86.h"], types=["S"])
    assert findings == []


@requires_vvenc
def test_full_sweep_of_both_codebases_does_not_crash():
    findings, _, _ = analyze([VVENC_X86])
    assert isinstance(findings, list)
    # isinstance(findings, list) alone would pass for a sweep that silently
    # crashed every file and returned []; docs/verification.md records 449
    # findings over this directory, so require it to have found something.
    assert findings


@requires_svt
@requires_vvenc
def test_no_confirmed_alias_target_over_both_checkouts_reaches_an_operand_sensitive_anchor():
    """The real C1 tripwire: run against the checkouts, not a hand-picked fixture.

    `tests/test_extract.py::
    test_confirmed_alias_targets_do_not_reach_an_operand_sensitive_rule_anchor`
    checks three shapes written inside the test file, so it can never observe
    a confirmed alias from an actual codebase. This test runs the same
    `reparse_macros`/`build_alias_map` machinery `extract_units` uses over
    every file `analyze()` would scan in SVT-AV1 `Source` and VVenC
    `CommonLib/x86`, and asserts the resulting alias-target set is disjoint
    from the narrowed operand-sensitive anchor union.

    That union is `suboptimal._TARGETS (S) | memory._SCALAR_SETS |
    memory._INSERTS (M) | widening._UNPACK | {_mm_mullo_epi16,
    _mm_mulhi_epi16} (W)` -- the three rules that read `call.args[N]` or
    `len(call.args)`, and so are genuinely misled by an alias that forwards
    its operands unfaithfully (see docs/verification.md, "The
    forwarding-alias argument list", for two measured examples). `fusion._*`
    and `pipeline._COMPARES` (F and P) are deliberately excluded: both read
    only operand *membership* (`arg.text == result_var`), which an operand
    reversal or an arity mismatch cannot affect. `_mm_cmpgt_epi64` -- the
    confirmed target of VVenC's `_my_cmpgt_epi64`, which is why rule P's
    DepQuant count agrees with the paper (docs/verification.md, "DepQuant P:
    3 vs 3") -- therefore sits outside this anchor union deliberately, not by
    coincidence: adding `pipeline._COMPARES` back into the union above makes
    this test fail, because `_mm_cmpgt_epi64` is a confirmed alias target
    over VVenC and is a member of that set.
    """
    knowledge = load_knowledge()
    operand_sensitive_anchors = (
        suboptimal._TARGETS
        | memory._SCALAR_SETS
        | memory._INSERTS
        | widening._UNPACK
        | {"_mm_mullo_epi16", "_mm_mulhi_epi16"}
    )

    alias_targets: set[str] = set()
    for _, source in read_sources([SVT_AV1, VVENC_X86]):
        root = parse_source(source).root_node
        macros = reparse_macros(root, source)
        alias_targets |= set(build_alias_map(macros, knowledge).values())

    assert alias_targets, "expected at least one confirmed forwarding alias across both checkouts"
    assert "_mm_cmpgt_epi64" in alias_targets, (
        "this is the known case the anchor union deliberately excludes P for "
        "-- if it stops resolving, the exclusion's premise needs rechecking"
    )
    assert alias_targets.isdisjoint(operand_sensitive_anchors)
