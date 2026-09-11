# Oracle corpus

Expected findings decided by reading the rule descriptions and the source,
before and independently of what the tool reports. `expected.yaml` is written
by hand. Nothing in this directory may be generated from tool output — that
would reproduce the failure it exists to catch.

The rest of the suite compares the tool against a second reading built from
the same inference: the fixture tests assert what the rule was written to do,
and `docs/precision/verify.py` re-implements each predicate. Both have missed
defects that shared their blind spot. `verify.py` could not see rule F's
nested multiply-add because its own predicate also required a named product,
and it had to be extended alongside the rule.

A hand-decided expectation does not copy the implementation's output, and can
fail independently of it. That is the property the rest of the evidence base
does not have, and it is all that is claimed: the same person reading the same
rule description with the same mental model can still reach the same wrong
answer the code did. Independence of *derivation* is not independence of
*assumption*, and `tests/acceptance.py` says so in its own output.

## Adding a case

1. Write the C file. Keep it small enough to reason about completely.
   Then read the line numbers off the file rather than counting them in
   your head — three of the first six expectations written here had the
   line wrong and nothing else, which is noise the oracle should not be
   spending its failures on.
2. Decide the expected findings from the codebook and the rule's stated
   mechanism. Do not run the tool first.
3. Add the entry to `expected.yaml`, with `why` naming the reasoning.
4. Run the suite. If the tool disagrees, decide which is wrong on the merits
   before changing either.

An empty `findings` list is a claim, not an omission: it says this file
contains no instance of any mechanism.

## What the runner guarantees

A corpus whose own vocabulary is unchecked can fail silently, which is the
failure it is here to prevent. Before the first of these tests existed, an
unrecognised key was skipped, so `evidance: A` was indistinguishable from a
satisfied `evidence` and four deliberate falsifications left the corpus green.

- **Only known keys.** `why`, `findings` and `covers` on a case; on a finding,
  `line`, `type`, `rule`, `rule_mechanism`, `evidence`, `reason`, `intrinsic`,
  `suggestion`, `simde_insns`, `native_insns`, `scope`, `macro`, `raw_name`,
  `rationale_includes`, `rationale_excludes`. Anything else fails.
- **Values of the right kind.** `line: "12"` can never hold and would fail
  forever as a disagreement with the tool rather than as a malformed
  expectation; `reason: guard-required` names a value no grade uses.
- **No repeated key.** PyYAML keeps the last one silently, which at case level
  would drop a whole case's expectations while every completeness test still
  passed.
- **Present-and-null is an assertion.** `suggestion:` with no value requires
  the tool to offer none. Omitting the key asserts nothing. Both of the
  faults in `tests/faults.yaml` about withheld costs are in that gap.
- **Matched, not zipped.** Expectations pair with findings that satisfy them,
  by maximum-cardinality matching. Sorting both sides needed a key both could
  compute, which `line` is not — it is optional, and where a mechanism anchors
  is not always something the contract fixes. First-fit is not enough either:
  a broad expectation would claim a finding a narrower one needed, and the
  narrow one would be reported as unmet.
- **Every field load-bearing.** Each asserted field is falsified one at a time
  and the comparison must notice. Six assertions have shipped here that could
  not fail; a passing test and a vacuous one look identical.
- **The count too.** Dropping any expectation, or inventing one, must fail —
  a rule that starts reporting one extra finding per call site is the failure
  mode this corpus was built for.
- **Attribution.** Every finding names the file that was scanned. True by
  construction today, which is a reason to check it: a finding is a chain of
  call sites and nothing forces the anchor into the file the scan began in.

## What the corpus deliberately does not assert

**Most of the instruction counts.** One case pins numbers: `shuffle_guard.c`
asserts 3 → 1, because `simde_mm_shuffle_epi8`'s AArch64 branch is a single
line — `vqtbl1q_s8(a, vandq_u8(b, vdupq_n_u8(0x8F)))` — whose two guard
operations a safe mask does not need. Nothing else does, because deciding a
number by hand otherwise means reading the tool's own knowledge table, and
reading a table is not independent validation of that table.

What every case decides is whether the counts exist at all — `costs:
reported`, `withheld`, or `partial` — because that follows from whether SIMDe
compiles the intrinsic to NEON or falls through to portable code, which is a
question the source answers directly. Against SIMDe 0.8.4:

| intrinsic | SIMDe source | NEON branch | `costs` |
| --- | --- | --- | --- |
| `_mm_shuffle_epi8` | `x86/ssse3.h:336` | `A64V8` → `vqtbl1q_s8` | reported |
| `_mm_insert_epi32` | `x86/sse4.1.h:1582` | `A32V7` → `vsetq_lane_s32` | reported |
| `_mm_set_epi32` | `x86/sse2.h:5720` | `A32V7` → `vld1q_s32` | reported |
| `_mm256_mullo_epi16` | `x86/avx2.h:4050` | none — portable loop | withheld |
| `_mm256_insert_epi64` | `x86/avx.h:4086` | none — scalar store | withheld |

Pinning the numbers needs the same citation carried further, into the complete
idiom each count covers. Until that exists, asserting them would import the
blind spot this corpus was built to avoid.

**Where a chain anchors.** `scalar_assembly.c` asserts no `line` for the insert
chain. Which call in a chain a finding attaches to is not fixed by the rule's
published description, so an expectation about it would pin an implementation
detail as if it were a contract.
