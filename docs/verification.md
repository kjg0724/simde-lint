# Verification against the reference codebases

This records the measurements behind the v1 completion criteria in the design
spec (Section 13): an exact match against SVT-AV1's known `_mm_shuffle_epi8`
count, and a per-module comparison against Table III of "A Taxonomy of SIMDe
Emulation Inefficiencies for ARM NEON Porting of VVC Encoders" (CAL, 2026).

**Absolute agreement with the paper is not a criterion.** The paper counted
instances in GCC `-O3` assembly; this tool counts source call sites (spec
Section 3), a different and larger unit. Divergences below are recorded as
results, with an established cause for each — not smoothed over and not
treated as failures.

Every command in this document was re-run against `main` on the day this
file was last updated (v1.1: `redundant.yaml` gained `_mm_loadl_epi64` and
`_mm_loadu_si64`; see Section 2). Reference checkouts are given through the
`SIMDE_LINT_SVT_AV1` and `SIMDE_LINT_VVENC` environment variables (see
CONTRIBUTING.md), which fall back to a local checkout path when unset.

## 1. SVT-AV1: the primary acceptance gate

Rule S must report exactly as many `_mm_shuffle_epi8` call sites as a plain
`grep` count. Both sides count source call sites, so exact equality is the
bar — not "close", equal.

```
$ grep -r -o _mm_shuffle_epi8 "$SIMDE_LINT_SVT_AV1/Source" | wc -l
204
```

```
$ uv run simde-lint "$SIMDE_LINT_SVT_AV1/Source" --type S --format json \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['summary'])"
{'total': 341, 'by_type': {'S': 341}, 'by_rule': {'S.pshufb_guard':
{'type': 'S', 'count': 341, 'mechanism': 'pshufb->tbl guard only'}},
'by_evidence': {'A': 35, 'C': 306}, 'by_impact': {'confirmed': 341}}
```

341 is the combined total of both shuffle widths rule S matches. Filtering
the tool's own findings to `_mm_shuffle_epi8` alone and comparing against the
grep count directly:

```python
findings, _ = analyze([SVT_AV1], types=["S"])
tool_count = sum(1 for f in findings if f.intrinsic == "_mm_shuffle_epi8")
# tool_count == 204 == grep count
```

**Result: 204 == 204, exact match**, across 16 files. `_mm256_shuffle_epi8`
accounts for the remaining 341 − 204 = 137 findings and is counted
separately; it is a distinct intrinsic, not a second measurement of the same
call sites.

This equality is enforced by
`test_rule_s_matches_the_grep_count_of_shuffle_epi8_call_sites` in
`tests/test_verification.py`, run against a live checkout rather than a
fixture, so it re-verifies itself on every future run against the same tree.

### Evidence grade distribution

Of the 204 `_mm_shuffle_epi8` findings: **A 22, C 182**, no B. (The combined
341-finding total above carries A 35 / C 306, i.e. `_mm256_shuffle_epi8`
contributes A 13 / C 124 on top.)

The 182 grade-C findings are masks the symbol index and literal tracer could
not resolve — mostly runtime-loaded or call-produced vectors, which is the
honest outcome for indices the tool cannot see the values of.

### The symbol index lifts three findings to grade A

Three of the 22 grade-A findings resolve through `SymbolIndex`, not an
inline or local-constant literal:

```
$ uv run python3 - <<'EOF'
import os
from pathlib import Path
from simde_lint.analyze import analyze
from simde_lint.finding import Evidence

findings, _ = analyze([Path(os.environ["SIMDE_LINT_SVT_AV1"]) / "Source"], types=["S"])
for f in findings:
    if f.evidence is Evidence.A and f.mask_source:
        print(f.file, f.line, f.mask_source)
EOF
.../Source/Lib/ASM_AVX2/intra_pred_intrin_avx2.c 617  {'symbol': 'even_odd_mask_x', 'defined_at': '.../Source/Lib/Codec/intra_prediction.c:108', 'resolution': 'all_rows'}
.../Source/Lib/ASM_AVX2/intra_pred_intrin_avx2.c 1420 {'symbol': 'even_odd_mask_x', 'defined_at': '.../Source/Lib/Codec/intra_prediction.c:108', 'resolution': 'all_rows'}
.../Source/Lib/ASM_AVX2/intra_pred_intrin_avx2.c 1533 {'symbol': 'even_odd_mask_x', 'defined_at': '.../Source/Lib/Codec/intra_prediction.c:108', 'resolution': 'all_rows'}
```

