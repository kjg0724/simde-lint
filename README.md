# simde-lint

`simde-lint` reads C/C++ source that uses x86 SIMD intrinsics translated to
ARM NEON through [SIMDe](https://github.com/simd-everywhere/simde), finds
call sites matching a six-type inefficiency taxonomy, and reports them with
file, line, rationale, and an instruction-count estimate — so a maintainer
can decide where a native NEON implementation is worth writing.

The taxonomy comes from J. Kim, "A Taxonomy of SIMDe Emulation Inefficiencies
for ARM NEON Porting of VVC Encoders," *IEEE Computer Architecture Letters*,
2026, doi: [10.1109/LCA.2026.3725622](https://doi.org/10.1109/LCA.2026.3725622),
which hand-reviewed GCC `-O3` assembly for five VVenC modules and the SVT-AV1
codebase to name six recurring patterns. This tool automates a source-level
reading of the same patterns.
It is not a re-derivation of the paper's numbers — see
[`docs/verification.md`](docs/verification.md) for exactly where the two
agree, where they diverge, and why.

## What it detects

| Type | Name | What SIMDe does on this call | NEON alternative |
|---|---|---|---|
| **R** | Redundant | Zero-initializes a vector before a partial load | Load straight into the lane |
| **S** | Suboptimal | Guards a shuffle index for x86 semantics NEON doesn't share | Use the table lookup directly |
| **W** | Widening | Computes a 16-to-32 widening multiply as two separate ops plus an unpack | One widening multiply instruction |
| **F** | Fusion miss | Emits a multiply and its accumulate as two instructions | One fused multiply-accumulate |
| **M** | Memory | Assembles a vector from scalars instead of a structured load | A lane load or set of loads |
| **P** | Pipeline | Consumes a compare's result immediately, at use-to-use latency cost | Reorder independent work in between |

Each rule implements one **named mechanism** of its type — not the whole
type. The taxonomy types are broader than what v1 detects; the coverage
table below states exactly what each rule catches and what it deliberately
does not.

### Detect, not prove

The tool reports that SIMDe emits an inefficient sequence at a call site. It
does **not** claim the sequence is removable — that usually depends on
operand values the tool cannot always resolve from source alone. This is
reported separately as an **evidence grade**, so "found" and "confirmed
removable" are never conflated into one signal.

## Evidence grade and impact class

Every finding carries two independent axes:

- **`evidence`** — how far the rule's premise is confirmed from source.
  - **A** — every operand the rule depends on resolves to a known value or a
    direct identity link.
  - **B** — derived from a literal or a link, but through an intermediate
    operation, so the final value isn't pinned.
  - **C** — the rule cannot confirm the transform is safe from source alone.
    Grade C covers two different situations, distinguished on the finding
    by a structured `reason` field (`unresolved` or `guard_required`, not
    free prose):
    - **C-unresolved** — the rule could not see far enough to judge at all
      (a runtime-loaded value, a call result with unknown lanes, a symbol
      not defined in the scanned inputs). `reason: "unresolved"`.
    - **C-guard-required** — the rule saw everything relevant and confirmed
      the guard it's examining is load-bearing (rule S: a mask whose lanes
      are fully known but include one outside the safe range).
      `reason: "guard_required"`.

    Both share grade C because v1's action is identical either way: do not
    transform without human confirmation. A fourth grade would only be
    warranted if the two ever needed different `--min-evidence` filtering
    or other CLI/automation behaviour, which they do not today. `reason`
    is `null`/absent for grades A and B.

  Rules that have no source of uncertainty (R, P) always emit A; they still
  carry the field for JSON schema uniformity and consistent
  `--min-evidence` filtering.

- **`impact`** — taken directly from the paper's Table IV microbenchmarks
  (isolated kernel, Graviton3), not a computed score:
  - `confirmed` — S (1.59x), W (2.15x), F (1.94x)
  - `diagnostic` — R, M, P (1.00x in an isolated kernel; `-O3` neutralizes
    them there, so their value is in identifying porting candidates, not in
    a measured speedup)

A computed priority score was deliberately not built: weighting types
against each other would need VVenC-specific benchmark data, reproducing in
the tool the exact overfitting concern the paper itself was written against.

## Installation

Not yet published to PyPI. Install from a checkout:

```bash
git clone https://github.com/kjg0724/simde-lint.git
cd simde-lint
pip install -e .
```

Requires Python >= 3.10. Dependencies: `tree-sitter`, `tree-sitter-cpp`,
`PyYAML`.

## Usage

```bash
simde-lint path/to/source.c path/to/dir [--format text|json] [--type R,S,W,F,M,P]
           [--min-evidence A|B|C] [--impact confirmed|all] [--sort impact|file]
           [--exclude GLOB] [--config FILE] [--dump-symbols]
```

- `--type` filters to a comma-separated set of taxonomy types.
- `--min-evidence` is a floor, not an exact match: `B` keeps grades A and B.
- `--impact confirmed` keeps only the three types with a measured
  microbenchmark speedup.
- `--sort` picks the display order; both `--format` values honor it, so text
  and JSON output never disagree on order for the same run.
  - `impact` (default) — `confirmed` findings before `diagnostic`, then
    grade A before B before C, then file and line. On a large codebase, the
    diagnostic-impact rules (chiefly R) can outnumber everything else several
    times over; sorting by impact first means the findings worth acting on
    aren't buried under a scroll of ones `-O3` typically removes on its own.
  - `file` — the plain `(file, line, type, rule)` walk through the source
    tree, for a diff-friendly read.
- `--exclude` is repeatable and matches both the literal path and the
  root-relative tail, so `--exclude 'tests/*'` works regardless of whether
  the scan root was given as absolute or relative.
- `--config` is a JSON file for rule thresholds, currently
  `{"memory_chain_threshold": N}` for rule M's insert-chain length (default
  3).
