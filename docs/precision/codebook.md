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

## How it is applied

`verify.py` implements these tests and runs them over every finding in both
corpora. It imports none of the tool: it re-parses the sources and
reimplements each predicate from the rule's own description, so agreement
means two implementations reached the same answer.

- Read the actual source at `file:line`. The rationale string is the claim
  under test, not evidence for it.
- A grade-C finding can still be TP: "the tool cannot confirm the rewrite is
  safe" and "the mechanism is present" are different statements.
- `scope: macro` findings are judged against the macro body. `verify.py`
  does not reparse macro bodies -- doing so would rebuild the extractor it
  is checking -- so it reports them as unchecked rather than guessing.
- When a verdict turns on SIMDe's expansion, check the cited
  `x86/<header>:<line>` rather than assuming. `docs/verification.md` records
  that check for all 30 cost entries.

## What this codebook cannot decide

**FP-context is not structural.** Whether a call site is one the mechanism
applies to at all -- whether the file compiles on ARM through SIMDe rather
than being an x86-native path or dead code -- needs the build system, which
the tool deliberately does without and `verify.py` therefore also lacks. It
is a property of a file, not of a finding: `verify.py --files` lists the
distinct files so the question can be answered once per file.

**Neither side checks the parse.** Both read the same tree-sitter output, so
a defect in how the parser handles a construct is invisible to both at once.
The tool's unparsed-region diagnostics cover that; neither is the whole
claim alone.

## History

This codebook was fixed before the first sample was drawn and has not been
weakened since. Two sampled designs preceded the census and are kept, with
the reasons they were replaced, in `superseded/`.
