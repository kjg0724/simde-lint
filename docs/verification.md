# Verification against the reference codebases

This records the measurements behind the v1 completion criteria in the design
spec (Section 13): an exact match against SVT-AV1's known `_mm_shuffle_epi8`
count, and a per-module comparison against Table III of J. Kim, "A Taxonomy of
SIMDe Emulation Inefficiencies for ARM NEON Porting of VVC Encoders," *IEEE
Computer Architecture Letters*, 2026, doi:
[10.1109/LCA.2026.3725622](https://doi.org/10.1109/LCA.2026.3725622).

**Absolute agreement with the paper is not a criterion.** The paper counted
instances in GCC `-O3` assembly; this tool counts source call sites (spec
Section 3), a different and larger unit. Divergences below are recorded as
results, with an established cause for each — not smoothed over and not
treated as failures.

**The reference checkouts are pinned.** Every figure below was measured
against these exact revisions; a different checkout will give different
counts, and the file-count footnotes in Section 1 record a case where it did.

| Codebase | Commit | Date |
|---|---|---|
| SVT-AV1 | `094b2a5262c465c60c33fd4e7e0c79a0aa564a32` | 2026-08-18 |
| VVenC | `0f2e874451d6b194615e5dfefdc96796a7da00f4` | 2026-08-11 |

Every command in this document was re-run on the day this file was last
updated (v1.2: intrinsic calls inside `#define` bodies are analysed; see
Section 5). Reference checkouts are given through the `SIMDE_LINT_SVT_AV1`
and `SIMDE_LINT_VVENC` environment variables (see CONTRIBUTING.md); the
checkout-dependent tests skip cleanly when they are unset, the same as for a
contributor with neither clone.

**Two counting units appear below and are never mixed.** Sections 1 and 2
count call sites inside function bodies, which is what every measurement
before v1.2 counted and what the per-module comparison against the paper
rests on. Section 5 counts call sites inside macro bodies — a unit that did
not exist in any earlier release. Macro findings are reported separately
everywhere in this document; they are not added to a paper figure, not
subtracted from one, and not lined up against one.

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
'by_evidence': {'A': 35, 'C': 306}}
```

341 is the combined total of both shuffle widths rule S matches. Filtering
the tool's own findings to `_mm_shuffle_epi8` alone and comparing against the
grep count directly:

```python
findings, _, _ = analyze([SVT_AV1], types=["S"])
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

findings, _, _ = analyze([Path(os.environ["SIMDE_LINT_SVT_AV1"]) / "Source"], types=["S"])
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
uv run simde-lint ... 14.55s user 0.23s system 96% cpu 15.307 total
$ echo $?
0
```

561 files scanned (all `.c`/`.h` under `Source/`), exit 0.

**stderr carries 362 warnings, and that is the expected state.** Each names
a file tree-sitter could not fully parse; 362 of the 561 files contain an
`ERROR` node. Recovery is why they still produce findings, and §6 measures
what recovery can cost. A reader running the command above should see those
362 lines — their absence would be the surprise, not their presence. No
warning here is a failure: the exit code stays 0 because a parse error is
not the tool erring.
3261 total findings: `F 1019, R 1816, S 341, M 53, P 31, W 1`. Evidence
`A 2661, B 49, C 551`.

> The evidence split moved twice while the type split did not, and the call
> sites never changed — only what the tool is willing to claim about them.
>
> v1.3 introduced rule F's grade cap: a finding drops to C
> (`reason: unresolved`) when the knowledge table records no established
> fused form for the intrinsic. That moved 520 SVT-AV1 findings from A to C,
> giving `A 2386, B 49, C 826`.
>
> v2.0.0 narrowed the cap's predicate. It had asked
> `native_insns is None or suggestion is None`, which conflates whether a
> fused form exists with whether SIMDe's expansion can be counted; it now
> asks only the first. `_mm256_mullo_epi32` is the case that separates them:
> SIMDe has no NEON branch for it, so no count can be read from the source,
> but `mullo_epi32` does not widen and the established 128-bit `vmlaq_s32`
> transform applies twice across its eight lanes. Its 275 findings returned
> to grading on the def-use link, with both counts absent, leaving
> `A 2661, B 49, C 551` and rule F's grade-C set at 245 — every one of them
> a `madd_epi16` call, whose pairwise reduction has no direct AArch64
> equivalent and so remains capped. By scope: **3233 in function bodies, 28 in macro
bodies** — the 3233 is the same figure v1.1.0 reported, unchanged
finding-for-finding (Section 5).

> R rose from 716 to 1798 between v1 and v1.1: `knowledge/redundant.yaml`
> gained `_mm_loadl_epi64` and `_mm_loadu_si64` (see Section 2 below), and
> SVT-AV1 uses the former 1082 times at the call-site level the tool counts,
> where a plain `grep` for the name returns 1101. The 19 reconcile exactly,
> and in both directions:
>
> | | count |
> |---|---|
> | `grep -ro` occurrences | 1101 |
> | prose mentions inside comments, not code at all | −2 |
> | calls inside `#define` macro bodies | −12 |
> | calls inside commented-out code | −8 |
> | the alias definition line itself | −1 |
> | calls reached only through alias resolution | +4 |
> | **tool, v1.1.0** | **1082** |
> | macro-body calls, now analysed (v1.2) | +12 |
> | **tool, v1.2** | **1094** |
>
> The macro-body calls are in `cdef_filter_block_avx2.c:93-96,102-105` and
> `cdef_filter_block_sse4_1.c:68-69,476-477`; they sit outside any function
> and so were outside v1.1's `FunctionUnit`-scoped extraction. v1.2 reports
> all twelve, at exactly those lines, as macro-scoped findings in
> `LOAD4_NAT`, `LOAD4_ORD`, `LOAD2_S` and `BND_LOAD8` — the four macros this
> footnote named before the tool could see into them. The
> commented-out calls are in `compute_mean_intrin_sse2.c`, where earlier
> variants of live lines were left in place. In the other direction,
> `ssim_avx2.c:20` defines `#define _mm_loadu_si64(p) _mm_loadl_epi64(...)`:
> `grep` counts that definition as an occurrence but cannot see the four
> call sites that use the alias, while the tool does the reverse. Every other
> type is unchanged. F's count (1009 in function bodies here vs. 1010 the
> last time this section was measured) is unrelated to this change: it is
> the same live-working-tree drift already described above for the
> file-count footnote, not a consequence of the R additions. The `F 1019`
> and `R 1816` printed above are those function-body counts plus the 10 F
> and 18 R findings v1.2 reports inside macro bodies (Section 5).

