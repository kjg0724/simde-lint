# Changelog

## 2.3.4 — 2026-09-11

### Rule F stops naming an instruction that cannot be dropped in

The one behavioural change against `v2.3.3`. `git diff v2.3.3 v2.3.4 -- src`
touches four files and no rule but F.

`_mm_mul_epi32` products accumulated by `_mm_add_epi32` were reported at grade
**A** suggesting `vmlal_s32`, which accumulates into 64-bit lanes. The
accumulator there is 32, and `_mm_add_epi32` does not carry across the 32-bit
boundary while `vmlal_s32` does — so following the suggestion changes the
result. Five call sites in SVT-AV1, all grade A, the layer `--min-evidence A`
exists to isolate. VVenC and the VVdeC holdout have none.

The cost table maps a suggestion per intrinsic, so the multiply alone picked
it; which add the product reaches is what decides whether it can be used, and
nothing consulted that. `accumulator_lanes` now sits beside `suggestion` in
`knowledge/patterns.yaml`, required for every F entry the way
`transform_status` is — a `KeyError`, not a default, so an entry naming an
instruction without saying what it accumulates into cannot go unchecked.

The findings stay: the multiply-add is real and unfused. What is withdrawn is
the replacement — `suggestion` becomes null, both instruction counts are
withheld, and the grade drops to C with `reason: transform_width_mismatch`.

**Reported by the paper session against `v2.3.3`, with the source read by
hand.** Two of the five are `_mm_mul_epi32` + `_mm_add_epi32` where the
product is later re-widened by `_mm_srli_epi64`; one is `_mm_mullo_epi16`
against a 32-bit round constant, a deliberate mixed-width idiom.

### Why this tag exists

`v2.3.0`–`v2.3.3` differ from one another only in documentation and version
metadata, and the width defect above is present in all four. `v2.4.0` fixed it
— but `v2.4.0` was tagged on 2026-09-08 and `v2.3.3` on 2026-09-09, off
`v2.3.2`, so the later tag carries the lower version number **and not the
fix**. A reader comparing version numbers alone would draw the wrong
conclusion about which behaviour each tag has.

This release exists so that work citing the `v2.3.x` line has a tag with the
fix and nothing else. It is `v2.3.3` plus this change: no other rule, cost
table, or reported figure moves. Releases from `v2.4.0` on add capability
beyond that line — a nested multiply spelling for rule F, the single-precision
float family, control-region and consumer-selection corrections, and the
oracle corpus and verification machinery — and their figures are not
comparable to these.

### Figures

SVT-AV1 3272 findings, `F 1019, R 1816, S 341, M 64, P 31, W 1`, evidence
`A 840, B 60, C 2372`. Against `v2.3.1`–`v2.3.3`'s `A 845, B 60, C 2367`:
five findings move A to C, none appear or disappear, and every other published
figure is unchanged, gate 204 included.


Five claims that a citation pinned to `v2.3.2` would have carried:

- **`README.md`** said the paper "hand-reviewed GCC `-O3` assembly for five
  VVenC modules and the SVT-AV1 codebase to name six recurring patterns". The
  taxonomy comes from the five VVenC modules; SVT-AV1 enters as the
  transferability check that located 204 type-S call sites. Read beside the
  paper, the old sentence made one of the two wrong.
- **`docs/verification.md`** claimed the SVT-AV1 full sweep confirms "exit 0
  and no stderr output over 561 files". Section 1 of the same document records
  362 parse warnings on stderr and explains why their absence would be the
  surprise. The file count was right; the silence was not. Exit 0 is the claim
  that survives, and it is the one that matters -- a parse warning is not the
  tool erring.
- **`docs/verification.md`** introduced a six-row table with "Five cells
  exceed the paper's count, and all five are ...". Anyone tallying the rows
  against the paper's split comes up one short.
- **`docs/verification.md`** said "Every zero-count cell above traces to a
  concrete property of the source", and thirty-nine lines later said what
  produces the paper's 2 FGA instances "is not established". The completeness
  claim now states its own exception. This is the fourth instance of that
  class -- `v2.3.2` corrected three of them in `README.md` and this document.
- **`CITATION.cff`** still read `version: 2.3.1` at the `v2.3.2` tag. The bump
  reached `__init__.py` and `pyproject.toml` and stopped there.