- `--dump-symbols` prints the cross-file constant-array index the tool built
  and exits, for debugging why a mask did or didn't resolve.
- Exit code is 0 unless the tool itself errors — this is a reporting tool,
  not a CI gate (`--error-on-findings` is roadmap work, not v1).

### Example

Run against a fixture with several forms of the same shuffle-mask call:

```
$ simde-lint tests/fixtures/rules/suboptimal_positive.c --format text
tests/fixtures/rules/suboptimal_positive.c:7  S (pshufb->tbl guard only)  evidence=A  impact=confirmed
    _mm_shuffle_epi8 in kernel
    SIMDe 0.8.4 guards the tbl index on every call; inline mask lanes are all in [0,15] or 0xFF (x86/ssse3.h:346)
    suggestion: vqtbl1q_u8 (3 -> 1 instructions)

tests/fixtures/rules/suboptimal_positive.c:15  S (pshufb->tbl guard only)  evidence=B  impact=confirmed
    _mm_shuffle_epi8 in kernel
    SIMDe 0.8.4 guards the tbl index on every call; mask derives from a literal through _mm_blendv_epi8, so the final lane values are not pinned (x86/ssse3.h:346)
    no suggestion offered (instruction count unknown)

tests/fixtures/rules/suboptimal_positive.c:18  S (pshufb->tbl guard only)  evidence=C (unresolved)  impact=confirmed
    _mm_shuffle_epi8 in kernel
    SIMDe 0.8.4 guards the tbl index on every call; mask is produced by a call with unknown lanes (x86/ssse3.h:346)
    no suggestion offered (instruction count unknown)

tests/fixtures/rules/suboptimal_positive.c:25  S (pshufb->tbl guard only)  evidence=C (guard_required)  impact=confirmed
    _mm_shuffle_epi8 in unsafe_but_known
    SIMDe 0.8.4 guards the tbl index on every call; inline mask has a lane in the unsafe [16,127] middle range (x86/ssse3.h:346)
    no suggestion offered (instruction count unknown)

Summary: 8 findings
  S (pshufb->tbl guard only) [S.pshufb_guard]: 8
  evidence A: 3
  evidence B: 3
  evidence C: 2
```

