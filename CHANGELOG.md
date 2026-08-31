# Changelog

## Unreleased

### Fixed

- **A call buried in a value-transforming expression was still read as its
  binding target's direct producer.** `_enclosing_result_var` and
  `_enclosing_result_lvalue` stopped only at `call_expression`,
  `init_declarator`, `assignment_expression` and `function_definition`, and
  crossed every other node silently. `x = _mm_mullo_epi32(a, b) ^ c` bound
  `x` to the multiply even though `x`'s actual value also depends on `c`;
  the same happened through a conditional's untaken branch, a comma
  expression's discarded first operand, a unary operator, and an
  `initializer_list` element bound to the whole array rather than to its own
  slot. Rules F and P read `result_var` to grade a def-use link at evidence
  A, so each of these asserted a direct identity link that never existed.
  The compound-assignment case #13 fixed is a special case of this one and
  stays fixed the same way, since a compound assignment is still an
  `assignment_expression` the walk still reaches.

  The walk is now inverted: only `parenthesized_expression` and
  `cast_expression` are transparent — the same set `_unwrap_cast` already
  treats as transparent for a plain assignment's right-hand side — and
  every other node terminates the walk with no binding, exactly as a nested
  `call_expression` already did.

  Across SVT-AV1 and VVenC, 608 and 79 call sites respectively lost a
  wrongly claimed direct binding (mostly `initializer_list`,
  `binary_expression` and `conditional_expression`), but none of them named
  an intrinsic any of F, P, W or M currently matches on — R and S never
  read `result_var` at all — so every published count is unchanged:
  SVT-AV1 3264 and VVenC 449, with identical per-rule and per-evidence
  breakdowns.

- **A compound assignment read its right-hand side as the target's direct
  producer.** `x += _mm_mullo_epi32(a, b)` recorded the multiply's
  `result_var` as `x`, so rules F and P treated `x` as the call's result and
  could report the def-use link at evidence A. `x`'s new value depends on
  its own old value as well as on the call, so the link is not direct and
  the grade asserted something untrue about the reader's code.

  Neither `result_var` nor `result_lvalue` now names the target of a
  compound assignment, and the write is instead recorded as an `UNKNOWN`
  definition, so `redefined_between` still sees the reassignment. Dropping
  the definition along with the wrong binding would have traded one false
  finding for another: rule F would link a multiply through a value the
  compound assignment had already overwritten.

  Neither reference corpus contains a compound assignment holding a current
  S, F, M or P anchor, so all published counts are unchanged.

## 2.1.0 — 2026-08-31

Minor rather than patch: `IntrinsicCall` gains a field, finding counts move
on a corpus users may already have measured, and a missing input now sets a
nonzero exit code where scripts previously saw success. Minor rather than
major: the JSON schema is unchanged, and every field v2.0.0 emitted is still
emitted.

**This is the release the paper's figures were measured on.** `v2.0.0`
predates the rule M fix below and reports `M.scalar_insert_chain` 24 against
this release's 27, and SVT-AV1 3261 against 3264. Cite this tag, not that one.

### Fixed

- **Rule M grouped an insert chain by variable name, merging chains that
  write to different array elements.** `dd[0]` and `dd[1]` are different
  vectors and a lane load replaces one of them, but `result_var` reduces
  both to `dd`, so two independent runs of two inserts counted as one run of
  four and cleared a threshold of three that neither reached. SVT-AV1's
  `pickrst_sse4.c` had three such findings.

  `IntrinsicCall` now carries `result_lvalue`, the assignment target as
  written, and rule M groups on that. `result_var` is unchanged and still
  means the identifier, because `redefined_between` tracks a variable rather
  than a place -- rules F, P and W keep their existing behaviour exactly.

  The fix also splits chains that genuinely were merged into the separate
  chains they always were, so the rule's count rises even as false positives
  go away: `M.scalar_insert_chain` 24 -> 27, SVT-AV1 total 3261 -> 3264,
  evidence B 49 -> 52. VVenC is unchanged.

  Found by `docs/precision/verify.py`.

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
