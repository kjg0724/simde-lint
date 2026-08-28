# Changelog

## 2.0.0 — 2026-08-28

### Breaking

**The per-finding `impact` field is gone.** It was removed from `Finding`, from
the JSON output, and from the CLI.

| Removed | Replace with |
|---|---|
| `finding.impact` | `finding.type in BENCHMARK_BACKED_TYPES` (`{"S", "W", "F"}`) |
| JSON key `impact` | the finding's own `type` key |
| JSON key `by_impact` | `by_type`, summed over `S`, `W`, `F` |
| `--impact confirmed` | `--type S --type W --type F` |
| `--sort impact` | `--sort benchmarked` (same order) |
| `analyze(..., impact=...)` | `analyze(..., types=[...])` |

No information is lost: the value was a complete function of `type` — every
`S`, `W` and `F` finding carried `confirmed` and every `R`, `M` and `P`
finding carried `diagnostic` — so any consumer can reconstruct the old field
from `type` alone. It was removed because a per-finding column reads as a
claim about *this* call site's measured effect, and no measurement supports
that. The microbenchmark figures it was derived from are now a reference
table in the README, where they belong: they are a property of the taxonomy
type, measured on isolated kernels, not a prediction for a call site.

There is no deprecation window. If you need one, pin `simde-lint==1.2.0`.

### Fixed

- **Rule F no longer caps a finding at grade C for a missing instruction
  count.** The cap now asks only whether a fused NEON form is established.
  These are different facts, and conflating them buried real signal:
  `_mm256_mullo_epi32` has no NEON branch in SIMDe, so its cost cannot be
  read from the source, but the established 128-bit `vmlaq_s32` transform
  applies twice across its eight lanes. Its 275 SVT-AV1 findings now grade on
  the def-use link, with both instruction counts absent. The `madd_epi16`
  family is unaffected — its pairwise reduction has no established fused
  form, so it still caps at C.

  At the pinned revisions this moves SVT-AV1's evidence split from
  A 2386 / B 49 / C 826 to A 2661 / B 49 / C 551. Totals and type counts do
  not change, and VVenC does not change at all.

- `docs/precision/sample.py` read hardcoded absolute paths and ignored the
  sweep's exit status. It now takes `SIMDE_LINT_SVT_AV1` and
  `SIMDE_LINT_VVENC`, the same contract the verification tests use.

### Changed

- **The precision audit's allocation and interval.** Three findings per
  stratum could not support a population-level claim — the stratum holding
  51.8% of the findings contributed the same evidence as one holding three.
  Allocation is now 25 for strata of 100 or more, 5 or a census below.
  `docs/precision/estimate.py` replaces the pooled Wilson interval, which is
  not valid for an unequally allocated stratified sample and disagreed with
  the population-weighted point estimate, with per-stratum Wilson bounds at
  `alpha/H` combined under the population weights.

- CI runs the test suite on Linux and macOS across Python 3.10–3.13.

- README and `CITATION.cff` described the tool as detecting the six taxonomy
  types. It implements seven named mechanisms drawn from them — one per type,
  two for Type M — and both now say so.