The last one defeats the release check added for `v2.4.0`, which reads the
version out of the tool: `CITATION.cff` is a file the tool never loads. A test
asserting it against the package metadata belongs on `main`, not in a
documentation-only release, and is tracked there.

## 2.3.3 — 2026-09-09

Documentation only, on top of `v2.3.2`. `git diff v2.3.2 v2.3.3 -- src tests`
shows one line, the `__version__` constant. Every figure measured at `v2.3.1`
still holds -- re-run to confirm: SVT-AV1 3272 `A 845, B 60, C 2367`, VVenC
449 `A 101, B 87, C 261`, gate 204.

## 2.3.2 — 2026-09-08

Documentation only. `git diff v2.3.1 v2.3.2 -- src tests` shows exactly one
line, the `__version__` constant, as the `v2.3.0`-to-`v2.3.1` diff did before
it. No rule, table or test changed, and every figure measured at `v2.3.1`
holds here unchanged -- re-run to confirm rather than assumed: SVT-AV1 3272
`A 845, B 60, C 2367`.

(`v2.3.1`'s own entry called its `src/` tree byte-identical to `v2.3.0`'s. It
was not, for the same one line. A release whose metadata disagrees with its
tag is the failure `test_the_declared_version_matches_the_package_metadata`
exists to catch, so the constant has to move with the tag.)

Pinning a citation to a tag freezes that tag's documentation with it, and
`v2.3.1`'s had six claims that were wrong or had gone stale. A reader
following the citation into the repository would have found them.

- **`README.md`** said every divergence from the paper is traced to a
  specific cause. Not all are: Section 2's FGA `F` row is 5 in the paper and
  0 here with no cause recorded, and it is not the only one. The claim now
  says divergences are reported rather than hidden, and that some are not yet
  accounted for.
- **`README.md`** said rules with no source of uncertainty (R, P) always emit
  A. Rule R has graded C throughout since `v2.2.0` -- 1922 findings across
  both corpora, none of them A. Only rule P still qualifies.
- **`README.md`** said six rules run independently. There are seven: type M
  carries two. The same sentence was corrected in `docs/verification.md`
  before `v2.3.1` and missed here.
- **`docs/verification.md`** made the same completeness claim as the README
  ("with an established cause for each"), corrected the same way.
- **`docs/verification.md`** labelled this release's own figures as what
  `main` gives and `v2.2.0`'s as "the tagged release's output". Standing on
  the tag, that reads backwards. Each set is now named by the release it
  belongs to. The three-corpora reference line also mixed `v2.2.0`'s SVT-AV1
  total with this release's VVenC and VVdeC ones.
- **`CONTRIBUTING.md`** said grade C carries one of *two* `Reason` values and
  that `S.pshufb_guard` is the only rule emitting C. There are three reasons
  -- `TRANSFORM_REQUIRES_CONTEXT` is missing -- and rules S, R and F all emit
  C. It also offered a "default path" for the reference checkouts, which does
  not exist and deliberately never did.

Nothing here changes what the tool reports. The `main` branch has since moved
past these figures: rule F now reports a multiply written directly as the
add's argument, which raises SVT-AV1 to 3365 and VVenC to 593. That is
outside this tag by design.

## 2.3.1 — 2026-09-07

Same tool as `v2.3.0`: the `src/` tree is byte-identical and every figure
measured at that tag holds here. The one difference is `docs/verification.md`.

`v2.3.0` was tagged before the census re-run landed, so the document at that
tag still reads 3713 / 3681 and dates itself to v2.1.0, while the current
figures are 3721 / 3689. Anyone pinning a citation to `v2.3.0` and following
its verification document would get numbers that do not match what the tool
now reports -- which is the exact failure that document exists to prevent.

Tagged so a citation can point at a fixed revision whose verification
document matches the tool it ships with.

## 2.3.0 — 2026-09-07

### Note on version provenance

`__version__` stayed at `2.2.0` between that release and this one rather than
moving to a development suffix, so a report produced from `main` in that
interval identifies itself as `2.2.0` while carrying the corrections below.
The v2.2.0 entry said development would resume at the next `.dev0`, and that
did not happen.

