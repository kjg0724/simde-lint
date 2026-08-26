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
    its operands unfaithfully as the *producer* call (see
    docs/verification.md, "The forwarding-alias argument list", for two
    measured examples). `fusion._*` and `pipeline._COMPARES` (F and P) are
    deliberately excluded here for a narrower reason than "safe": both
    decide by operand *membership* (`arg.text == result_var`), so a
    *producer* alias's own operand position (which neither rule reads)
    cannot mislead them, regardless of what this anchor union contains.
    They are not excluded because a *consuming* alias is safe -- it is not,
    in general (`is_forwarding_alias` cannot detect every way a body can
    drop a parameter's value; see `docs/verification.md`'s forwarding-alias
    section for `DROP_VALUE`). F and P's protection against that is not
    this anchor union at all: `PipelineRule.match`/`FusionRule._path`
    decline to read a consumer call's args whenever that call carries a
    `raw_name`, unconditionally, regardless of which intrinsic it resolves
    to or whether this union contains it. `_mm_cmpgt_epi64` -- the confirmed
    target of VVenC's `_my_cmpgt_epi64`, which is why rule P's DepQuant
    count agrees with the paper (docs/verification.md, "DepQuant P: 3 vs
    3") -- sits outside this anchor union because, as a *producer*, an
    operand reversal at that call site cannot mislead P's membership check;
    adding `pipeline._COMPARES` back into the union above makes this test
    fail, because `_mm_cmpgt_epi64` is a confirmed alias target over VVenC
    and is a member of that set. That failure would say nothing about
    whether P is sound at that call site -- it still would be, because
    `_my_cmpgt_epi64` is the producer there, not the consumer.
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
        alias_targets |= set(build_alias_map(macros, knowledge).targets.values())

    assert alias_targets, "expected at least one confirmed forwarding alias across both checkouts"
    assert "_mm_cmpgt_epi64" in alias_targets, (
        "this is the known case the anchor union deliberately excludes P for "
        "-- if it stops resolving, the exclusion's premise needs rechecking"
    )
    assert alias_targets.isdisjoint(operand_sensitive_anchors)


@requires_svt
@requires_vvenc
def test_no_pipeline_or_fusion_finding_over_both_checkouts_has_a_macro_resolved_consumer():
    """P1 round 4: what is actually enforced, stated at the narrowest scope that is true.

    An earlier round of this predicate tried to make registration itself
    reject any alias that drops a parameter -- `is_forwarding_alias`
    refusing to register a body that never mentions one of its parameters.
    That is unsound: `#define DROP_VALUE(a, b) _mm_add_epi32(((void)(a),
    (b)), (b))` still mentions `a`, inside a `(void)`-cast comma operand
    whose value never reaches the forwarded call, so a text-appearance
    check confirms it as an alias anyway. `(a) ^ (a)` is accepted the same
    way. Both are live false positives at rule level, reproduced in
    `tests/test_rule_pipeline.py`/`tests/test_rule_fusion.py`.

    **What is actually enforced, not approximated:** `PipelineRule.match`
    and `FusionRule._path` decline to read a *consumer* call's args at all
    once that call was resolved through a **file-local `#define` wrapper
    macro** (`IntrinsicCall.is_macro_alias`, set at extraction from
    `macros.build_alias_map`'s file-local `aliases` map) -- see
    `rules/pipeline.py`/`rules/fusion.py`. This is unconditional and does
    not depend on what `is_forwarding_alias` decided about the alias; it is
    sound for any corpus, not only these two, because it is enforced in the
    rule's own control flow rather than approximated from the alias's
    syntax.

    **What this guard explicitly does NOT cover, and why that is correct
    (P2):** a call whose spelling changed only through
    `knowledge/aliases.yaml` normalization -- `simde_mm_shuffle_epi8`
    resolving to `_mm_shuffle_epi8`, for instance -- also has `raw_name !=
    name`, exactly like a macro alias does, but carries none of the macro
    alias's risk: SIMDe exposes every intrinsic under a `simde_` prefix
    with the identical signature to its native spelling by its own naming
    convention (verified directly: `ssse3.h:388` is `#define
    _mm_shuffle_epi8(a, b) simde_mm_shuffle_epi8(a, b)`, `ssse3.h:336` is
    `simde_mm_shuffle_epi8(simde__m128i a, simde__m128i b)` -- same arity,
    same order), so there is no macro body to drop, duplicate or discard a
    parameter's value in. Guarding on `raw_name != name` abstained on this
    too, for zero soundness gain, discarding a true positive. `is_macro_alias`
    is False for this case, so the guard fires only where the risk actually
    is. `tests/test_rule_pipeline.py`/`tests/test_rule_fusion.py` pin both
    directions in one fixture file each: a wrapper-macro consumer abstains,
    a direct `simde_`-spelled consumer does not.

    **What this test measures, and what it does not:** it is a fact about
    these two corpora, not a proof of anything general. Over every P
    "compare consumed" candidate and F "multiply reaches an add" candidate
    actually realized in SVT-AV1 `Source` and VVenC `CommonLib/x86`, zero
    have a consumer call resolved through a file-local wrapper macro -- the
    shape the abstention exists for does not occur at the consumer position
    in either reference codebase (confirmed separately: the only `simde_mm_`
    spelling anywhere in either corpus is VVenC's `_my_cmpgt_epi64`
    macro's own *body*, `#define _my_cmpgt_epi64(a, b)
    simde_mm_cmpgt_epi64(a, b)` -- a producer-side alias, never a consumer,
    and irrelevant to this guard either way). A codebase that does have a
    wrapper-macro consumer will produce fewer F/P findings under this tool
    than a version without the abstention would have (see the release
    notes' known limitations) -- that loss is not visible here because
    neither reference corpus pays it.
    """
    from simde_lint.extract import extract_units
    from simde_lint.ir import ValueKind
    from simde_lint.rules.fusion import _ADDS
    from simde_lint.rules.pipeline import _COMPARES

    knowledge = load_knowledge()
    p_macro_consumers = 0
    p_direct_alias_consumers = 0
    p_total_consumers = 0
    f_macro_adds = 0
    f_direct_alias_adds = 0
    f_total_adds = 0
    for path, source in read_sources([SVT_AV1, VVENC_X86]):
        for unit in extract_units(path, source, knowledge):
            ordered = sorted(unit.calls, key=lambda c: c.start_byte)
            for current, following in zip(ordered, ordered[1:]):
                if current.name not in _COMPARES or not current.result_var:
                    continue
                consumed = any(
                    arg.kind is ValueKind.VARIABLE and arg.text == current.result_var
                    for arg in following.args
                )
                if consumed:
                    p_total_consumers += 1
                    if following.is_macro_alias:
                        p_macro_consumers += 1
                    elif following.raw_name != following.name:
                        # A knowledge-table normalization, not a macro --
                        # the case P2 recovers. Counted separately so a
                        # nonzero value here is visible as a gain
                        # opportunity, not folded into the macro count above.
                        p_direct_alias_consumers += 1
            for add in unit.calls:
                if add.name in _ADDS:
                    f_total_adds += 1
                    if add.is_macro_alias:
                        f_macro_adds += 1
                    elif add.raw_name != add.name:
                        f_direct_alias_adds += 1

    assert p_total_consumers > 0 and f_total_adds > 0, (
        "expected at least one P consumer candidate and one F add call across "
        "both checkouts -- an empty corpus would make the zero below meaningless"
    )
    assert p_macro_consumers == 0, (
        f"{p_macro_consumers} of {p_total_consumers} P consumer candidates are "
        "macro-resolved -- the abstention now has something real to discard in this corpus"
    )
    assert f_macro_adds == 0, (
        f"{f_macro_adds} of {f_total_adds} F add calls are macro-resolved -- the "
        "abstention now has something real to discard in this corpus"
    )
    # P2's fix recovers a finding only where a direct simde_-spelled call
    # was a P/F consumer; both are zero in these two corpora too, which is
    # the measured reason the fix's finding-set diff over both sweeps is
    # exactly empty, not merely why the old, broader guard happened not to
    # discard anything.
    assert p_direct_alias_consumers == 0
    assert f_direct_alias_adds == 0
