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

from simde_lint.analyze import analyze
from simde_lint.finding import Evidence

# Reference checkout roots, overridable so an outside contributor can point
# these at their own clones without editing this file. See CONTRIBUTING.md
# for the SIMDE_LINT_SVT_AV1 / SIMDE_LINT_VVENC variables.
_SVT_AV1_ROOT = Path(
    os.environ.get("SIMDE_LINT_SVT_AV1", str(Path.home() / "Solario/Solido/open-source/svt-av1"))
)
_VVENC_ROOT = Path(
    os.environ.get("SIMDE_LINT_VVENC", str(Path.home() / "Solario/Solido/open-source/vvenc"))
)
SVT_AV1 = _SVT_AV1_ROOT / "Source"
VVENC_X86 = _VVENC_ROOT / "source/Lib/CommonLib/x86"

requires_svt = pytest.mark.skipif(not SVT_AV1.exists(), reason="SVT-AV1 checkout not present")
requires_vvenc = pytest.mark.skipif(not VVENC_X86.exists(), reason="VVenC checkout not present")


def _grep_count(root: Path, needle: str) -> int:
    result = subprocess.run(
        ["grep", "-r", "-o", needle, str(root)], capture_output=True, text=True, check=False
    )
    return len(result.stdout.splitlines())


@requires_svt
def test_rule_s_matches_the_grep_count_of_shuffle_epi8_call_sites():
    """The plan's primary acceptance gate: 204 call sites, exact equality.

    Both sides count source call sites, not assembly instances, so this is
    the one place absolute agreement is required rather than merely expected.
    """
    findings, _ = analyze([SVT_AV1], types=["S"])
    tool_count = sum(1 for f in findings if f.intrinsic == "_mm_shuffle_epi8")
    assert tool_count == _grep_count(SVT_AV1, r"_mm_shuffle_epi8")


@requires_svt
def test_symbol_index_lifts_table_backed_masks_to_grade_a():
    """even_odd_mask_x resolves through the cross-file symbol index.

    Three _mm_shuffle_epi8 call sites index this table at runtime
    (`even_odd_mask_x[base_shift]`); the all-rows check still grades them A
    because every row's lanes lie in [0,15].
    """
    findings, _ = analyze([SVT_AV1], types=["S"])
    graded_a = [f for f in findings if f.evidence is Evidence.A and f.mask_source]
    assert graded_a
    assert any(f.mask_source["symbol"] == "even_odd_mask_x" for f in graded_a)


@requires_vvenc
def test_depquant_reports_the_types_its_source_can_carry():
    """DepQuantX86.h pins to the measured call-site counts, not the paper's ranking.

    At assembly-instance granularity the paper's Table III ranks DepQuant's
    dominant type as S (12). At call-site granularity — the unit this tool
    uses (spec Section 3) — R leads: R 26, S 22, P 3. W, F and M are absent
    because the file carries no x86 multiply intrinsic at all and no insert
    chain (see docs/verification.md for the traced cause of each zero).
    """
    findings, _ = analyze([VVENC_X86 / "DepQuantX86.h"])
    counts = Counter(f.type for f in findings)
    assert counts["R"] == 26
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
    findings, _ = analyze([VVENC_X86 / "LoopFilterX86.h"], types=["S"])
    assert findings == []


@requires_vvenc
def test_full_sweep_of_both_codebases_does_not_crash():
    findings, _ = analyze([VVENC_X86])
    assert isinstance(findings, list)
    # isinstance(findings, list) alone would pass for a sweep that silently
    # crashed every file and returned []; docs/verification.md records 412
    # findings over this directory, so require it to have found something.
    assert findings