Nothing published is affected -- the tagged v2.2.0 artefact reports 2.2.0 and
is what it says it is -- but a JSON report saved from an untagged `main`
during that window cannot be told apart from the release by its version
field. If you have one, the finding counts distinguish them: v2.2.0 gives
SVT-AV1 3264 with evidence A 2661, this release 3272 with A 845.

### Fixed

- **Rule R graded A while disclaiming the condition its transform depends
  on.** Every R finding carried evidence A -- the grade that says the rule
  resolved everything it depends on -- beside a rationale ending "removing
  the zero-init is safe only if the vector's unused lanes are dead in the
  code that consumes the result, which this rule does not establish". The
  rule never looks at the consumer, so the sentence was right and the grade
  was not.

  This was a deliberate choice rather than an oversight: the test carried the
  comment "R always grades A (evidence is purely structural)", leaving the
  caveat to the prose. A caveat the grade contradicts is not carried by prose.

  R now grades C with `transform_requires_context` -- not `guard_required`,
  which is for a guard the rule examined and found load-bearing, as rule S
  does with a mask lane provably out of range. R saw the call clearly and did
  not check a condition, which is the other reason. Both grade C, so only the
  reported reason differs, and the vocabulary exists so they are not
  interchangeable.

  **1816 SVT-AV1 and 106 VVenC findings move from A to C.** Totals and
  taxonomy-type counts do not change: SVT-AV1 stays 3264 and VVenC 449, with
  every type count identical. `docs/verification.md` keeps each tagged
  release's split as that release emitted it and records the current one
  beside it. The paper reports taxonomy-type counts, not the evidence
  distribution, so nothing in print is affected.

- **Rule R suggested the intrinsic its own note called wasteful.** Three of
  the five entries suggested `vsetq_lane_s32`/`vsetq_lane_s64` while the note
  identified `vsetq_lane_s32(a, vdupq_n_s32(0), 0)` as the redundancy -- the
  reader was told to write what SIMDe already writes. The other two named a
  lane load that still takes a destination vector, so it does not avoid the
  zero-init either.

  All five suggestions are withdrawn, and `native_insns` with them: only the
  replacement side was conditional, so `simde_insns` stays and the report now
  reads "SIMDe expansion: 2 instructions; replacement count unknown" rather
  than collapsing a known fact into "instruction count unknown". A bare
  `2 -> 1` restated in numbers the claim the withdrawn suggestion had made.

- **An invalid `--config` produced a report anyway.** A value of the wrong
  type raised inside rule M once per unit, after discovery and extraction had
  run, leaving a well-formed report with an empty findings list; a missing
  file or malformed JSON reached the user as a raw traceback with nothing on
  stdout under `--format json`. An unknown key and a negative threshold were
  accepted silently, so a typo'd config produced output identical to a
  correct run -- the worst of the four, because nothing distinguishes it from
  success.

  Rules now declare the options they accept as data -- name, type, default,
  minimum -- and `validate_config` checks a config against the union of those
  declarations before any file is opened. Rule M reads the validated value
  rather than parsing it again, so a validated config and an executed one
  cannot drift.

  Validation lives at the analysis boundary rather than in the CLI, because
  `analyze(config=...)` is a public entry point with the same exposure. The
  CLI keeps what is its own: reading the file and parsing its JSON, both now
  usage errors that exit 2 with one line and no traceback.

  An unknown key is an error rather than a warning. A version that quietly
  accepts an option it does not implement claims to have honoured a
  configuration it ignored; failing tells the reader to upgrade. `true` is
  not a threshold either -- `bool` is a subclass of `int` and is rejected.