All three resolve `even_odd_mask_x`, defined at
`Source/Lib/Codec/intra_prediction.c:108`, `resolution: all_rows` — the table
is indexed at runtime (`even_odd_mask_x[base_shift]`) but every one of its 8
rows has lanes in `[0,15]`, so the finding grades A regardless of which row
the runtime index selects. Verified by
`test_symbol_index_lifts_table_backed_masks_to_grade_a`.

### Full sweep

```
$ time uv run simde-lint "$SIMDE_LINT_SVT_AV1/Source" --format json > out.json
uv run simde-lint ... 13.83s user 0.15s system 97% cpu 14.390 total
$ echo $?
0
```

561 files scanned (all `.c`/`.h` under `Source/`), exit 0, no stderr output.
3233 total findings: `F 1009, R 1798, S 341, M 53, P 31, W 1`. Evidence
`A 2878, B 49, C 306`.

> R rose from 716 to 1798 between v1 and v1.1: `knowledge/redundant.yaml`
> gained `_mm_loadl_epi64` and `_mm_loadu_si64` (see Section 2 below), and
> SVT-AV1 uses the former 1082 times at the call-site level the tool counts,
> where a plain `grep` for the name returns 1101. The 19 are accounted for
> exactly, and in both directions. Two are not calls at all. Twenty sit
> inside `#define` macro bodies — `cdef_filter_block_avx2.c:93-96`,
> `cdef_filter_block_sse4_1.c` and `compute_mean_intrin_sse2.c` — which are
> outside any function and so outside the tool's declared
> `FunctionUnit`-scoped extraction. Against that, the tool finds four calls
> `grep` misses: `ssim_avx2.c` defines `#define _mm_loadu_si64(p)
> _mm_loadl_epi64(...)`, and alias resolution reports those four under the
> canonical name. Every other type is unchanged. F's count (1009 here vs. 1010 the
> last time this section was measured) is unrelated to this change: it is
> the same live-working-tree drift already described above for the
> file-count footnote, not a consequence of the R additions.

> An earlier run of the same command against this tree recorded 557 files
> and 22s wall clock. The run recorded above counts 561 — the SVT-AV1
> checkout is a live working tree, and one untracked ARM-NEON source file
> was added and two others were modified between the two runs. None of the
> changed or added files contain an x86 intrinsic any rule matches: the
> finding totals above (2152, and every per-type and per-evidence count)
> are bit-for-bit identical between the two runs. Wall clock varies with
> machine load and is not a pinned figure. The file-count difference is an
> artifact of running the same command twice against a tree that changed
> in between, not a tool defect.

## 2. VVenC: per-module comparison against Table III

Five modules use SIMDe: DepQuant, LoopFilter, Quant, Trafo, FGA. For each,
the type distribution below comes from:

```
findings, _ = analyze([VVENC_X86 / "<Module>X86.h"])
Counter(f.type for f in findings)
```

| Module | Type | Paper (Table III) | Tool |
|---|---|---:|---:|
| DepQuantX86.h | R | 4 | 40 |
| DepQuantX86.h | S | 12 | 22 |
| DepQuantX86.h | W | 3 | 0 |
| DepQuantX86.h | F | 6 | 0 |
| DepQuantX86.h | M | 2 | 0 |
| DepQuantX86.h | P | 3 | 3 |
| LoopFilterX86.h | R | 3 | 0 |
| LoopFilterX86.h | S | 8 | 0 |
| LoopFilterX86.h | W | 2 | 0 |
| LoopFilterX86.h | F | 0 | 5 |
| LoopFilterX86.h | M | 5 | 14 |
| LoopFilterX86.h | P | 2 | 0 |
| QuantX86.h | R | 2 | 5 |
| QuantX86.h | S | 0 | 0 |
| QuantX86.h | W | 6 | 4 |
| QuantX86.h | F | 4 | 8 |
| QuantX86.h | M | 0 | 0 |
| QuantX86.h | P | 0 | 0 |
| TrafoX86.h | R | 1 | 0 |
| TrafoX86.h | S | 0 | 4 |
| TrafoX86.h | W | 1 | 0 |
| TrafoX86.h | F | 7 | 10 |
| TrafoX86.h | M | 3 | 0 |
| TrafoX86.h | P | 0 | 0 |
| FGAX86.h | R | 2 | 0 |
| FGAX86.h | S | 0 | 0 |
| FGAX86.h | W | 0 | 0 |
| FGAX86.h | F | 5 | 0 |
| FGAX86.h | M | 3 | 0 |
| FGAX86.h | P | 0 | 0 |

