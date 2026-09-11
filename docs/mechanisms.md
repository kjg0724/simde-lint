# Mechanism contract

**Version 1. Any change to this file changes what the tool claims, and the
figures in `docs/verification.md` move with it.**

What a rule matches is written in `README.md`'s table, for a reader deciding
whether to run the tool. This file answers the questions that table leaves
open and that an expectation cannot be written without: **what one finding
counts**, which intrinsic families are in scope, where detection stops, what
each field asserts, and whether two findings' costs may be added.

It exists because those answers were previously spread across a docstring, a
knowledge-table note and the implementation, and they did not all agree. Rule
W's module docstring says one thing about its counting unit and its code does
another (#66). An expectation written from the README and an expectation
written from the docstring disagreed, and nothing decided between them.

Where this file and the implementation disagree, **this file is the
specification and the implementation is the defect**. Each such case is named
below with its issue.

---

## What a finding is not

A finding names a call site whose SIMDe translation to NEON carries the named
inefficiency. It does **not** assert that an ARM build reaches that call site;
see Section 0 of `docs/verification.md`. Nothing in this contract changes that.

## Fields, and what each asserts

| field | asserts |
|---|---|
| `type` | the taxonomy type, one of R S W F M P |
| `rule` | which mechanism matched; type M has two |
| `line`, `file`, `function`/`macro` | where the rule anchors the finding — the anchor is named per mechanism below and is not always the first call in the sequence |
| `evidence` | how far the rule resolved its own premise, **and** what it will assert about the replacement. A fully resolved def-use path still grades C when the recorded instruction does not apply |
| `reason` | present exactly when `evidence` is C; absent otherwise |
| `intrinsic` | the anchoring call's normalized name; `raw_name` when it differed before alias resolution |
| `suggestion` | a NEON instruction the tool is willing to name, in the form that applies at this call site's register width. `null` means the tool will not name one, never that none exists |
| `simde_insns` | instructions SIMDe's expansion emits for the matched sequence. `null` when the expansion has no NEON branch, or leaves the count to the compiler |
| `native_insns` | instructions the named replacement emits. `null` whenever `suggestion` is `null` — the count belongs to the instruction |

**Costs are per finding and are not additive across findings that share a
matched call.** Two rule W findings over one multiply pair each report the cost
of the four lanes their own unpack rebuilds; summing them double-counts the
two multiplies. A total over a corpus is a count of findings, not a saving.

---

## R.zero_init_partial_load

- **Unit:** one call to a registered intrinsic. Nothing is grouped.
- **Families:** `_mm_loadu_si32`, `_mm_cvtsi32_si128`, `_mm_cvtsi64_si128`,
  `_mm_loadl_epi64`, `_mm_loadu_si64`.
- **Boundary:** the rule never inspects the consumer, so it cannot tell a live
  zero-init from a dead one.
- **Grade:** C always, `reason: transform_requires_context` — the zero-init is
  dead only for a consumer the rule does not look at.

## S.pshufb_guard

- **Unit:** one call to a registered shuffle.
- **Families:** `_mm_shuffle_epi8`, `_mm256_shuffle_epi8`.
- **Boundary:** transpose and blend sequences the paper also classes as type S
  are out of scope by decision, not oversight.
- **Grade:** A when every mask lane is known and within the range where pshufb
  and tbl agree; C with `guard_required` when a known lane falls outside it; C
  with `unresolved` when the mask cannot be read from source.

## W.mul16_widen_roundtrip

- **Unit: one consuming unpack.** A `mullo`/`mulhi` pair feeding both
  `_mm_unpacklo_epi16` and `_mm_unpackhi_epi16` is **two** findings. The unit
  is what the unpack reconstructs — four lanes, replaced by one widening
  multiply — which is why `suggestion` depends on which unpack matched
  (`vmull_s16` low, `vmull_high_s16` high) and why the cost is 5 -> 1 per
  finding rather than for the whole idiom.
- **Anchor:** the low multiply.
- **Families:** `_mm_mullo_epi16` + `_mm_mulhi_epi16` over operands equal as
  written, consumed by `_mm_unpacklo_epi16`/`_mm_unpackhi_epi16`. 128-bit only.
- **Boundary:** other missing-widening-multiply shapes, including 32-bit lanes
  and operands flowing across functions.
- **Costs:** 5 -> 1 per finding, and not additive across the two findings of a
  full eight-lane rebuild.

## F.mul_add_no_fuse

- **Unit: one add.** An add is one fusion opportunity, so two products
  reaching one add is one finding, and one product reaching two adds is one
  finding per add — each add is its own opportunity.
- **Anchor:** the multiply.
- **Families:** `mullo_epi16/epi32`, `madd_epi16`, `mul_epi32`, `mul_ps` at 128
  and 256 bits, reaching an `add_epi16/epi32/epi64/ps` of matching element kind
  and lane width, directly, as the add's own operand, or through one widening
  conversion.
- **Boundary:** more than one conversion between them; a product with no x86
  multiply intrinsic to anchor on.
- **Grade:** A for a direct path, B through a widening hop, capped to C by the
  entry's `transform_status`: `conditional` -> `transform_requires_context`,
  `changes_result` -> `transform_changes_result`, `unknown` -> `unresolved`.
  Capped to C with `transform_width_mismatch` when the recorded instruction's
  accumulator does not match the add's element kind and lane width.
- **Suggestion:** withdrawn — with `native_insns` — on a width mismatch. Named
  but qualified when it is not an exact substitution.

## M.scalar_insert_chain

- **Unit:** one chain. A run of inserts on one target within one control
  region, at or above `memory_chain_threshold` (default 3), is one finding
  however long it is.
- **Target identity:** the lvalue as written. `dd[0]` and `dd[1]` are different
  places; merging them once produced three false positives.
- **Chain, not consecutive statements:** an insert on another target does not
  end the chain. What ends it is the region closing, or the target being
  assigned by something that is not an insert.
- **Families:** `_mm_insert_epi16/epi32/epi64`, `_mm256_insert_epi16/epi32/epi64`.
- **Boundary:** the `_mm_cvtsi32_si128`-plus-unpack variant; stride-pointer
  loop forms.

## M.scalar_set_build

- **Unit:** one `set` call.
- **Families:** `_mm_set_epi64x`, `_mm_set_epi32`, `_mm_set_epi16`. Calls whose
  arguments are all literals are excluded as constant vectors.
- **Boundary:** the rest of the `set`/`setr` families; where the scalars came
  from.

## P.cmp_immediate_use

- **Unit:** one compare.
- **Families:** `cmpgt_*`/`cmpeq_*` as registered, macro aliases included.
- **Boundary:** adjacency in source text among *recognized* calls. Source order
  is a documented approximation of scheduling order along one path; it says
  nothing across arms of an `if`.
- **Grade:** A always.

---

## Relations every rule shares

**Two calls can both run on one pass** unless some `if` or `switch` encloses
both and they sit in different arms of it. Nesting, sequential sibling blocks
and independent conditionals can all run together. Rules F, W and P require
this of a producer and its consumer.

Rule M requires something stronger and different: every link of a chain in
**one** region, compared by equality. The two must not be conflated — doing so
cost six real findings.

**A macro-resolved consumer is abstained from.** Where a consumer's spelling
came from a file-local `#define`, its recorded arguments are the call site's
own with no mapping back through the macro body, so membership claims about
them are not supported. A `simde_`-prefixed name resolved through
`knowledge/aliases.yaml` is exact and does not abstain.

## Open against this contract

Nothing. The two divergences this file was written with — rule W reporting one
finding where the unit is the consuming unpack (#66), and rule F reporting one
for a product reaching two adds (#68) — are closed.

`docs/precision/recall_widening.py` was brought to the same unit in the same
change. It had taken one consumer per pair, matching the implementation rather
than the contract, so its agreement preserved the omission instead of exposing
it. An enumerator written from the README row and a rule written from its own
docstring are two readings of different documents; this file is the one both
now read.