- **Rule M chained inserts across code that cannot all run.** The IR ordered
  calls by byte offset and knew nothing about blocks, so two arms of an `if`
  read as one straight-line sequence. Four inserts split two-and-two across
  an `if`/`else` were reported as a chain of four — at evidence A, with the
  instruction counts summed over both arms — when the threshold is three and
  neither arm builds more than two. No execution path assembles that chain.

  A loop boundary is a weaker case and is split for a different reason.
  `pickrst_avx2.c:1900` reported "16 scalar inserts assemble dd[0]" where the
  source has twelve before a `while` and four inside it. That chain *can*
  execute — the outer run and the first iteration run consecutively — so the
  split is not a claim that it cannot. It is that this rule has no model of
  repetition: reporting one chain of sixteen states a cost that holds for one
  iteration count and no other, so a chain is confined to a single syntactic
  region instead.

  `IntrinsicCall` gains `control_region`, the identity of the innermost
  enclosing block, switch arm, or unbraced `if`/loop body. Rule M splits a
  chain wherever consecutive inserts disagree. Equality only — the field says
  which region a call is in, never which regions reach which, and reading
  nesting out of it would put back the control flow the parser never
  established. The field is unit-local and never serialized.

  This is fail-closed: consecutive nested blocks that would genuinely chain
  are split and their finding lost, which costs coverage. The alternative
  costs correctness.

  `M.scalar_insert_chain` rises from 27 to 35 on SVT-AV1, the total from 3264
  to 3272, and evidence B from 52 to 60. **The aggregate rises because
  thirteen findings were repartitioned into twenty-one region-local ones, not
  because coverage expanded** — no new call site is reported. All are in three
  files with the same shape, and every split was read against its source.
  Lengths of 16 disappear entirely (8 of them), replaced by the 12 + 4 and
  8 + 8 each site actually splits into.

- **Rule W suggested the low-half widening multiply whichever unpack
  consumed the round-trip.** `vmull_s16` rebuilds lanes 0-3 and
  `vmull_high_s16` lanes 4-7, but the suggestion came from the knowledge
  table, which can hold only one name. When the consumer was
  `_mm_unpackhi_epi16` the reader was handed the intrinsic that computes the
  other half.

  The rule now derives the suggestion from the unpack it matched, and the
  table's `suggestion` is gone rather than left holding an answer that is
  wrong half the time. `native_insns: 1` is unchanged and correct for both:
  the rule matches a single unpack, so four lanes of product are
  reconstructed either way and one widening multiply is the whole
  replacement -- only its name differs.

  Latent in both reference corpora: all 18 W findings consume
  `_mm_unpacklo_epi16`, so no published figure moves and the fixture added
  here is the only thing that exercises the high-half path.

- **The reporter attached one rule's condition to every rule sharing its
  reason.** The conditional-suggestion line hardcoded "before horizontal
  reduction", rule F's condition, for anything carrying
  `TRANSFORM_REQUIRES_CONTEXT`. Rule R inherited it on the change above and
  advised a horizontal reduction about zero-initialized lanes. The line is
  now generic and each rule states its own condition in its rationale, where
  the ownership already differs: F's comes from an adjudicated knowledge
  entry, R's is rule logic.

- **`README.md` and `CONTRIBUTING.md` declared evidence grades the code does
  not emit.** Both listed rule F as `{A, B}`; F emits C on 245 SVT-AV1 and
  117 VVenC findings, and `tests/test_evidence_conformance.py` -- the table
  CONTRIBUTING says enforces this -- already declared `{A, B, C}`. README
  also described the C case in prose three sections earlier. R's entry and
  the type table's "NEON alternative" column are corrected for the changes
  above.

## 2.2.0 — 2026-09-01

### Added

- **The JSON report did not say which version of the tool produced it.**
  `simde_version` names the SIMDe release the tool models, but nothing named
  `simde-lint` itself, and the two are not interchangeable: as 2.1.0's own
  entry below records, v2.0.0 and v2.1.0 disagree on rule M's count over the
  same corpus, so a detached report file gave a reader no way to tell which
  analysis semantics produced it. The document now leads with
  `simde_lint_version`, read from `simde_lint.__version__` at render time so
  it cannot drift from the field it names — an additive schema change; every
  key `--format json` already emitted is still emitted, in the same relative
  order. `--version` prints the same string and exits 0; the text format is
  untouched, since a header on every terminal report would be noise and
  would break existing snapshots and scripts.

  When version recording landed, at `a722b1d`, `__version__` and
  `pyproject.toml` advanced from `2.1.0` to `2.2.0.dev0`. Reporting `2.1.0`
  from a `main` that had already moved past that tag — by the two
  correctness fixes below, both of which were on `main` under the old
  version — would have manufactured, from a key whose whole purpose is
  answering "which version produced this", exactly the ambiguity the key
  exists to remove. Reports produced from `a722b1d` until this release
  therefore identify themselves as `2.2.0.dev0`, which is neither tagged
  release. Development after this one resumes at the next `.dev0`.

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