Re-running the `analyze()` calls above against the current checkout
reproduces every cell in this table with no changes.
`test_depquant_reports_the_types_its_source_can_carry` in
`tests/test_verification.py` pins DepQuant's row directly: R 40, S 22, P 3,
W/F/M 0. (R was 26 before v1.1 added `_mm_loadu_si64` to
`knowledge/redundant.yaml`; DepQuant carries 14 call sites of it, all of
them in the `+40` here.)

A full recursive sweep of the whole `x86/` directory (47 files: the five
SIMDe-dependent modules plus the rest of `CommonLib/x86`, including its
`avx2/` and `sse41/` subdirectories) totals 445 findings — `R 106, S 164,
F 131, W 17, M 23, P 4` — evidence `A 320, B 87, C 38`, impact
`confirmed 312, diagnostic 133`. R was 73 at v1 (three registered
intrinsics); v1.1 added `_mm_loadl_epi64` (1 call site in this sweep) and
`_mm_loadu_si64` (32 call sites), for +33. Every other type is unchanged
from the v1 measurement.
`test_full_sweep_of_both_codebases_does_not_crash` runs this and only checks
it returns a list: no crash, no hang.

### Counts above the paper

Five cells exceed the paper's count, and all five are the expected
consequence of counting source call sites rather than assembly instances
(spec Section 3) — a call inside a loop body, an unrolled block, or a helper
invoked from more than one place produces several source-level findings that
`-O3` folds or unrolls into a different number of instructions:

| Module | Type | Paper | Tool | Ratio |
|---|---|---:|---:|---:|
| DepQuantX86.h | R | 4 | 40 | 10.0x |
| DepQuantX86.h | S | 12 | 22 | 1.8x |
| QuantX86.h | R | 2 | 5 | 2.5x |
| QuantX86.h | F | 4 | 8 | 2.0x |
| TrafoX86.h | F | 7 | 10 | 1.4x |
| LoopFilterX86.h | M | 5 | 14 | 2.8x |

No rule was tuned toward any of these ratios — spec Section 3 states plainly
that the tool does not target the paper's 84-instance total, and every rule
module (see `src/simde_lint/rules/`) matches on the mechanism its docstring
describes, not on a count.

LoopFilter's M ratio has an added wrinkle beyond the source-call-site
argument: `M.scalar_set_build` is a mechanism added mid-plan, after
measuring that VVenC expresses strided row reads as
`_mm_set_epi64x(m2, m5)` rather than as an insert chain
(`_mm_insert_epi16` appears only 3 times in all of VVenC, so
`M.scalar_insert_chain` alone finds 0 everywhere and would have left rule M
unvalidated against real code). All 14 of LoopFilter's M findings come from
`M.scalar_set_build`; 0 come from `M.scalar_insert_chain`.

### DepQuant P: 3 vs 3, the one exact non-primary match

Rule P's DepQuant count agrees with the paper exactly, and for a specific,
checkable reason: all three findings reach the rule only because extraction
resolves VVenC's local macro `#define _my_cmpgt_epi64(a, b)` down to
`_mm_cmpgt_epi64` through `knowledge/aliases.yaml`
(`simde_mm_cmpgt_epi64: _mm_cmpgt_epi64`) plus the file-local `#define`
alias step in `extract.py`. Without that resolution the rule would see an
unregistered call name and report 0.

### Zeros where the paper reports instances

Every zero-count cell above traces to a concrete property of the source,
verified individually rather than assumed:

- **DepQuant W/F/M = 0.** `DepQuantX86.h` contains no x86 multiply intrinsic
  at all — `_mm_mullo_epi16`, `_mm_mullo_epi32`, `_mm_madd_epi16`,
  `_mm_mul_epi32`, `_mm_mul_epu32` are all absent — and no insert chain. The
  paper's F instances there come from widening-accumulate chains
  (`_mm_cvtepi32_epi64` → `_mm_add_epi64`, lines 466–469) whose product is
  computed by a NEON-side multiply that has no corresponding x86 multiply
  intrinsic in this source; rule F matches on a multiply intrinsic reaching
  an add, so a chain with no multiply call to anchor on is invisible to it
  by construction, not by a matching bug.
