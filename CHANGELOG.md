# Changelog

## Unreleased

### Added

- **A file that does not fully parse is now reported.** tree-sitter always
  returns a tree; when it cannot parse a construct it recovers, so the file
  still yields findings with no signal that any were lost. The unparsed line
  spans now appear as warnings on stderr and in `analyze()`'s third return
  value.

  This does not set the exit code, and `simde_lint.analyze.is_failure()`
  separates a genuine failure from an incomplete parse. Unparsed regions are
  the normal case on preprocessor-heavy C++ — 362 of SVT-AV1's 561 files at
  the pinned revision — so an exit code that counted them would be 1 on
  nearly every sweep.

  Found by sweeping a holdout codebase: on VVdeC `e493ce51`, recovery cost
  eleven registered-intrinsic call sites, every one past the point where a
  3398-line header stopped parsing. Recall for the two name-matched
  mechanisms there is 420 of 431, 97.4%, and all eleven misses have this one
  cause. See `docs/verification.md` §6.

- `extract_units_and_diagnostics()` returns units and unparsed spans from a
  single parse. `extract_units()` keeps its old signature and behaviour.

### Fixed

- **A missing or unreadable input now sets the exit code.** `simde-lint
  /path/that/moved` printed a warning and exited 0, so a sweep over a path
  that had gone away reported success with an empty report — the failure a
  script cannot see. The same held for a file that could not be opened, and
  for both under `--dump-symbols`.

  This is the other half of the contract the unparsed-file work was
  protecting. Recovery from a parse error must not escalate the exit code,
  because it is the normal case; an input that is not there must, because it
  is the tool failing to do what it was asked.

- **The precision census no longer credits a composition as a forward.**
  `docs/precision/verify_r.py` matched `#define`s with a regex over raw
  text, which accepted one written inside a block comment, and accepted
  `#define X(p) f(p) + g(p)` as forwarding to `f`. Definitions now come from
  the parse tree, bodies are reparsed and must be exactly one call, a name
  defined more than once is not resolved at all, and each finding is checked
  against the spelling it actually records rather than against any call on
  its line.

  The published figure does not change — 1904 of 1922, 99.06% — because the
  shapes it accepted wrongly forwarded to intrinsics rule R does not
  register. What changes is that the checker now establishes the number
  instead of happening to agree with it.

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