> **The sweep is deterministic.** The command above was run twice in
> succession against this checkout and the two JSON outputs are identical
> byte for byte (`cmp` reports no difference), so every count in this section
> reproduces exactly. Both runs saw 561 files:
>
> ```
> $ find "$SIMDE_LINT_SVT_AV1/Source" -type f \
>     \( -name '*.c' -o -name '*.cc' -o -name '*.cpp' -o -name '*.cxx' \
>        -o -name '*.h' -o -name '*.hpp' -o -name '*.hxx' \) | wc -l
> 561
> ```
>
> Wall clock is the one figure that does vary — 14.9s and 18.6s total for the
> two runs — because it tracks machine load. It is not a pinned number.
>
> A v1-era note recorded here previously is worth keeping for what it warns
> about rather than for its figures: an earlier pair of runs disagreed on the
> file count (557 vs 561) because the SVT-AV1 checkout is a live working tree
> and files were added or modified between them, while the finding totals
> stayed identical. A file-count difference across two runs means the tree
> changed, not that the tool is nondeterministic.

## 2. VVenC: per-module comparison against Table III

Five modules use SIMDe: DepQuant, LoopFilter, Quant, Trafo, FGA. For each,
the type distribution below comes from:

```
findings, _, _ = analyze([VVENC_X86 / "<Module>X86.h"])
Counter(f.type for f in findings)
```