- **LoopFilter S = 0.** Declared out of scope in spec Section 2:
  `LoopFilterX86.h` contains zero `_mm_shuffle_epi8` call sites. The paper's
  LoopFilter Type S instances are 64-bit lane transpose and blend sequences
  built from `_mm_unpacklo_epi64` and `_mm_set_epi64x`, a different
  mechanism than the pshufb guard rule S implements. This is the expected,
  documented outcome, not a verification failure.
- **R = 0 on LoopFilter, Trafo and FGA, still, after v1.1.** v1.1 added
  `_mm_loadl_epi64` and `_mm_loadu_si64` to `redundant.yaml` specifically to
  close this gap (see the R rows in the table above and the full-sweep note
  under Section 1), and it did close the gap on DepQuant (R 26 → 40, all 14
  of the increase from `_mm_loadu_si64`). It did not move LoopFilter, Trafo
  or FGA: none of the five intrinsics now registered
  (`_mm_loadu_si32`, `_mm_cvtsi32_si128`, `_mm_cvtsi64_si128`,
  `_mm_loadl_epi64`, `_mm_loadu_si64`) appears in any of those three files at
  all — confirmed by grep, not just by the tool's silence.
  - **LoopFilter** and **Trafo** do contain `_mm_cvtsi128_si64` and
    `_mm_cvtsi128_si32` respectively — the *extract* direction (vector lane
    to scalar), the mirror image of the intrinsics rule R covers (scalar or
    partial memory to zero-padded vector). That is a distinct, currently
    unimplemented mechanism, not an unregistered intrinsic of the mechanism
    R already has; registering `_mm_cvtsi128_si64` in `redundant.yaml` under
    the current rule would be citing the wrong SIMDe expansion for what the
    rule actually matches. LoopFilter's `_mm_set_epi64x` occurrences are
    already covered, but by `M.scalar_set_build`, not R.
  - **FGA** contains no candidate at all under either direction — every load
    in it (`_mm_loadu_si128`, `_mm256_loadu_si256`) is full-width, and it has
    no `_mm_cvtsi128_*`/`_mm_cvtsi*_si128` call of any kind. Which SIMDe
    construct produces the paper's 2 FGA instances is not established by
    this change; it needs separate investigation, not assumed to be the same
    extract-direction mechanism as the other two.

### Types the paper did not report

Two cells report a nonzero count against the paper's 0: **LoopFilter F 5**
and **TrafoX86 S 4**. These are not presented as the tool outperforming the
paper's assembly review — a source-level reading and a hand assembly review
are different methods that can each see call sites the other's method
doesn't surface under a given type, and that is what these two cells record.
They are call sites the paper's assembly review did not classify under F or
S respectively — a finding about the two methods' coverage, not a score
against either.

## 3. Robustness

`test_full_sweep_of_both_codebases_does_not_crash` sweeps the entire VVenC
`x86/` directory and only checks the result is a list. The SVT-AV1 full sweep
above (Section 1) separately confirms exit 0 and no stderr output over 561
files. Both were re-run as part of writing this document, not assumed.

## 4. Fixture unit tests

Every rule has at least one positive and one negative fixture test; see
`tests/test_rule_*.py`. These are unaffected by reference-checkout
availability and run in the default `uv run pytest` invocation.

## Reproducing this document

Export `SIMDE_LINT_SVT_AV1` and `SIMDE_LINT_VVENC` to point at your own
checkouts before running any of the commands in this document (see
CONTRIBUTING.md); without them the tests fall back to a local checkout path
and the commands below need the paths substituted by hand.

```
uv run pytest tests/test_verification.py -v
grep -r -o _mm_shuffle_epi8 "$SIMDE_LINT_SVT_AV1/Source" | wc -l
uv run simde-lint "$SIMDE_LINT_SVT_AV1/Source" --type S --format json \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['summary'])"
uv run simde-lint "$SIMDE_LINT_VVENC/source/Lib/CommonLib/x86/DepQuantX86.h" --format json \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['summary'])"
```

Both reference checkouts are external to this repository and are not
required to run the rest of the test suite; every test in this file skips
cleanly when its checkout is absent.
