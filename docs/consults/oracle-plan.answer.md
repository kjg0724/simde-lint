The strongest false claim is that hand-written expectations “cannot acquire the implementation’s blind spot.” They can share its author, interpretation, omitted cases, and mistaken counting unit. Writing expectations before running the tool prevents copying its output; it does not establish independent errors. Both the [oracle README](/Users/solario/Solario/Solido/open-source/simde-lint/tests/oracle/README.md:15) and [issue #48](https://github.com/kjg0724/simde-lint/issues/48) make that stronger, unsupported claim.

There are also concrete discrepancies on `main` at `575380f`:

- There are **eight oracle case files**, not nine. All seven rules are represented, but the claimed positive/negative arrangement is not universal: S’s two shapes are both findings, distinguished by grade.
- The oracle cannot check `simde_insns` or `native_insns`: neither is an allowed expectation field. Several expectations also omit grades, reasons, or positions. It therefore does not yet implement the output contract #48 requests.
- The neighbouring-shape problem remains after the nesting fix. In an in-memory probe, a straight-line F multiply/add produced one A finding. Putting the assignment and consumer in **two sequential sibling brace blocks** produced none. Both blocks execute; their region chains merely diverge. The [common-path helper](/Users/solario/Solario/Solido/open-source/simde-lint/src/simde_lint/rules/base.py:169) mistakes a syntactic relationship for an execution relationship.
- One low/high multiply pair feeding **both** low and high unpacks produced one W finding. [W’s description](/Users/solario/Solario/Solido/open-source/simde-lint/src/simde_lint/rules/widening.py:10) explicitly promises two. The recall enumerator also consumes the high multiply after the first match, so agreement can preserve this omission.

All 17 oracle tests passed alongside those probes. I did not rerun the reference-corpus sweeps or change files.

**H1 is useful but insufficient; H2’s proposed prohibition is unjustified; H3 needs a narrower interpretation.** You can close a finite verification deliverable. You cannot close the possibility of correlated mistakes.

1. **First, define what a finding counts and what its fields assert.**

   Spend roughly half a day writing a short, versioned contract outside the rule implementations. For each mechanism, state the counting unit, supported families, detection boundary, grade/reason conditions, suggestion conditions, and cost unit.

   Resolve W’s contradiction explicitly: is the unit a multiply pair or a consuming unpack? If it is the latter, shared producers cannot be consumed after the first finding. Separately decide how costs behave when findings share operations. Two valid findings do not automatically justify adding their reported savings.

   Make the corresponding decision for F: “one add is one opportunity” is a counting convention requiring specification, not a consequence of multiply-add semantics. Include one product feeding two adds as well as two products feeding one add.

   This catches disagreements that additional examples cannot settle because the expected answer itself is underspecified. Do this before expanding the corpus.

2. **Replace “add a neighbouring case” with a finite coverage obligation.**

   Metamorphic pairs are relationships, not a coverage model. A pair is complete only relative to its stated transformation and preconditions. No pair set is complete over C/C++.

   Start with a reviewed inventory of dimensions derived from the contract, language constructs, and defect history. For this repository, the initial inventory should include:

   - Control: same block, producer outside consumer, consumer outside producer, sequential sibling blocks, exclusive arms, independent conditionals, loop boundaries, and early exits.
   - Value flow: named versus nested, direct versus one widening hop, unchanged versus overwritten, and overwrite before versus after consumption.
   - Multiplicity: one producer/one consumer, two producers/one consumer, one producer/two consumers, and an invalid candidate preceding a valid candidate.
   - Representation: register width, element width and kind, direct spelling versus `simde_` spelling versus wrapper macro.
   - Claims: known versus unknown expansion cost, applicable versus mismatched replacement, and each evidence/reason outcome.

   Not every combination is meaningful. Record applicability and exclusions explicitly. Require every applicable value, every applicable pair of dimensions, and selected higher-order combinations implicated by past defects. One mandatory higher-order combination should be portable fallback × accumulator compatibility × register width.

   These are proposed adequacy criteria, not a theorem that pairwise testing finds every bug. Their advantage is that missing cells become visible before somebody remembers a particular example.

   Each transformation must specify which outputs remain invariant and which change. Naming a product should preserve the finding after relocating its anchor. Adding a widening hop need not preserve the final grade: the transform cap may override the structural grade. Moving calls into exclusive arms is an expected change, not a semantics-preserving transformation.

   Include absolute expected answers for the seeds. A tool returning nothing everywhere can satisfy many relational checks.

   Allow approximately one to two days for the inventory and initial cases. This specifically catches the nesting/sibling gap, family omissions, alternate rationale paths, and shared-consumer counting mistakes.

3. **Separate case selection from the fix, then test whether the tests discriminate.**

   A reviewer should inspect the contract and dimension inventory before seeing the implementation change or its output, and propose missing partitions. Record the initial expectations and later adjudications. A second person is not proof of independence; this separation makes the claimed independence concrete and auditable.

   If working alone, use the same inventory before editing the implementation, then conduct a separate review against language constructs and historical defects. Describe that as reduced separation, rather than calling it independent.

   For every changed predicate, require both a case that needs its acceptance and one that needs its rejection. Your existing guard-neutralisation discipline tests guards that are too permissive. Also mutate predicates to be **too restrictive**: replace common-path handling with equality, discard a family, require a named product, or claim a producer after its first consumer. These mutations exercise false negatives.

   Retain a small, named set of historical fault mutations. Require each to fail a designated assertion for the intended reason. Do not pursue a global mutation percentage.

   Budget roughly a day initially, then a modest review addition per rule change. This catches tests that merely accompany the implementation and checks that fail for unrelated reasons.

4. **Complete the oracle runner and make #48’s exit condition mechanical.**

   Require complete expected records for the fields #48 names, including explicit nulls and both costs. Resolve unspecified anchors in the contract rather than silently omitting them. For multiple findings at the same position, compare multisets with an unambiguous identity.

   Validate field types, required fields, enum values, duplicate YAML keys, and fixture/expectation correspondence. Deliberately corrupt each asserted field and confirm failure; also exercise missing and extra findings. The current unknown-key check is valuable but narrower.

   Cost expectations must cite a pinned source and explain the complete idiom being counted. Reading the tool’s knowledge table is not independent validation of that table. Where a count cannot be established, decide whether the correct output is null or whether that claim is explicitly outside this milestone.

   My proposed replacement acceptance condition is:

   “For the versioned seven-mechanism contract and committed coverage manifest, every mandatory case exists; every expected output field is checked; every mandatory relation passes; every named fault mutation is detected; and every discrepancy has a recorded resolution. The results establish conformance on this finite suite, not corpus-wide recall or freedom from shared assumptions.”

   Once those conditions pass, close #48 against that contract. A script can decide completion. Human judgment remains in choosing the contract and coverage manifest, where it belongs.

   Expect half a day to a day for the runner, plus time for source-based cost adjudication. Fixing defects exposed by the suite is additional work. Do not close #48 today merely by weakening its description to match the current tests.

5. **For F and P, decline a full second analyzer now—but retain partial enumeration.**

   H2 conflates implementing the same question with implementing the same reasoning. A second implementation is not automatically circular. Conversely, importing no `simde_lint` does not guarantee useful independence.

   The existing W enumerator already omits redefinition and path checks. It is therefore inconsistent to permit an approximate population finder for W while demanding that an F enumerator solve every inference problem before being useful.

   Two partial cuts are worth doing.

   First, build a **restricted exact slice**. For F, accept only explicitly defined, straight-line shapes: a direct nested multiply/add or a single-assignment product immediately consumed by an add, with simple operands and no wrappers or control flow. For P, accept a named comparison followed by a direct consuming call under similarly restricted conditions. Report every unsupported construct as excluded, not negative. Compare locations and multiplicities, not totals.

   Such a checker need not resolve arbitrary def-use. Its claim is “agreement within this declared grammar,” with the grammar fixed independently of the tool’s successful matches. Budget roughly one day per mechanism, including adversarial tests of the checker.

   Second, enumerate **candidate anchors without deciding the mechanism**: multiply/add families for F and comparison families for P. Select complete functions or bounded source regions before looking at tool findings, and hand-adjudicate every candidate, including negatives and ambiguous cases. This can reveal omissions that a findings-driven precision census cannot see. Keep the existing Quant slice, but add a slice chosen for structural variety and one selected without targeting known findings.

   Budget half a day to a day for an initial bounded audit. Publish exact slice results and unresolved counts; do not convert them into a corpus recall percentage.

   Independently audit family coverage against a pinned intrinsic inventory. Otherwise both the tool and its checker can exclude the same unregistered family. This is relatively cheap and directly targets the defects the 16-bit accumulator and 256-bit insert discoveries exposed.

I would drop the proposed full F/P analyzer, a clang/compile-database project, exhaustive Cartesian case generation, and any attempt to prove statistically independent errors. None is needed to finish this issue. Keep the existing census, but describe its F/P checks accurately: they verify selected structural relationships, not every redefinition, control-flow, grade, or cost claim. The executable finish line is a bounded conformance suite with demonstrated discrimination; continuing assurance comes from the discipline applied to subsequent changes.