(Four of the eight findings — the other local-constant, derived, and
table-indexed mask forms in the same fixture — are omitted above for length;
run the command yourself for all eight.) The mechanism annotation
`(pshufb->tbl guard only)` is mandatory on every line, in both text and JSON
output — a reader who saw only "Type S: 0" for a file with a different S
mechanism would wrongly conclude the tool fails to detect it, when only the
implemented mechanism is absent there.

The two grade-C lines above show why `reason` exists: line 18's mask is a
call result the rule cannot see the lanes of at all (`C (unresolved)`), and
line 25's mask is a fully-known inline literal with one lane the rule
confirmed sits outside the safe range (`C (guard_required)`) — a
categorically different kind of "cannot confirm safe" that plain `evidence=C`
would flatten into one.

`--format json` produces one object per finding plus a summary. This is a
real finding from an SVT-AV1 scan (paths shortened for display):

```json
{
  "type": "S",
  "rule": "S.pshufb_guard",
  "rule_mechanism": "pshufb->tbl guard only",
  "evidence": "A",
  "reason": null,
  "impact": "confirmed",
  "file": "Source/Lib/ASM_AVX2/intra_pred_intrin_avx2.c",
  "line": 617,
  "scope": "function",
  "function": "dr_prediction_z1_hxw_internal_avx2",
  "macro": null,
  "intrinsic": "_mm_shuffle_epi8",
  "rationale": "SIMDe 0.8.4 guards the tbl index on every call; mask resolved via even_odd_mask_x, all 8 row(s) have lanes in [0,15] or 0xFF (x86/ssse3.h:346)",
  "simde_insns": 3,
  "native_insns": 1,
  "suggestion": "vqtbl1q_u8",
  "mask_source": {
    "symbol": "even_odd_mask_x",
    "defined_at": "Source/Lib/Codec/intra_prediction.c:108",
    "resolution": "all_rows"
  }
}
```

`evidence` grade A never carries a `reason`, so it renders `null` here — see
"Evidence grade and impact class" above for what `reason` holds on grade C.

**`scope` says which kind of unit the call site sits in**, and `function` and
`macro` are mutually exclusive. A call written in a function body reports
`"scope": "function"` with the function's name in `function` and `macro`
`null`, as above. A call written in a `#define` body reports
`"scope": "macro"` with the macro's name in `macro` and `function` `null`.
All three keys are always present. The text reporter renders the two cases as
`_mm_shuffle_epi8 in dr_prediction_z1_hxw_internal_avx2` and
`_mm_loadl_epi64 in LOAD4_NAT (macro)`.

The `mask_source` field is present only for rule S findings graded through
`SymbolIndex`; it is omitted entirely (not `null`) on every other finding.
`raw_name` is likewise present only when a call's original spelling differs
from the resolved `intrinsic` name (a macro-aliased call site, e.g. VVenC's
`_my_cmpgt_epi64` resolving to `_mm_cmpgt_epi64`) — omitted, not `null`,
everywhere else.

**One location may produce multiple findings.** A code region can exhibit
several taxonomy types at once, and the paper says so explicitly. The six
rules run independently; their findings are never deduplicated, merged, or
reduced to one "primary" type.

## Per-rule mechanism coverage