**The paper column was transcribed and then checked back against the paper's
own source**, cell by cell, along with the Table IV microbenchmark figures the
impact discussion quotes (S 1.59x, W 2.15x, F 1.94x; R/M/P 1.00x). All match.
Two notes from that check: the paper labels the fourth module TrQuant where
this table uses the header the tool scans (`TrafoX86.h`), and the paper
footnotes LoopFilter because its native implementation there was scalar C
rather than NEON — its taxonomy counts come from the same SIMDe-translated
x86 source as the other four modules.

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
`avx2/` and `sse41/` subdirectories) totals 449 findings — `R 106, S 164,
F 135, W 17, M 23, P 4` — evidence `A 207, B 87, C 155`. By scope: **445 in function bodies, 4 in
macro bodies**; the 445 and its per-type split (`F 131`, everything else as
printed) are v1.1.0's figures unchanged, and the 4 macro findings are all F,
in `AffineGradientSearchX86.h`, which is not one of the five modules in the
table above (Section 5). R was 73 at v1 (three registered
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

This reaches P through a confirmed forwarding alias whose target,
`_mm_cmpgt_epi64`, sits inside `pipeline._COMPARES` — §5's "The
forwarding-alias argument list" explains why that is sound rather than a gap
in the safety argument there. `_my_cmpgt_epi64` is the *producer* here, and P
decides by operand membership, not position or arity, so it cannot be misled
by however that particular alias forwards its own operands. That is the
whole of why this specific finding is sound — it says nothing about a
*consuming* call resolved through a file-local wrapper macro immediately
following a compare, which is a separate case P protects against a
different way: `PipelineRule.match` declines to read such a consumer's args
at all once `IntrinsicCall.is_macro_alias` is set on it, regardless of what
the registration predicate decided about it. It does *not* decline for a
consumer whose only change is a `knowledge/aliases.yaml` spelling
normalization (`simde_mm_shuffle_epi8` → `_mm_shuffle_epi8`, for instance) —
that case is not covered by `is_macro_alias` and does not need to be, since
no macro body sits between the call site and the resolved name. See §5 for
what the guard does and does not cover.

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

## 5. Macro bodies: what v1.2 added, measured against v1.1.0

v1.2 analyses intrinsic calls written inside `#define` bodies. Everything
below was measured by running both sweeps at the `v1.1.0` tag in a scratch
worktree and again at the v1.2 branch head, then comparing finding by
finding.

### The measured delta

| | v1.1.0 | v1.2 | delta |
|---|---:|---:|---:|
| SVT-AV1 `Source`, total | 3233 | 3261 | +28 |
| — in function bodies | 3233 | 3233 | 0 |
| — in macro bodies | — | 28 | +28 |
| VVenC `CommonLib/x86`, total | 445 | 449 | +4 |
| — in function bodies | 445 | 445 | 0 |
| — in macro bodies | — | 4 | +4 |
| rule S on `_mm_shuffle_epi8` in SVT-AV1 | 204 | 204 | 0 |

The function-body rows are not merely equal in count. Comparing the two JSON
sweeps as multisets over **every** field a finding carries — type, rule,
evidence, reason, impact, file, line, function, intrinsic, rationale,
`simde_insns`, `native_insns`, suggestion, and the optional `mask_source`
and `raw_name` — the v1.1.0 output and the function-scoped part of the v1.2
output are identical, on both codebases. The whole of the difference is the
new macro-body unit, plus the two new schema fields (`scope`, `macro`) that
every finding now carries.

This comparison was run when `impact` was still part of the schema, which is
why it appears in the field list above. The field was removed later, so the
comparison as written cannot be re-run against the current tool: re-running
it means dropping `impact` from the field set on both sides.

### Where the 32 macro findings are

They come from 15 macro units across 14 distinct macro names: 26 grade
evidence A, 6 grade C. The six are the `_mm_madd_epi16` call sites that rule
F's grade cap moves to C, for the same reason as anywhere else -- no fused
form is established for that intrinsic.

| codebase | file | macro | findings |
|---|---|---|---:|
| SVT-AV1 | `Lib/ASM_AVX2/cdef_filter_block_avx2.c` | `LOAD4_NAT` | 4 R |
| SVT-AV1 | `Lib/ASM_AVX2/cdef_filter_block_avx2.c` | `LOAD4_ORD` | 4 R |
| SVT-AV1 | `Lib/ASM_AVX2/cdef_filter_block_avx2.c` | `DEFINE_8XN_IMPL` | 2 R |
| SVT-AV1 | `Lib/ASM_SSE4_1/cdef_filter_block_sse4_1.c` | `BND_LOAD8` | 2 R |
| SVT-AV1 | `Lib/ASM_SSE4_1/cdef_filter_block_sse4_1.c` | `LOAD2_S` | 2 R |
| SVT-AV1 | `Lib/ASM_SSE4_1/cdef_filter_block_sse4_1.c` | `DEFINE_4XN_SSE4` | 2 R |
| SVT-AV1 | `Lib/ASM_SSE4_1/cdef_filter_block_sse4_1.c` | `DEFINE_8XN_SSE4` | 2 R |
| SVT-AV1 | `Lib/ASM_SSE2/av1_txfm_sse2.h` | `btf_16_sse2` | 4 F |
| SVT-AV1 | `Lib/ASM_SSE2/av1_txfm_sse2.h` | `btf_16_4p_sse2` | 2 F |
| SVT-AV1 | `Lib/ASM_SSE4_1/av1_txfm1d_sse4.h` | `btf_32_sse4_1_type0` | 1 F |
| SVT-AV1 | `Lib/ASM_SSE4_1/av1_txfm1d_sse4.h` | `btf_32_type0_sse4_1_new` | 1 F |
| SVT-AV1 | `Lib/ASM_SSE4_1/highbd_fwd_txfm_sse4.c` | `btf_32_type0_sse4_1_new` | 1 F |
| SVT-AV1 | `Lib/ASM_AVX2/highbd_fwd_txfm_avx2.c` | `btf_32_type0_avx2_new` | 1 F |
| VVenC | `Lib/CommonLib/x86/AffineGradientSearchX86.h` | `CALC_EQUAL_COEFF_8PXLS` | 2 F |
| VVenC | `Lib/CommonLib/x86/AffineGradientSearchX86.h` | `CALC_EQUAL_COEFF_8PXLS_AVX2` | 2 F |

By intrinsic: SVT-AV1's 18 R are `_mm_loadl_epi64` (12) and
`_mm_cvtsi32_si128` (6); its 10 F are `_mm_madd_epi16` (6),
`_mm_mullo_epi32` (3) and `_mm256_mullo_epi32` (1). VVenC's 4 F are
`_mm_mul_epi32` (2) and `_mm256_mul_epi32` (2).

**These 32 are not comparable to any figure in the paper, in either
direction.** They are call sites inside macro bodies that earlier versions of
this tool could not see, found by the same six rules that were already
running against function bodies. The paper counted assembly instances; a
macro-body call site is neither one of those nor a substitute for one, and no
row of the Table III comparison in Section 2 is affected by them — that
comparison's basis has not changed. Twelve of the 32 were, however, predicted
in this document before the tool could reach them: the v1.1 footnote under
Section 1 named `cdef_filter_block_avx2.c:93-96,102-105` and
`cdef_filter_block_sse4_1.c:68-69,476-477` as `_mm_loadl_epi64` call sites
`grep` saw and the tool did not. v1.2 reports exactly those lines.

### Per-task attribution of the delta

v1.2 landed as five changes. Measured at each one's final commit, with both
sweeps re-run:

| task | change | SVT-AV1 total | VVenC total | gate |
|---|---|---:|---:|---:|
| — | `v1.1.0` baseline | 3233 | 445 | 204 |
| 1 | def-use ordered by byte offset | 3233 | 445 | 204 |
| 2 | macro bodies reparsed | 3233 | 445 | 204 |
| 3 | strict forwarding-alias predicate | 3233 | 445 | 204 |
| 4 | macro bodies analysed | 3261 | 449 | 204 |
| 5 | `scope`/`macro` on every finding | 3261 | 449 | 204 |

**All of the movement is Task 4's.** Tasks 1 and 3 are corrections that
changed no count on these two codebases, and it is worth being precise about
why, because "no delta" is not the same as "no effect":

- **Task 1 (byte-offset ordering).** `definition_before` and
  `redefined_between` compared line numbers, so two definitions of the same
  variable on one physical line were unordered, and a self-assignment
  (`res = _mm_add_epi64(res, ...)`) could see its own result as an already
  available definition. The design spec counts 1619 same-line redefinition
  cases in existing SVT-AV1 function code and 350 in VVenC, so the wrong
  ordering was reachable; the sweeps say no rule's def-use query in this
  corpus landed on one, since the totals at Task 1's commit are unchanged in
  every category. The fix is also a precondition for Task 4: in a macro body
  every statement collapses onto one or two physical lines, so line-based
  ordering there is not merely imprecise, it is unusable.
- **Task 3 (strict alias predicate).** The old rule registered a macro as a
  forwarding alias for whichever identifier appeared first in its body. Over
  the two sweep directories, 37 macro definition sites were registered that
  way with a target that normalizes to a recognized intrinsic; 15 of those
  bodies contain more than one call, so the registration named an intrinsic
  the body merely mentions first. The strict predicate keeps 22 definition
  sites — exactly the 37 less those 15 — none with a multi-call body, which
  resolve to 16 distinct per-file alias entries (11 in SVT-AV1 `Source`, 5 in
  VVenC `CommonLib/x86`). Those are the v1.2 figures. Requiring every
  definition of a name to agree before it registers reduced them to 15
  entries (10 and 5): `MM256_BROADCASTSI128_SI256` has six definitions across
  compiler-version `#if` branches split between two targets, and no longer
  registers. **Which macros register as aliases changed; which
  findings fire did not** — the 15 removed misregistrations all pointed at names no
  rule anchors on (`_mm256_inserti128_si256`, `_mm256_castsi128_si256`,
  `_mm_unpacklo_epi64`, `_mm256_insertf128_si256`, `_mm_cvtsi128_si32`), so
  they produced no finding to remove. That is luck, not design, and
  `test_every_reported_intrinsic_is_a_name_the_knowledge_tables_recognize`
  in `tests/test_verification.py` now pins it: every finding's `intrinsic`
  must be a name the knowledge tables recognize, so a misattribution that
  lands on a future anchor fails the suite instead of being reported as a
  real call site.

Tasks 2 and 5 move nothing by construction and the table confirms it: Task 2
reparses macro bodies but nothing consumes the result until Task 4, and Task
5 adds report fields without touching a rule.

Task 3 is also what makes the macro path unambiguous. A body that passes the
predicate yields an alias entry and no unit; a body that fails it yields a
unit and no alias entry. Without that exclusivity a call site could be
counted once as a normalized alias call and again as a call inside the macro
body.

### Coverage and limits of macro-body analysis

Measured over the same two directories:

| | SVT-AV1 `Source` | VVenC `CommonLib/x86` |
|---|---:|---:|
| files scanned | 561 | 47 |
| function-like macro definitions | 685 | 11 |
| bodies that failed to reparse (skipped) | 181 | 0 |
| — of those, containing an `_mm*` call | 7 | 0 |
| confirmed forwarding-alias entries (name → intrinsic; these become no unit) | 11 | 5 |
| macro units built | 68 | 5 |
| macro units producing a finding | 13 | 2 |

The declared limits, all of them consequences of the design rather than
gaps to be closed later:

- **Expansion sites are not analysed.** One intrinsic call expression in a
  macro body is one finding, whatever the macro's expansion count. Four calls
  in a body are four findings because they are four places a maintainer would
  edit. Counting expansions would require modelling the preprocessor, which
  is the dependency the tree-sitter approach exists to avoid, and would make
  counts depend on how often a macro happens to be used.
- **A body that fails to reparse is skipped, not guessed at.** tree-sitter
  exposes a macro body as an opaque `preproc_arg`, so it is reparsed inside a
  synthetic function wrapper; if that parse reports an error the macro yields
  neither an alias entry nor a unit. Token pasting (`##`), stringification
  (`#`) and GNU statement expressions are the usual causes. 181 of SVT-AV1's
  685 bodies fail this way, but only 7 of the 181 contain an `_mm*` call at
  all — the rest are ordinary non-SIMD macros whose omission costs nothing.
- **Macro parameters are unresolved external inputs.** A parameter reference
  stays a `VARIABLE` with no in-unit definition, which the existing evidence
  rules already resolve conservatively: the grade drops and the instruction
  counts are withheld. No synthetic definition is created for a parameter,
  because any position chosen for it would misstate its availability against
  uses on the same line.
- **Symbol state is not shared between units.** A `tmp` in a macro and a
  `tmp` in a function are unrelated and neither satisfies the other's def-use
  query.
- **A macro name defined more than once in a file yields one unit per
  definition, except definitions registered as forwarding aliases.**
  VVenC's `RdCostX86.h` defines `UNPACKX` twice, in two separate `#ifdef
  USE_AVX2` blocks; both are read, as all `#if` branches are, and — since
  neither body is a forwarding alias — both become units of three calls
  each. Neither produces a finding today.

  Whether a name registers at all is a decision made over the *whole set*
  of that name's definitions, not per definition: every one of them must be
  a forwarding alias, must resolve — following through other already-
  registered names, when the immediate callee is itself a macro rather than
  a recognized intrinsic directly — to the same final target intrinsic, and
  must compose to the same parameter-to-argument mapping (each definition's
  own forwarded-call shape, with any intermediate macro's own forwarding
  substituted in). A different immediate callee name between two of a
  name's definitions is not itself disagreement, provided both routes
  resolve and compose to the same result; an intermediate that reorders or
  otherwise reshapes the operands it forwards is. Once a name registers,
  the resulting unit skip *is* applied per definition: every one of that
  name's own definitions is exempt from getting its own macro unit, and a
  same-named sibling that shares no relationship to a *different*,
  disagreeing name is unaffected.

  A name whose definitions disagree — a genuinely different multi-call
  `#if` branch sharing an alias-shaped sibling's name, or alias-shaped
  branches that resolve to different intrinsics or compose to different
  mappings — registers nothing: none of its definitions are skipped, and
  none of its call sites are recognized as the intrinsic either. SVT-AV1's
  `MM256_BROADCASTSI128_SI256` in `aom_subpixel_8t_intrin_avx2.c` is exactly
  this: six definitions across nested `#if`/`#elif` branches, forwarding to
  either `_mm_broadcastsi128_si256` or `_mm256_broadcastsi128_si256`
  depending on the branch — a genuine disagreement, previously collapsed
  into a single, arbitrary "last definition wins" registration before this
  fix (see the release notes' "Alias registration and the unit skip are now
  keyed per definition" for the underlying defect). Neither of that name's
  two possible targets is anchored by a rule, so this changes which macros
  register as aliases without moving any finding — the same shape as Task
  3 below.

  **One honesty boundary, stated rather than implied:** this comparison is
  over each definition's *written token structure* — string/character
  literal contents are opaque and never inspected, punctuators are lexed by
  longest match (`&&` is one token, never mistaken for two adjacent `&`
  tokens, and likewise for every other multi-character C/C++ punctuator,
  including C99 digraphs and C++-only forms such as `->*`, `::`, `<=>`),
  C++'s own `<::` exception is honored (`f<::N>` lexes as `f`, `<`, `::`,
  `N`, `>` — a qualified name — not as the `<:` digraph swallowing the
  first colon of `::`), a C++14 digit separator inside a numeric literal is
  read as part of the same pp-number token (`1'000`, `0x1'ff`) rather than
  mistaken for the start of a character literal, and every other token is
  compared byte-for-byte once whitespace, comments and backslash-newline
  continuations are normalized away — never over macro *expansion*. Two
  forwarding bodies whose written text is identical are treated as agreeing
  even if one of them contains a further, separately `#if`-redefined
  object-like macro that would make the two expand to different values at
  compile time; this module has no model of the preprocessor beyond the one
  function-like macro layer it reparses.

  This comparison also requires a macro's own declared variadic pack, not
  only its fixed parameters, to actually be written somewhere in the
  forwarded call: `#define BAD(...) _mm_set_epi32(0, 0, 0, 0)` declares a
  pack and throws it away, and is rejected as a forwarding alias for that
  reason, the same as a body that drops a fixed parameter. A pack that *is*
  written in the body but composes to zero tokens at a particular call site
  (`#define V(...) _mm_setzero_si128(__VA_ARGS__)` called as `V()`) is not
  this case — the pack is used, it just expands to nothing there.

  **This lexer is a conservative approximation of C/C++ preprocessing-token
  lexing, not a complete one, and that is a deliberate boundary, not an
  oversight.** It is a plain byte-level scanner over already-substituted
  argument text, independent of tree-sitter's own grammar, and it does not
  implement the full preprocessing-token grammar down to every corner case.
  What matters for this module's own soundness is which direction a gap
  fails in: every case this lexer cannot classify — an input `_tokenize`
  cannot get through cleanly — returns `None` and propagates as a hard
  failure (`_normalized_tokens`, `_call_shape`), which can only ever *cost*
  a registration, never grant one to definitions that do not actually
  agree. A gap here means a legitimate forwarding alias is missed and kept
  as its own ordinary unit — a coverage loss — not a misregistration. Wrong
  output (two genuinely different definitions judged to agree, as the `&&`
  vs `& &` and `<::` defects both were before their respective fixes)
  remains a blocking defect regardless of how obscure its trigger is; a
  fail-closed gap that neither reference corpus exercises is tracked as a
  known limit instead, on the same standing this project already applies to
  `A body that does not reparse is skipped` (README.md) and other
  fail-closed boundaries elsewhere in this module.

### The forwarding-alias argument list

A confirmed forwarding alias's call site presents the **alias macro's own**
argument list, not the forwarded intrinsic's. Nothing in the alias predicate
requires a body to pass its parameters through faithfully, and real macros do
not: of the **16 forwarding-alias definition sites** that register across the
two sweep directories — which resolve to 15 distinct per-file alias entries
(10 in SVT-AV1 `Source`, 5 in VVenC `CommonLib/x86`) — **10 forward
unfaithfully**. Two measured examples:

- SVT-AV1's `_mm256_setr_m128i(lo, hi)` forwards to
  `_mm256_set_m128i((hi), (lo))` — the two operands are reversed.
- SVT-AV1's `LOAD8_S(BASE, OFF, S)` forwards to an eight-argument
  `_mm256_setr_epi32`, so its call sites record arity 3.

No wrong output follows from this today, checked rather than assumed, for two
separately-checked reasons — one per group of rules, not one blanket claim:

- **S, M and W** read a call's own operand *position* (`call.args[1]`) or
  *arity* (`len(call.args)`), so they genuinely could be misled by an
  unfaithful forward — and none of the 22 confirmed alias targets is one of
  their anchors (`suboptimal._TARGETS | memory._SCALAR_SETS |
  memory._INSERTS | widening._UNPACK | {_mm_mullo_epi16, _mm_mulhi_epi16}`).
  `test_no_confirmed_alias_target_over_both_checkouts_reaches_an_operand_sensitive_anchor`
  in `tests/test_verification.py` checks this against both reference
  checkouts directly, over the real `reparse_macros`/`build_alias_map`
  machinery — not a hand-picked fixture — and fails if the intersection ever
  becomes non-empty.
  `tests/test_extract.py::test_confirmed_alias_targets_do_not_reach_an_operand_sensitive_rule_anchor`
  is the fast, fixture-based companion to that corpus test, over the same
  narrowed anchor union.
- **F and P never read a call's own args at all — as the producer.** Both
  decide by operand *membership* (`arg.text == result_var`): P checks
  whether a compare's result is a member of the *following* call's args, F
  checks whether a multiply's result is a member of a *following* add's
  args. An operand reversal or arity mismatch inside the *producer*
  alias's own body cannot change that judgment. §2's "DepQuant P: 3 vs 3"
  is this case: `_mm_cmpgt_epi64` is the confirmed target of VVenC's
  `_my_cmpgt_epi64`, a member of `pipeline._COMPARES`, and rule P's three
  DepQuant findings are sound because the compare's own operand order
  cannot affect whether its result is later consumed.
  `tests/test_rule_pipeline.py::test_verdict_is_invariant_to_how_the_alias_forwards_its_operands`
  and the equivalent test in `tests/test_rule_fusion.py` demonstrate this
  directly: a macro that forwards its operands faithfully and one that
  reverses them produce the identical verdict.

  **That was an incomplete argument on its own (P1).** Membership is read
  from the *following* call's args, and if that following call is itself a
  forwarding alias, its args are the call site's own — built from the
  macro's parameter positions, with no mapping back to which of the body's
  operands each parameter actually reached. A macro that *drops* a
  parameter's value (writes it in its own parameter list but never lets its
  value reach the forwarded call) therefore made a phantom operand look
  consumed. Two live false positives, not a latent risk, reproduced in
  `tests/test_rule_pipeline.py`/`tests/test_rule_fusion.py`:

  - `#define DROP_FIRST(a, b) _mm_add_epi32((b), (b))` called as
    `DROP_FIRST(cmp, x)` resolved to `_mm_add_epi32` with args `(cmp, x)`,
    and P reported `cmp` consumed even though the real `_mm_add_epi32(x,
    x)` never receives it.
  - `#define DROP_VALUE(a, b) _mm_add_epi32(((void)(a), (b)), (b))` called
    the same way produces the identical false positive by a subtler route:
    `a` (bound to `cmp`) *appears* in the argument subtree — inside a
    `(void)`-cast comma operand — so a text-appearance registration check
    still confirms the alias, even though a comma expression's value is its
    *last* operand and `(void)` explicitly discards the other. `(a) ^ (a)`
    is accepted by the same kind of check for the same reason: no syntactic
    rule distinguishes "combined with itself losslessly" from "genuinely
    used."

  An attempt to close this by tightening the registration predicate itself
  — rejecting an alias whose body never uses one of its parameters,
  measured against both checkouts — caught `DROP_FIRST` but not
  `DROP_VALUE`, because "appears in the subtree" is a text search, not a
  value-flow analysis. A value-flow-aware version of that predicate (skip a
  comma expression's non-final operand, a `(void)`-cast's operand, and
  either branch of a `conditional_expression`) closed `DROP_VALUE` but not
  `(a) ^ (a)`, which has no syntactic marker at all distinguishing it from
  a genuine use. Both attempts were approximations with a residual gap by
  construction, not a decreasing one — so the fix that shipped is not a
  registration change at all:

  **`PipelineRule.match` and `FusionRule._path` decline to read a consumer
  call's args at all once that call was resolved through a file-local
  `#define` wrapper macro**, unconditionally and regardless of what the
  registration predicate decided about that macro. This is sound for any
  corpus, not only these two, because it is enforced in the rule's own
  control flow rather than approximated from the alias's syntax — F and P
  make no operand claim about such a call rather than approximate one.
  `tests/test_rule_pipeline.py`/`tests/test_rule_fusion.py` reproduce both
  `DROP_VALUE` and `(a) ^ (a)` in both F and P shapes and confirm zero
  findings; each fails without the abstention.

  **The guard's first implementation tested `raw_name != name`, which is
  broader than "resolved through a macro" and cost a true positive for no
  soundness gain (P2).** `IntrinsicCall.raw_name` differs from `.name` for
  two distinct reasons that a name comparison alone cannot tell apart: a
  file-local wrapper macro (the risk above), and a direct call under its
  `simde_`-prefixed spelling, normalized through `knowledge/aliases.yaml`.
  The second carries none of the first's risk — SIMDe exposes every
  intrinsic under a `simde_` prefix with the identical signature to its
  native spelling by its own naming convention (`ssse3.h:388` is `#define
  _mm_shuffle_epi8(a, b) simde_mm_shuffle_epi8(a, b)`; `ssse3.h:336` is
  `simde_mm_shuffle_epi8(simde__m128i a, simde__m128i b)` — same arity,
  same order) — so there is no macro body for a parameter's value to be
  dropped, duplicated, or discarded in. Reproduced live: `_mm_cmpgt_epi64`
  followed directly by `simde_mm_shuffle_epi8(cmp, mask)` produced no P
  finding under the `raw_name != name` guard, while the identical code
  calling `_mm_shuffle_epi8` directly did.

  The fix moved the distinction to where the two resolutions are actually
  told apart — extraction, not the guard. `IntrinsicCall.is_macro_alias`
  (`ir.py`) is set at both `extract_units` call-construction sites
  (`extract.py`) from whether the call's `raw_name` is a key in the
  file-local `aliases` map `macros.build_alias_map` returns for that file;
  a `knowledge/aliases.yaml` normalization with no matching file-local
  macro leaves it `False`. All three consumption checks — `pipeline.py`'s
  direct consumer, and *both* of `fusion.py`'s paths, the direct add at
  `fusion.py:103` and the widening hop at `fusion.py:125` (easy to miss,
  since it guards the intermediate call rather than the add itself) — read
  this flag and nothing else.

  **This is a user-visible behaviour change, not a free fix.** A codebase
  whose F/P consumer call is itself resolved through a file-local wrapper
  macro will get fewer F/P findings under this tool than a version without
  the abstention would have produced — the tool declines the claim rather
  than approximating it. It does **not** lose a finding merely because the
  consumer is spelled with a `simde_` prefix; that case is recovered by
  this round's fix and confirmed by
  `tests/test_rule_pipeline.py`/`tests/test_rule_fusion.py`'s
  `simde_spelled_consumer`/`widening_simde_intermediate` tests, which
  assert the finding IS produced. Over both reference checkouts, the
  narrower guard costs nothing measurable and the P2 fix recovers nothing
  measurable either — not because the fix has no effect, but because
  neither shape occurs in either corpus: every P "compare consumed"
  candidate and F "multiply reaches an add" candidate actually realized in
  SVT-AV1 `Source` and VVenC `CommonLib/x86` has a consumer call that is
  neither a wrapper-macro alias nor a direct `simde_`-spelled call
  (`tests/test_verification.py::
  test_no_pipeline_or_fusion_finding_over_both_checkouts_has_a_macro_resolved_consumer`,
  which counts both categories separately and confirms both are zero). The
  finding-set diff over both full sweeps, before this round's fix and
  after, is empty: 0 lost, 0 gained, in either corpus.
  **That is a fact about these two corpora, not a bound on the general
  case** — a codebase where a compare's or a multiply's result flows
  through a wrapper macro before reaching its consumer would lose real
  findings here, and this tool has no way to recover them without reading
  through the wrapper, which is exactly the re-projection deferred below.

  The registration predicate (`macros.py`'s `is_forwarding_alias`) is
  unchanged from the naive "parameter name appears anywhere in the
  argument subtree" check: it is known-unsound (see `DROP_VALUE` above) and
  makes no claim this document or the test suite relies on for F/P. It
  still governs whether a macro is registered as an alias at all, which
  matters for the S/M/W anchor-disjointness property above and for the
  general correctness of a confirmed alias's recorded `call.args` beyond F
  and P.

See the release notes for why the underlying re-projection (making a forward
faithful, or reading through it) is deferred rather than fixed.

## 6. VVdeC: a holdout corpus, and the first recall measurement

Sections 1 and 2 measure the tool on the two codebases the taxonomy was
derived from. That cannot answer whether the rules generalize, and it cannot
answer recall at all. This section uses a third codebase that took no part in
the derivation.

**Corpus.** Fraunhofer VVdeC at `e493ce51f13a2dea72cd58354652ed4e0f509a0e`,
`source/Lib/CommonLib/x86` — 59 files. It vendors SIMDe and includes it
directly (`#include <simde/x86/sse4.1.h>`), so its x86 intrinsic paths are
what actually compiles on ARM, which is the precondition for a finding to
mean anything.

Two caveats belong here rather than in a footnote. VVdeC is a **weak**
holdout: it is the same organization as VVenC and both descend from VTM, so
it is independent of the derivation but not of the codebase family. And the
pinned revision's HEAD is a merge of a pull request from this tool's author
(an unrelated null-dereference fix), which is disclosed rather than
concealed.

```
$ uv run simde-lint "$VVDEC/source/Lib/CommonLib/x86" --format json
516 findings: R 224, S 196, F 77, W 9, M 8, P 2
$ echo $?
0
```

10 parse warnings on stderr, one per unparsable file. For reference across
all three corpora: SVT-AV1 3261 findings / 362 warnings, VVenC 449 / 11,
VVdeC 516 / 10 — every one exit 0.

All six taxonomy types fire on a codebase none of them were fitted to.

### Recall, for the mechanisms where ground truth is mechanical

Rules R and S match registered intrinsic names, so `grep` gives a ground
truth that needs no judgement: every occurrence of a registered name that is
not a definition is a call site the tool should report. Definitions are
excluded by the same rule in both directions — a `static inline` signature
or the left side of a `#define` is not a call.

| Intrinsic | Ground truth | Reported | Missed | Recall |
|---|---:|---:|---:|---:|
| `_mm_shuffle_epi8` | 120 | 115 | 5 | 95.8% |
| `_mm256_shuffle_epi8` | 84 | 81 | 3 | 96.4% |
| `_mm_loadu_si64` | 197 | 195 | 2 | 99.0% |
| `_mm_cvtsi32_si128` | 21 | 20 | 1 | 95.2% |
| `_mm_loadu_si32` | 8 | 8 | 0 | 100% |
| `_mm_loadl_epi64` | 1 | 1 | 0 | 100% |
| **Total** | **431** | **420** | **11** | **97.4%** |

This is recall for the two name-matched mechanisms only. F, M, W and P turn
on structure rather than a name, so their ground truth cannot be built by
`grep` and is not claimed here.

### Every miss has one cause, and it is not the rules

All eleven sit in `InterpolationFilterX86.h`, between lines 3145 and 3296.
The tool's findings in that file stop at line 3034 and resume nowhere; the
file is 3398 lines long.

tree-sitter returns a single `ERROR` node spanning the whole file. It always
returns a tree — when it cannot parse a construct it recovers — so the file
still produced 123 findings, and nothing in the output said the rest were
missing.

That is not specific to the holdout:

| Corpus | Files | Containing an `ERROR` node |
|---|---:|---:|
| SVT-AV1 `Source/` | 561 | 362 (64.5%) |
| VVenC `x86/` | 47 | 11 (23.4%) |
| VVdeC `x86/` | 59 | 10 (16.9%) |

Every figure in Sections 1 and 2 was computed over trees like these.
Recovery cost nothing measurable there — Section 1's rule-S gate still
matches `grep` exactly, 204 to 204 — but that is an observation about two
codebases, not a guarantee, and VVdeC is the counterexample that shows the
guarantee does not exist.

The tool now reports it. `analyze()` returns the unparsed line spans among
its warnings and the CLI prints them to stderr, so a reader sees which files
carry the risk instead of discovering it by grepping. It remains a warning
and not a skip: the file's other findings are real and are still reported.

### Rule R, checked as a census rather than a sample

Rule R has no structural premise -- it reports every call to one of five
registered intrinsics -- so whether a finding is a true positive reduces to
whether a real call stands at the reported line rather than a comment, a
string, or a definition. That needs no judgement, so
`docs/precision/verify_r.py` checks all 1922 of them instead of sampling.

The check imports no `simde_lint`. It re-parses with tree-sitter from
scratch and reuses neither the lexer, the extractor, nor the alias
resolution, because a checker sharing the implementation's assumptions
proves nothing about them.

```
$ uv run python3 docs/precision/verify_r.py
rule R findings checked: 1922 (census, not a sample)

  call        1898   98.8%
  macro         18    0.9%
  aliased        6    0.3%

confirmed true positives: 1904 / 1922 = 99.06%  (1898 direct, 6 through a local alias)
```

The six `aliased` are in `ssim_avx2.c`, which defines two forwarding macros
under `#ifndef` guards -- `_mm_loadu_si32` at line 17 and `_mm_loadu_si64`
at line 20. The checker resolves them with its own predicate: a `#define`
whose body is a single call, matched by one regex. It follows no chains and
does not check that the parameters are used, which is the point -- a wider
predicate would start to resemble what it is checking.

The 18 `macro` are calls written *inside* a `#define` body, and they
partition as:

| File | Findings | Macros |
|---|---:|---|
| `cdef_filter_block_avx2.c` | 10 | `LOAD4_NAT` 4, `LOAD4_ORD` 4, `DEFINE_8XN_IMPL` 2 |
| `cdef_filter_block_sse4_1.c` | 8 | `LOAD2_S` 2, `DEFINE_8XN_SSE4` 2, `DEFINE_4XN_SSE4` 2, `BND_LOAD8` 2 |

Confirming these means reparsing macro bodies the way `macros.py` does, and
a second macro extractor built to check the first would be exactly the
circularity this file avoids. They are listed rather than credited. The
census stopping where its independence would have to be spent is the honest
outcome, not a gap in it.

### A version claim that is not checked

The sweep above reports `simde_version: 0.8.4`. VVdeC vendors **0.8.3**. The
figure comes from the knowledge table's own header, not from the scanned
tree, so it describes the SIMDe the cost entries were read against and not
the SIMDe the target will actually compile with. On this corpus the cited
file and line numbers are therefore for a version the project does not use.
This is a real limitation, recorded here rather than fixed: detecting the
target's SIMDe version means finding and parsing its vendored copy, which is
build-system knowledge the tool deliberately does not have.

## Reproducing this document

Export `SIMDE_LINT_SVT_AV1` and `SIMDE_LINT_VVENC` to point at your own
checkouts before running any of the commands in this document (see
CONTRIBUTING.md); the commands below need the paths substituted by hand.

```
uv run pytest tests/test_verification.py -v
grep -r -o _mm_shuffle_epi8 "$SIMDE_LINT_SVT_AV1/Source" | wc -l
uv run simde-lint "$SIMDE_LINT_SVT_AV1/Source" --type S --format json \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['summary'])"
uv run simde-lint "$SIMDE_LINT_VVENC/source/Lib/CommonLib/x86/DepQuantX86.h" --format json \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['summary'])"
```

Section 5's scope split and macro attribution come from the full sweeps:

```
uv run simde-lint "$SIMDE_LINT_SVT_AV1/Source" --format json > svt.json
uv run simde-lint "$SIMDE_LINT_VVENC/source/Lib/CommonLib/x86" --format json > vvenc.json
python3 - <<'EOF'
import json
from collections import Counter

for label, path in [("SVT-AV1", "svt.json"), ("VVenC", "vvenc.json")]:
    findings = json.load(open(path))["findings"]
    macro = [f for f in findings if f["scope"] == "macro"]
    print(label, len(findings), Counter(f["scope"] for f in findings))
    print("  macro:", Counter((f["file"], f["macro"], f["type"]) for f in macro))
EOF
```

The v1.1.0 comparison in Section 5 was made by checking that tag out in a
separate worktree (`git worktree add <dir> v1.1.0`), running the same two
commands there, and diffing the two JSON outputs as multisets of findings
with `scope` and `macro` excluded from the comparison key — those two fields
do not exist in v1.1.0's output.

Both reference checkouts are external to this repository and are not
required to run the rest of the test suite; every test in this file skips
cleanly when its checkout is absent.
