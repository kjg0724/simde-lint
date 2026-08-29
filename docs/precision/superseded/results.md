# Precision audit — results

Codebook fixed before sampling: [`codebook.md`](codebook.md).
Sample drawn by [`sample.py`](sample.py) (seed 17) from the pinned revisions
(SVT-AV1 `094b2a52`, VVenC `0f2e8744`). Verdicts in `verdicts.json`.

## What this measures

**Whether the mechanism a finding names is present at the call site it
names.** Not whether the rewrite is safe — the evidence grade reports that —
and not whether the tool finds everything, which §"What this does not
measure" below is explicit about.

## Result

36 findings, stratified 3 per (rule, evidence) stratum over 12 strata,
population 3710.

| Rule | Population | Sampled | TP | Precision |
|---|---:|---:|---:|---:|
| `R.zero_init_partial_load` | 1922 | 3 | 3 | 100% |
| `F.mul_add_no_fuse` | 1154 | 6 | 6 | 100% |
| `S.pshufb_guard` | 505 | 9 | 9 | 100% |
| `M.scalar_set_build` | 52 | 6 | 6 | 100% |
| `P.cmp_immediate_use` | 35 | 3 | 3 | 100% |
| `M.scalar_insert_chain` | 24 | 6 | 6 | 100% |
| `W.mul16_widen_roundtrip` | 18 | 3 | 3 | 100% |

**36/36 TP.** Population-weighted precision 100%, Wilson 95% CI
**90.4%–100%**. No FP, no UNJUDGED.

## Why the number is this high, and what it costs

Each rule matches a narrow structural shape over a small registered set of
intrinsics: a named intrinsic, a same-target insert chain, a product reaching
an add, a compare consumed by the next call. A rule that fires has already
matched a shape that is hard to be wrong about. **The price is recall**, and
the per-module comparison in `verification.md` shows it directly: VVenC's
LoopFilter has 8 Type~S instances in the published hand review and the tool
reports 0, because its S mechanism is `_mm_shuffle_epi8` and that module
contains none. Those are misses, and a precision audit cannot see them.

**High precision here is a claim about what the tool says, not about how much
it says.**

## Two things worth recording that are not false positives

**Grade conservatism (sample #29).** `padDmvr_SSE` at `InterPredX86.h:667`
shuffles through `sl = _mm_setr_epi8(0,1,2,3,4,5,4,5,8,9,10,11,12,13,14,15)` —
every lane pinned and every lane in `[0,15]`. The rule graded it B ("derives
from a literal through `_mm_setr_epi8`, so the final lane values are not
pinned") where A is justified: the literal tracer treats `set`/`setr` as an
intermediate operation rather than as a constructor. This under-claims, which
is the safe direction, but it means grade B currently mixes "genuinely
derived" (sample #30, through `_mm_blendv_epi8`) with "constructed by a
literal setter". Worth separating.

**Rule F on rounding adds (sample #4).** `_mm256_madd_epi16` reaching
`_mm256_add_epi32(v0, rounding)` was judged TP: the accumulator being a
constant does not disqualify the shape, since a fused multiply-accumulate
takes the accumulator as an operand. The finding is graded C in any case,
because no fused form is established for `madd_epi16`.

## Limitations of this audit

- **One judge, who is the tool's author.** No second coder and no blinding.
  The codebook was fixed before the sample was drawn, and the sample, the
  verdicts and the commands are all in this directory so the judgement can be
  re-run by someone else — but that is reproducibility, not independence.
- **Precision only.** Recall is not estimated here. The per-module table in
  `verification.md` is the closest available evidence and it is not a recall
  measurement either.
- **Three per stratum.** The CI lower bound of 90.4% is what 36 clean
  judgements support; it is not evidence that the rate is exactly 100%.
- **Two codebases**, both video codecs, both already used to derive the
  taxonomy.
