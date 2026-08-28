# Precision audit codebook

Fixed before drawing the sample. A finding is judged on **whether the
mechanism it names is actually present at that call site** — not on whether
the rewrite is safe, which is what the evidence grade already reports, and
not on whether a rewrite is worth doing, which is the maintainer's call.

## Verdicts

| Code | Meaning |
|---|---|
| **TP** | The named mechanism is present. The intrinsic is the one the rule claims, it sits in the structural shape the rule claims (a chain, a reaching add, an adjacent consumer), and SIMDe's expansion for it is the one the knowledge table cites. |
| **FP-shape** | The intrinsic is right but the structural claim is wrong — the "reaching add" does not consume the product, the insert chain is not same-target, the compare's consumer is not the next call, and so on. |
| **FP-context** | The structure is right but the call site is not one the mechanism applies to — for example the file is an x86-native path that never reaches SIMDe, or the code is unreachable. |
| **FP-knowledge** | The knowledge table's claim about SIMDe's expansion is wrong for this intrinsic. |
| **UNJUDGED** | Cannot decide from the source in the scanned tree. Recorded, never silently dropped. |

## Rules for the judge

- Read the actual source at `file:line` before deciding. The rationale string
  is the claim under test, not evidence for it.
- A grade-C finding can still be TP: "the tool cannot confirm the rewrite is
  safe" and "the mechanism is present" are different statements.
- `scope: macro` findings are judged against the macro body, not its
  expansions.
- When a verdict turns on SIMDe's expansion, check the cited
  `x86/<header>:<line>` rather than assuming.

## Sampling

Stratified by rule id, then by evidence grade within each rule, drawn with a
fixed seed from the pinned revisions. Strata smaller than the per-stratum
quota are taken whole.