| Rule id | Type | What it matches | Evidence grades | Impact | What it does not cover |
|---|---|---|---|---|---|
| `R.zero_init_partial_load` | R | Calls to the intrinsics registered in `knowledge/redundant.yaml` (`_mm_loadu_si32`, `_mm_cvtsi32_si128`, `_mm_cvtsi64_si128`, `_mm_loadl_epi64`, `_mm_loadu_si64`) | {A} always | diagnostic | Any other intrinsic whose SIMDe expansion begins with a redundant zero-init but isn't yet registered — this is knowledge-table coverage, the cheapest gap to close (see CONTRIBUTING.md) |
| `S.pshufb_guard` | S | `_mm_shuffle_epi8` and `_mm256_shuffle_epi8`, graded on whether the shuffle mask's lanes are known to be safe | {A, B, C} | confirmed | Transpose and blend sequences the paper also classes as Type S — an explicit v1 exclusion, not an oversight (VVenC's LoopFilter has zero `_mm_shuffle_epi8` sites and is exactly this case) |
| `W.mul16_widen_roundtrip` | W | `_mm_mullo_epi16` + `_mm_mulhi_epi16` over the same operands consumed by `_mm_unpacklo_epi16`/`_mm_unpackhi_epi16`, within one unit | {A, B} | confirmed | Any other missing-widening-multiply shape (e.g. 32-bit lanes, cross-function operand flow) |
| `F.mul_add_no_fuse` | F | `mullo`/`madd`/`mul_epi32` (128- and 256-bit) reaching an `add_epi32`/`add_epi64`, directly or through one widening conversion hop | {A, B} | confirmed | A multiply's product reaching two different adds (only the first is reported); widening-accumulate chains where the product itself has no x86 multiply intrinsic to anchor on (e.g. `_mm_cvtepi32_epi64` → `_mm_add_epi64` with no preceding multiply call) |
| `M.scalar_insert_chain` | M | A same-target chain of `_mm_insert_epi16/epi32/epi64`/`_mm256_insert_epi16` at or above a configurable threshold (default 3) | {A, B} | diagnostic | The `_mm_cvtsi32_si128` + unpack variant of the same mechanism; stride-pointer loop forms |
| `M.scalar_set_build` | M | `_mm_set_epi64x`/`_mm_set_epi32`/`_mm_set_epi16` assembling a vector from runtime scalars (all-literal calls excluded as constant vectors, not scalar assembly) | {A, B} | diagnostic | The remaining `set`/`setr` families beyond these three; dataflow reasoning about where the scalars originally came from |
| `P.cmp_immediate_use` | P | A `cmpgt_*`/`cmpeq_*` result (macro aliases included, e.g. VVenC's `_my_cmpgt_epi64`) consumed by the very next call in source order | {A} always | diagnostic | Anything beyond adjacency in source text — source order is an explicit, documented approximation of scheduling order, not a claim about compiler output |

Type M is the one taxonomy type with two implemented mechanisms in v1.
Report summaries group by rule id, not by bare type, so the two are never
collapsed into one line.

Cross-cutting limits that apply to every rule, not just one:

- **Detection unit is the source call site**, not the assembly instance the
  paper counted (spec Section 3). A loop body or a helper called from
  several places produces several findings where hand-reviewed `-O3`
  assembly might show fewer, folded or unrolled instructions. Rules are
  never tuned toward the paper's totals.
- **Def-use linking is confined to a single unit** — one function body, or
  one `#define` body. No interprocedural analysis, and no flow between a
  macro and the functions that expand it — that would need a build system,
  which is the exact dependency tree-sitter was chosen to avoid. Two units
  never share symbol state: a `tmp` in a macro and a `tmp` in a function are
  unrelated.
- **Every rule runs over macro bodies as well as function bodies**, since
  v1.2. A `#define` body is reparsed and analysed as its own unit, and a
  finding in one reports the macro's name with `"scope": "macro"`. Four
  limits come with it:
  - **Expansion sites are not analysed.** One intrinsic call in a macro body
    is one finding, however many times the macro is expanded — it is one
    place a maintainer would edit. Counting expansions would mean modelling
    the preprocessor.
  - **A body that does not reparse is skipped**, not guessed at from its
    text. Token pasting (`##`), stringification (`#`) and GNU statement
    expressions are the usual causes.
  - **Macro parameters are unresolved inputs.** A parameter reference has no
    definition inside the body, so it resolves conservatively: the grade
    drops and the instruction counts are withheld, exactly as for any other
    value a rule cannot see.
  - **A macro name defined more than once in a file yields one unit per
    definition, except definitions registered as forwarding aliases.**
    All `#if` branches are read. Whether a name registers at all is decided
    over the *whole set* of that name's definitions — every one of them
    must be a forwarding alias, resolve (following through other registered
    names, if the immediate callee is itself a macro) to the same target
    intrinsic, and compose to the same parameter-to-argument mapping.
    Registration and the resulting unit skip are then applied per
    *definition*, not per name: a genuinely different, multi-call `#if`
    branch sharing an alias-shaped sibling's name keeps its own unit, and so
    does every definition of a name whose branches disagree with each other
    — conflicting definitions are never merged, and none of them is then
    recognized as an intrinsic call at its use sites either. This comparison
    is over each definition's written token structure, not over macro
    expansion: two forwarding bodies that are textually identical are
    treated as agreeing even if one of them contains a further, separately
    `#if`-redefined object-like macro that would make the two expand
    differently at compile time. The token-structure comparison is a
    conservative, fail-closed approximation of C/C++ preprocessing-token
    lexing, not a complete implementation of it: anything it cannot lex
    costs a missed registration, never a wrong one — see
    `docs/verification.md`'s forwarding-alias section for what this
    currently covers and where the boundary sits.
- **The knowledge tables are small by design, not by accident.** Every entry
  in `knowledge/*.yaml` is read from the SIMDe source and cites the file and
  line it came from; nothing is guessed. Extending coverage means adding
  entries, not writing new matching logic — see CONTRIBUTING.md.
- **Counts are tied to SIMDe 0.8.4.** Every `simde_insns`/`native_insns`
  figure was read from that version's expansion; a newer SIMDe release could
  change the instruction count without changing whether the pattern exists.
- **The tool has no ARM build awareness.** It reports x86 intrinsic call
  sites in whatever files it's pointed at — it does not know whether a given
  file is actually compiled for the ARM/SIMDe path, an x86-native path, or
  dead code. Point it at the files you know are ARM-relevant.
- **A finding's grade depends on what was scanned in the same run, not just
  on the call site itself.** `SymbolIndex` — the table that lets rule S grade
  a runtime-indexed mask A when every row is safe (Section 6) — only covers
  the files given to that invocation. The same call site can grade A when the
  file defining its mask table is included in the scan and grade C (mask
  symbol not defined in the scanned inputs) when it's scanned alone. Scan a
  whole tree, or at least every file a mask symbol might be defined in, for
  grades that reflect what the source actually establishes.

## Verification

The design's completion criteria — an exact match against SVT-AV1's 204
known `_mm_shuffle_epi8` call sites, and a per-module comparison against the
CAL paper's Table III for five VVenC modules — are measured, re-run, and
recorded with the exact commands used in
[`docs/verification.md`](docs/verification.md). Every divergence from the
paper is traced to a specific cause: a broader detection unit, a knowledge
table that doesn't yet carry an intrinsic, a mechanism the rule doesn't
implement, or a call site the two methods classify differently. Absolute
count agreement with the paper is explicitly not the bar — the exact
`_mm_shuffle_epi8` count is.

That document also records what v1.2's macro-body support changed, measured
against the `v1.1.0` tag: the function-body findings are identical
finding-for-finding on both reference codebases, and the 32 macro-body
findings are reported as their own unit. They are call sites earlier versions
could not see, not a revision of any figure the paper reports.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for how to add an intrinsic to the
knowledge tables, add a rule, and run the test suite.

## License

MIT, matching SIMDe. See [`LICENSE`](LICENSE).
