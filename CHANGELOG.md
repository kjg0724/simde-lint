# Changelog

## Unreleased

### The oracle runner checks the output contract's shape, and every field it asserts is load-bearing

#48 names a tuple — `(file, line, type, evidence, reason, intrinsic,
suggestion, simde_insns, native_insns)` — and the runner checked six of the
nine. All nine are checked now, plus `rule`, `rule_mechanism`, `scope`,
`macro` and `raw_name`.

**Checked is not the same as decided, and the counts are where the two come
apart.** `costs: reported|withheld|partial` says whether the tool must report
instruction counts at all, which follows from whether SIMDe compiles the
intrinsic to NEON — a question `x86/ssse3.h` and `x86/avx2.h` answer
directly. Three values, not two: one count known and the other not is a state
`report/text.py` renders on purpose and rule R produces at every call site, so
a check reading only `simde_insns` would file it under whichever of the other
two happened to match and a rule that started dropping a count would look
unchanged. The numbers themselves are asserted in one case only:
`_mm_shuffle_epi8` expands to `vqtbl1q_s8(a, vandq_u8(b, vdupq_n_u8(0x8F)))`,
three instructions of which two are the pshufb guard, so a mask that needs no
guard leaves the `vqtbl1q` alone — 3 to 1, counted off the header. Rule M's
entries are per chain element and turn on whether the scalar is already in a
register, which is a modelling choice about the call site rather than a line
to count. Reconstructing that reasoning from the table's own `note:` would
restate the table, not check it, so it is a recorded gap.

**A present null is an assertion.** `suggestion:` with no value requires the
tool to offer none; omitting the key asserts nothing. Two of the ten
historical faults live in exactly that gap — a portable-fallback path
asserting instruction counts SIMDe never emits, and a withdrawn suggestion
keeping the count of the instruction it withdrew — and no expectation could
state the contract they broke. Five cases state it now.

**Matched, not zipped.** Expectations paired with findings by sorting both
sides, which needs a key both can compute. `line` is not one: it is optional,
and where a mechanism anchors is not always something the contract fixes.
`shared_producers.c` has two findings at line 8 and two at line 19, and one
case passed only because its chain happened to anchor earliest of three.

The pairing is maximum-cardinality, not first-fit. With first-fit, a broad
expectation claims a finding a narrower one needed, and the narrow one is
reported as unmet — a disagreement with the tool that is really an artefact of
which expectation was written first. `shared_producers.c` already holds two
findings at one line differing only in `suggestion`, so that shape is one
asserted field away.

**Every asserted field is falsified, one at a time, and the comparison must
notice.** Six assertions have shipped in this repository that could not fail.
Corrupting a field and requiring the case to go red is the only evidence that
the corpus checks what it says it checks — it says nothing about whether the
tool is right, which is `faults.yaml`'s job. Dropping any expectation, or
inventing one, must fail too: a rule reporting one extra finding per call site
is the failure mode this corpus was built for, and a runner that only checked
what it was told about would not see it.

**The runner validates its own input.** Value kinds and enum members, so
`reason: guard-required` fails as a malformed expectation rather than as a
disagreement with the tool. Repeated YAML keys, which PyYAML resolves to the
last one silently — at case level that drops a whole case's expectations while
every completeness test still passes. And a field the runner checks that no
case asserts now fails unless `coverage.yaml` records why: four were added at
once here, and adding the capability is not the same as exercising it.

**One invariant moved into the type.** `native_insns` counts a named
replacement, so `Finding` rejects a native count without a `suggestion`. It
holds on every finding the three corpora produce when each is scanned whole,
9,526 of them; moving it into `__post_init__` makes it a guarantee rather than
an observation. One test fixture violated it and was wrong — rule P does name
a replacement.

The mirror — a replacement's count known while the expansion's is not — was
briefly forbidden too, and that was a mistake caught in review.
`report/text.py` renders exactly that pair on purpose, arguing in its own
docstring that collapsing it to "unknown" throws away a fact the header
states. Where SIMDe falls through to portable code only the *saving* is
unavailable, not the number.

**What the corpus still does not assert: most of the numbers.** One case pins
a pair — `shuffle_guard.c`'s 3 → 1, counted off the header above. Every other
`simde_insns` and `native_insns` in the corpus is either null or unasserted,
because deciding a number by hand otherwise means reading the tool's own
knowledge table, and reading a table is not independent validation of it.
Rule M's entries are the concrete blocker: per chain element, and turning on
whether the scalar is already in a register. Recorded in
`tests/oracle/README.md` as a decision, not left as a silence.

### The runner's own guards, neutralised one at a time

`tests/runner_guards.yaml` is `faults.yaml`'s shape aimed inward: twenty-two
mutations of the machinery that decides whether the corpus means anything —
nine in `tests/test_oracle.py`, eleven in the replay harness, two in the
shared YAML loader — each naming the assertion that must die to it. Same
harness; `run_faults.py` takes a catalogue path now.

One check has no entry, and the absence is deliberate: narrowing `caught` from
"exited non-zero" to "a test failed" is subsumed by the count comparison,
which reaches every scenario found so far. The code keeps the narrower form as
the precise statement of what counts; claiming a mutation pinned it would
report coverage it does not have.

The catalogues are separate because the claims differ. One says "this shipped
and this test would have stopped it". The other says "this check is not
decorative", which is a different and, for the runner, more urgent claim: the
runner decides whether every other test under `tests/oracle/` means anything,
so a guard inside it fails in exactly the silent way the corpus was built to
catch elsewhere.

It exists because of what review found. A counterexample test written to pin
the file-attribution check re-derived the path comparison instead of calling
it, so reverting that comparison left both the check and its regression test
green — the ninth inert assertion in this repository, added in the commit that
fixed the eighth. That mutation is `attribution_by_name`, and it survived until
the comparison moved into a shared helper. Naming both tests in an acceptance
clause did not help, because a clause cannot see that two assertions do not
share a code path.

Adding a check to `test_oracle.py` without adding its mutation here is how the
next one gets in.

**The harness needed the same treatment, and a catalogue cannot give it.**
`run_faults.py` read the new catalogue with `yaml.safe_load`, so a repeated
top-level `faults:` would discard the earlier list and the run would print
"all 0 mutations caught" and exit zero — the strict loader written for
`expected.yaml`, re-opened one file over. It is shared now
(`tests/strict_yaml.py`) rather than copied, an empty catalogue is refused
outright however it arose, and `tests/test_run_faults.py` pins both, because
a catalogue of mutations cannot test the code that reads catalogues.

The first version of that pin was itself inert, and this time the sweep said
so rather than a reviewer. Its duplicate key left an *empty* surviving list,
so the emptiness guard caught the file first and the test still passed with
the permissive loader restored. The fixture now leaves a real mutation behind
the duplicate, so only the loader can object, and the test asserts the message
rather than the exit code.

### Fail-closed reading, for the tables as well as the tests

The tables the tool publishes numbers from had the duplicate-key half of the
same hole: `knowledge.py` read `patterns.yaml`, `redundant.yaml` and
`aliases.yaml` with `yaml.safe_load`, where a repeated intrinsic keeps only
the last row — silently changing every instruction count and replacement the
tool reports for it. The loader lives in the package now
(`simde_lint/strictyaml.py`) rather than under `tests/`, and the tables use it.

The catalogue hole generalised. Almost every check under `tests/oracle/` is a
universal statement, and a universal statement over an empty collection is
true — so an emptied `coverage.yaml` passes "every cell is covered or a named
gap" and "every mandatory combination is met by one case" **without examining
anything**. Measured, not supposed:

    all_cells: set()
    every_cell_covered: PASSES VACUOUSLY
    mandatory:          PASSES VACUOUSLY

`strictyaml.require()` now guards each collection these checks quantify over:
the manifest's dimensions, each dimension's values, each mandatory combination
individually (an empty one is `set() <= cells`, met by every case without
naming anything), the gaps, the unasserted fields, the expectations, the cells
cases declare, the fields cases assert, and both catalogues. Zero entries is
zero evidence, whatever emptied it.

Guarding was not enough on its own. The guards sat on collections that are
never empty on disk, so nothing exercised them: neutralising `require()`
entirely left 504 tests passing. Nine tests now hand the loaders emptied
fixtures, and the same neutralisation takes ten of them down.

### Four ways the replay could credit a mutation it had not caught

Chasing that generalisation turned up four more, and the sweep found three of
them rather than a reviewer:

**An anchor can be unique and still wrong.** Moving the loader into its own
module left `if not faults:` matching the `--only` filter instead of the
emptiness guard. `run_faults.py` refuses an anchor occurring zero times *or*
more than once now, because `.replace(find, replace, 1)` otherwise mutates the
first occurrence, which need not be the one the entry describes.

**And it still printed `caught`.** The harness asked only whether the named
assertion fails with the mutation applied — never whether it passes without
it. That test was red at the time for an unrelated reason, so a mutation
landing somewhere harmless looked caught. A baseline run comes first now, and
an already-failing assertion is refused rather than credited.

**A test can pass off the traceback of the thing it is testing.** With
required-field validation removed, every malformed entry died of a `KeyError`
whose traceback printed the missing key's name — which is exactly what the
test asserted. It now requires the refusal's own wording and no traceback at
all.

**A catalogue can describe a mutation it cannot perform.** Missing fields and
repeated names are refused up front: a missing `kills` would credit the run to
whatever node id `None` resolves to, and "caught twin" would not say which of
two entries was caught.

One of those guards was itself too strict, and only the shipped catalogue
showed it: `replace: ""` deletes the anchor, which is how
`sixteen-lane-family-unregistered` expresses two absent table rows, and a
required-field check that read empty as missing rejected all ten entries. It
was caught because the acceptance run covers both catalogues rather than the
new one alone.

**A guard's own mutation can be the thing that breaks.** Disabling the
"`kills` must name an assertion" check made the harness run the whole file the
test named -- which contained that test, which spawns the harness. It did not
fail; it forked until several hundred pytest processes were alive. The fixture
names a throwaway file under `tmp_path` now.

A first attempt at the collection check had the same shape more quietly: an
extra `--collect-only` pass per entry is not a constant cost when the tests
spawn the harness that spawns pytest, and the catalogue went from seconds to
unfinishable. The count comes out of pytest's own summary line now, and the
whole run takes 17 seconds.

**And an interrupted run left a mutation in the tree.** `finally` does not run
for SIGTERM, so a killed replay left a guard neutralised in the working tree,
where the next run would measure its baseline against it -- and where it could
be committed by accident. A signal handler restores every in-flight file;
verified by killing a run and finding the tree clean, where the same kill had
previously left `if False:` behind.

`tests/test_run_faults.py` pins all of these, and `runner_guards.yaml` carries
a mutation for each.

**The first version of that claim was false, and it is the reason for the
section below.** One entry deleted an argument from `require(collection,
what)` rather than neutralising the emptiness guard, so the named test died of
`TypeError` without ever reaching it — and the harness printed `caught`. The
guard was reported covered by a mutation that never touched it.

### A script decides when #48 is done

`tests/acceptance.py` runs the condition clause by clause, each clause naming
the assertion that decides it, and prints what a green run does and does not
establish. Two clauses are narrower than first written, because what they
actually decide is narrower: the counts are excluded except the one adjudicated
case, and "every discrepancy has a recorded resolution" became "no discrepancy
remains, and every case carries its reasoning" — the suite checks that nothing
is open and that every case has a `why`, not that a past disagreement and its
settlement were written down.

The exclusions print with the result rather than sitting in a document beside
it, so a green run cannot be quoted as more than it is. CI runs the script in
place of the fault replay, which it contains.

### The faults that shipped, replayed against the assertions credited with catching them

`tests/faults.yaml` holds ten defects that reached a release, each as a
mutation and the assertion that must fail for it. `tests/run_faults.py`
applies each, runs that one assertion, and requires a failure. CI runs it.

Naming the assertion is the point. "Something fails" credits a test with
catching a fault it fails for unrelated reasons — which is how three
assertions in this repository went inert while still passing.

Naming it was not quite enough, and the gap took until the runner-guard work
below to surface: the replay asked whether the named assertion fails *with*
the mutation, never whether it passed *without* it. An assertion already red
for an unrelated reason would have been credited with catching anything
pointed at it. It now runs the baseline first and refuses to credit a failing
assertion. All ten entries pass that check, so nothing here is withdrawn —
but until this change the evidence was weaker than the claim.

**Six of the ten are over-restrictive**: a predicate that rejects too much, a
family left unregistered, a producer retired before its second consumer.
Every mutation run here before now made predicates *more* permissive, which
exercises false positives only — and almost every defect this month was a
false negative.

One of the ten was not caught. `widening-filters-the-consumer-after-choosing-it`
(#62) had been found by review and fixed, with no oracle case: a regression
would have been silent. `consumer_choice.c` covers it now.

Two things went wrong while building this, both recorded where they happened.
The first run stopped with "anchor not found" — a YAML block scalar had
stripped the indentation, so the mutation did not match the source. The
harness treats that as a hard stop rather than a pass, because a mutation that
does not land reports success; `indent:` states the indentation instead of
encoding it in whitespace. And the first draft of the new case put the
multiplies outside the `if`, which makes the arm's unpack nested rather than
exclusive — a valid consumer, proving nothing.

Adding the case made the coverage manifest fail as designed: a gap it now
covers was stale. The entry had merged rules W and F, so it is split, and
rule F's half still demands a case.

### Coverage the suite computes instead of a claim someone makes

`tests/oracle/coverage.yaml` names six dimensions and 39 values, each
dimension carrying the defect history that makes it one. Every case declares
the cells it covers, and four tests decide the rest:

- a cell must be covered or listed as a gap with a reason;
- a `covers:` entry naming no defined cell fails, so a typo cannot inflate
  coverage the way a mistyped expectation key once hid a falsified assertion;
- a gap a case now exercises fails as stale, because leaving it suppresses the
  failure that would demand the next case;
- a mandatory combination must be met by **one** case, not by two with half of
  it each — the defects here have all been interactions, and splitting them
  across files is how they stayed invisible.

"The corpus covers all seven rules" was true and useless. Every defect since
has been a shape nobody had written down, so adding a dimension value now
fails the suite until a case exists: that is how a shape gets recorded before
it is forgotten.

It found three empty cells immediately — `value_flow.widening_hop`,
`claims.grade_b` and `claims.grade_c_guard_required`. Nine cases and nothing
pinned grade B.

Writing the case for them caught two of my own errors. A mask bound to a
variable is not traced to its literals, so it grades `unresolved` rather than
`guard_required`; and `0x80` is a **safe** lane, because a high bit means
zeroing on both sides. The unsafe lanes are the middle ones, `[16,127]`.

Six gaps are recorded rather than closed: independent conditionals, a loop
boundary, an early exit, an invalid candidate before a valid one for rule F,
a macro-resolved consumer, and a rebinding after the consumer. Each says what
is untested and why.

### Both counting-unit divergences closed

`docs/mechanisms.md` was written with two places the implementation did not
meet it. Both were the same defect — a shared producer retired after its first
consumer — and both are fixed.

Rule W reports one finding per consuming unpack (#66), so a pair rebuilding all
eight lanes is two, which is what its own module docstring and its 5 -> 1 cost
already said. Rule F reports one finding per add (#68), so a product
accumulated into two of them is two, the mirror of two products into one add
being one. The multiply pair is still claimed once, which is what kept VVenC's
DeQuant from reporting sixteen findings for four round-trips.

`docs/precision/recall_widening.py` was brought to the same unit. It had taken
one consumer per pair, matching the implementation rather than the contract, so
its 17/17 agreement preserved the omission instead of exposing it — the failure
the recall work exists to catch, occurring inside the recall work.

One mistake worth recording. Avoiding an infinite loop over a rejected consumer,
the first attempt claimed it globally, on the reasoning that a consumer this
pair cannot own is not one a later pair should inherit. That was asserted, not
established, and it cost a real VVdeC finding — 9 became 8 where the change
should only add. Rejections are per-pair now. It was caught by re-measuring,
not by any test.

| corpus | before | after | W | F |
|---|---:|---:|---|---|
| SVT-AV1 | 3404 | 3409 | 1 -> 2 | 1149 -> 1153 |
| VVenC | 620 | 634 | 17 -> 31 | unchanged |
| VVdeC (holdout) | 600 | 609 | 9 -> 18 | unchanged |

Sampled at the source: VVdeC's nine pairs each feed an `unpacklo` and an
`unpackhi`, and the two findings name different consumers.

Gate 204 == 204. Census 4043 / 4011 / 100.00%, no edit to `verify.py`.
Enumerator agreement after the change: 2/2, 31/31, 18/18.

**These counts must not be summed as savings.** The two findings of an
eight-lane rebuild share the multiply pair, and so do the two findings of a
product reaching two adds.

### A mechanism contract, and two places the implementation does not meet it

`docs/mechanisms.md` states, per mechanism, what one finding counts, which
families are in scope, where detection stops, what each field asserts, and
whether two findings' costs may be added. `README.md` says what a rule matches,
for someone deciding whether to run the tool; this says what a finding *is*,
which is what an expectation cannot be written without.

It exists because those answers were spread across a docstring, a
knowledge-table note and the implementation, and did not all agree. Rule W's
docstring says a pair feeding both unpacks is "two separate matches, not one";
its code reports one. An expectation written from the README and one written
from the docstring disagreed, and nothing decided between them.

Two divergences are declared rather than fixed here, each reproduced:

- rule W reports one finding where the contract says two (#66) — and the cost
  model agrees with the contract, since 5 -> 1 is the cost of the four lanes
  one unpack rebuilds;
- rule F reports one finding for a product reaching two adds, where each add is
  its own opportunity (#68).

Both move corpus figures, so they are separate changes. The contract is the
specification; where they differ the implementation is the defect.

Also recorded: **costs are not additive across findings that share a matched
call.** Two rule W findings over one multiply pair each report the pair, so
summing them double-counts it. A corpus total is a count of findings, not a
saving.

### The region relation names what it tests

Third correction to the same relation, and the reason it needed three: each
was written against the shape in front of it.

- `control_region` equality (v2.4.0, v2.5.0) rejected exclusive arms, and
  nesting with them — six real VVenC findings.
- Prefix-of region chains (#60) fixed nesting, and still rejected two
  sequential sibling blocks, which run one after the other.

Both were syntactic relations standing in for an execution one. Two calls
cannot both run on one pass exactly when some `if` or `switch` encloses both
and they sit in different arms of it; nesting, sequential siblings and
independent conditionals all can. `IntrinsicCall` now records which arm of
each enclosing selection it sits in, and `on_a_common_path` compares those
directly instead of inferring from region identity.

Found by an external review of the oracle work. No corpus figure moves — the
sibling shape appears in none of the three — and the oracle carries it as a
case beside the other two, where it failed before this change.

Rule M is untouched: a chain must sit in one region, so equality is the right
relation there.

### Code review of v2.5.0: ten defects, four of them grade-A visible

The release went out without a code review of its diff. It has one now, and
everything below was reproduced before being changed.

**The control-region relation was wrong** (#60). `control_region` equality was
added to rule F in `v2.4.0` and to rules W and P in `v2.5.0` to reject arms of
an `if` that cannot both execute. It also rejects nesting, which is a different
relation: where one region encloses the other, a path reaching the inner one
runs both. Six real VVenC findings were suppressed — VVenC returns from 614 to
620, and the holdout from 597 to 600.

The IR had said so. `_control_region`'s note warns that rules "must not read
nesting out of it", and equality is the other half of that warning: treating
different regions as mutually exclusive. Rule M compares for equality because a
*chain* must sit in one region; a *producer and its consumer* only have to be
able to run together. `IntrinsicCall` now carries `region_chain`, and
`on_a_common_path` is shared by the three rules that ask the question, so they
cannot drift apart on it.

**The oracle ignored any key it did not recognise** (#61). `evidance: A` was
indistinguishable from a satisfied `evidence`: four deliberate falsifications
left the corpus green. The corpus exists because it is the one check that
cannot inherit the implementation's blind spot, and its own failure mode was
silence. A test now validates the expectation's vocabulary.

**Rule W tested the consumer's region after choosing it** (#62), so the search
ended at a candidate the rule then rejected and a later unpack in the
multiplies' own region was never reached. The test moved inside the search.

**A portable fallback conceded on one path and asserted on the other** (#63).
`_width_mismatch` built its own rationale and hardcoded the sentence
`portable_fallback` exists to suppress. Both paths now share `_observed`.

Five smaller ones. The `suggestion` field said `vmlaq_s16` while the rationale
said "vmlaq_s16 per 128-bit half" — one finding, two claims; register width is
now a table column rather than a `_mm256_` prefix test, and every branch and
the JSON field use the same applied form. The oracle's two sort keys disagreed
and a case passed on the luck of its anchor line. `portable_fallback` loaded
with a default where its siblings raise. The completeness test globbed `*.c`
only. A comment explained numbers it no longer matched.

| corpus | v2.5.0 | now |
|---|---:|---:|
| SVT-AV1 `Source` | 3404 | 3404 |
| VVenC `CommonLib/x86` | 614 | 620 |
| VVdeC `CommonLib/x86` (holdout) | 597 | 600 |

Census 4024 / 3992 / 100.00%, no edit to `verify.py`. Gate 204 == 204.

**Why the oracle missed these.** Its cases covered the shapes the fixes were
written for and not their neighbours: exclusive arms but not nesting, the
portable path at a matching width but not a mismatched one. Both gaps are
cases now.

## 2.5.0 — 2026-09-11

Rules W, P, M and F, plus the verification surface that found most of it.

Two grade-A false positives removed: rules W and P reported across arms of an
`if` that cannot both execute, which rule M carries `control_region` for and
rule F was corrected for in `v2.4.0`. Rule F stopped asserting which machine
instructions a portable fallback emits, and names a 256-bit suggestion "per
128-bit half". `_mm256_insert_epi32` and `_mm256_insert_epi64` are registered,
a family missing while `_mm256_insert_epi16` was present.

`tests/oracle/` is new: expectations decided by hand from the rule
descriptions, before the tool is run, covering all seven rules. It was written
before the fixes above and failed on exactly the defects they close.

Recall is measured for three more mechanisms than before, by enumerators that
import no `simde_lint`. What those figures do and do not establish is set out
in the document rather than left to the reader.

`docs/verification.md` gained Section 0, which says what a finding
establishes: these corpora's x86 paths are largely not what ARM compiles, so
the counts are a census of call sites carrying each pattern and not the
emulation cost these projects pay today.

| corpus | v2.4.0 | v2.5.0 |
|---|---:|---:|
| SVT-AV1 `Source` | 3402 | 3404 |
| VVenC `CommonLib/x86` | 614 | 614 |
| VVdeC `CommonLib/x86` (holdout) | 597 | 597 |

Gate 204 == 204. Census 4018 / 3986 / 100.00%.

### What the recall figures claim, narrowed to what they show

Review of the three enumerators added above. Their arithmetic stands; the
words around it claimed more than the arithmetic does.

The document said the independent check "is not the more reliable of the two",
on the evidence of two disagreements it had lost. Three cases fix no ranking,
and none is claimed now. What is recorded instead is what happened: **all
three enumerators disagreed with the tool on their first run**, and
adjudication found defects in two of them and a missing intrinsic family in
the tool. The value of an independent check is that its errors do not
correlate with the implementation's, not that it is more accurate.

"Ground truth" is gone from the tables, the scripts and their output. These
are regular expressions approximating comments, strings, preprocessor branches
and declarations, not parsers; importing no `simde_lint` argues for
independence and does not confer authority. The figures are agreement against
the corrected enumerators over the population each one found, at the pinned
revisions, and the document now lists what that does not establish —
generalisation to another revision, coverage of every C++ spelling, recall
over the taxonomy rather than over each rule's registered families, or
anything about regions the parser could not read.

F and P are stated as having no enumerator by design rather than by omission,
with the reason: counting either independently means writing that rule a
second time, which returns it to the first one's assumptions. The `QuantX86.h`
hand enumeration is labelled an adjudicated slice of one file, not rule F's
recall on a corpus.

### Recall for the insert chain, and the family it was missing

`M.scalar_insert_chain` turned out to be decidable without the tool, once
"chain" is read as the description writes it rather than as consecutive
statements -- SVT-AV1's `pickrst` builds `dd[0]` and `dd[1]` alternately, and
a call on another target does not end the chain on this one.

The enumeration disagreed twice before agreeing. Written strictly it found
nothing where the tool found 35. Relaxed to the description it found 37, and
**the two extra were real**: chains of `_mm256_insert_epi64`, which the rule
had never registered while `_mm256_insert_epi16` was. There is no difference
in the mechanism -- all three store a scalar into a lane, all three expand
without a NEON branch -- so `_mm256_insert_epi32` and `_mm256_insert_epi64`
are registered now.

This is the second gap of this shape found by an independent enumeration, and
the first time the independent side was right rather than wrong.

| corpus | before | after | rule M |
|---|---:|---:|---|
| SVT-AV1 | 3402 | 3404 | 64 -> 66 |
| VVenC | 614 | 614 | unchanged |
| VVdeC (holdout) | 597 | 597 | unchanged |

Recall after the fix: SVT-AV1 37/37, VVenC and VVdeC 0/0.

### Recall for the widening round-trip

`W.mul16_widen_roundtrip` names three calls and one relation between them, and
operands compared as written settle it. `docs/precision/recall_widening.py`
enumerates it without importing the tool: SVT-AV1 1/1, VVenC 17/17, VVdeC 9/9,
site for site.

The enumeration was wrong once, as the previous one was. It required a binding
to end in `;` and so missed VVenC's `RdCostX86.h:2905`, where both multiplies
sit in one declarator list ending in a comma. Twice out of two the independent
check has been the side in error. That does not make it useless — a check that
can only agree proves nothing — but the document now says it is not the more
reliable of the two.

### Recall, for one more mechanism than was claimed

`docs/verification.md` said F, M, W and P turn on structure so their ground
truth cannot be built by `grep`. That overstated the gap by one:
`M.scalar_set_build` matches `_mm_set_epi64x`/`_mm_set_epi32`/`_mm_set_epi16`
over runtime scalars, excluding all-literal calls, and both halves are
decidable from the text of the call.

`docs/precision/recall_set_build.py` enumerates it without importing the tool.
SVT-AV1 29/29, VVenC 23/23, agreeing site for site rather than only in total.

The first version of that enumeration disagreed on five SVT-AV1 sites and was
wrong on all five: it tested arguments against a character class of "things a
number is spelled with", which takes `e0` and `e1` for hex, and it read one
line, so calls opening their parenthesis at the end of a line were classified
on a fragment. Recorded rather than quietly fixed -- an independent check
earns its place by either side being able to be wrong, and here it was the
check.

`QuantX86.h` was also enumerated by hand, from the file rather than the tool's
output: 4 type W round-trips and 8 type F pairs, both matching. It is one of
the two VVenC modules with no native NEON counterpart, which is where a
finding still describes work SIMDe is doing.

### The oracle corpus covers all seven rules

Five more cases, decided the same way: from the published rule descriptions
and the source, before the tool was run. Every rule now has at least one
positive shape and, alongside it in the same file, a negative one that
separates the mechanism from something that merely looks like it -- a
full-width load against a partial one, two inserts against the threshold of
three, a literal `set` against one over runtime scalars, a known shuffle mask
against a runtime mask, a multiply with no add at all.

Rule F carries the spellings that have cost the most: the product bound to a
name and the product written as the add's operand, which are the same
instance and must both be found; two products reaching one add, which is one
finding because one add is one opportunity; and the float pair, which is the
mechanism with a replacement that is never exact.

The tool agreed with every substantive expectation on the first run. Three
disagreements were mine and all of the same kind -- a line number counted in
my head rather than read off the file -- so the README now says to read them.
That is noise the oracle should not be spending its failures on.

### An oracle corpus, and the two defects it was written to catch

`tests/oracle/` holds expectations decided by hand from the rule descriptions
and the source, before the tool is run. Nothing in it may be generated from
tool output.

Everything else here compares the tool against a second reading built from the
same inference, and that has missed defects sharing its blind spot:
`docs/precision/verify.py` could not see rule F's nested multiply-add because
its own predicate also required a named product, and had to be extended
alongside the rule. A hand-decided expectation can be wrong -- a human decided
it -- but it is wrong independently.

Written first, it failed on exactly the two open defects and passed the rest,
which is the order that makes it evidence rather than a transcript.

**Rules W and P now honour `control_region`.** A widening round-trip split
across arms of an `if` never has both products reaching the unpack, and a
compare in one arm is never followed by a consumer in the other. Both reported
at grade **A**. Rule M carries `control_region` for this and rule F was
corrected for it; W and P are the third and fourth rules to need it, and the
second time it was found only after release. Rule P's stated approximation --
source order for scheduling order -- is about instruction order along one
path, and does not license collapsing exclusive paths into one order.

**A portable fallback no longer claims what it cannot see.** Rule F opened
every rationale with "the multiply and the accumulate are emitted as separate
instructions". For `_mm256_mullo_epi16` and `_mm256_mullo_epi32` SIMDe has no
NEON branch: both fall through to a per-element loop carrying
`SIMDE_VECTORIZE`, so what a compiler emits cannot be read from the source --
which the entries already conceded by recording both counts as unknown. The
table now declares `portable_fallback`, and those rationales say SIMDe
expresses the two operations separately rather than what is emitted. A 256-bit
suggestion also names "per 128-bit half", since that is how the instruction
applies.

Both defects were absent from all three corpora, and the figures confirm it:
SVT-AV1 3402, VVenC 614, VVdeC 597, unchanged to the finding.

Found by review after v2.4.0. Closes #50 and #51.

### What a finding establishes, said where the figures are

`docs/verification.md` stated the precondition for a finding to mean anything
— that the x86 path is what actually compiles on ARM — in the holdout section
and nowhere else. Asked of the two evaluation corpora, the answer changes what
the headline figures describe.

SVT-AV1 contains no `simde` string at the pinned revision. Its CMake selects
`ASM_SSE2/SSSE3/SSE4_1/AVX2/AVX512` under `HAVE_X86_PLATFORM` and
`ASM_NEON/CRC32/DOTPROD/I8MM/SVE/SVE2` under `HAVE_ARM_PLATFORM`, as an
`if`/`elseif`, so all 3402 findings sit in directories ARM never compiles.
VVenC carries hand-written NEON for thirteen modules under
`CommonLib/arm/neon/`, leaving 20 of 614 findings in modules with no NEON
counterpart.

The counts measure what they always measured — call sites whose SIMDe
translation would be inefficient — and that is a different quantity from the
emulation cost these projects pay on ARM today. A new Section 0 says so before
any figure appears, and `verify.py --native-neon` reports the split for any
corpus, so the question is answered by a command rather than remembered. It
was remembered for the holdout and forgotten for the two corpora the figures
come from, which is the failure this closes.

Found by reviewers of the paper that uses these corpora. No finding, count or
grade changes.

### Every file carrying a version string is now checked

`CITATION.cff` read `2.3.1` inside both the `v2.3.2` and `v2.4.0` tags. The
release check added for `v2.4.0` reads the version out of the tool, which is
the right check for the files the tool loads and no check at all for the ones
it does not -- and citation tooling, and anyone following the repository from
a paper, read this one.

A test now asserts `CITATION.cff` and `pyproject.toml` against the installed
package metadata. It failed the moment it was written, which is the point:
the file is corrected here, and a new file carrying a version is now a
deliberate addition to that list rather than a silent omission.

`v2.4.0`'s tag keeps the stale value -- a published tag is not moved -- and
`v2.3.3` carries the corrected one for the release the paper cites.

## 2.4.0 — 2026-09-08

Rule F only. Every other rule is unchanged finding-for-finding on all three
corpora, and the acceptance gate still reads 204 against `grep`'s 204.

`main` reported `simde_lint_version: 2.3.1` for the whole of this work: the
`v2.3.2` version bump lived on that tag and was never merged back, so every
JSON report produced from `main` since then named a version it was not. That
is the third time a version here stopped describing its tree, so the release
checklist now ends with reading the version out of the tool rather than out
of a file.

| corpus | v2.3.1 | v2.4.0 | rule F |
|---|---:|---:|---|
| SVT-AV1 `Source` | 3272 | 3402 | 1019 -> 1149 |
| VVenC `CommonLib/x86` | 449 | 614 | 135 -> 300 |
| VVdeC `CommonLib/x86` (holdout) | 516 | 597 | 77 -> 158 |

Census 4016 checked, 3984 structurally checkable, 100.00% agreement. The
`reason` field gained two values, `transform_changes_result` and
`transform_width_mismatch`, so a consumer matching on the full set needs
updating; nothing was removed or renamed.

### Review findings: a missing family, two grade-A false positives

An independent review of the three rule F changes above. Everything here was
reproduced before being fixed.

**The 16-lane family was never registered.** `_ADD_LANES` had no 16-bit add and
`_mm256_mullo_epi16` was not a registered multiply, so `vmlaq_s16` sat in the
knowledge table unable to be printed: every 16-bit multiply met a wider add and
had its suggestion withdrawn as a width mismatch. SVT-AV1's CDEF filters
accumulate `_mm256_add_epi16(acc, _mm256_mullo_epi16(tap, x))` in fourteen
places and rule F reported nothing on them. A test now asserts the mirror of
the table-completeness check -- every declared accumulator width is reachable
by some registered add -- which fails on the table as it stood.

**Two grade-A false positives, both older than any change above.**

- An add written inside the *multiply's* argument list runs first and feeds it.
  Byte position says it comes later, and the redefinition guard could not
  object: the interval it was handed inverted and passed vacuously -- the same
  inversion the widening-hop branch already guarded against, with no analogue
  on the direct path. Comparing against the multiply's binding statement, not
  its opening byte, rejects it.
- A multiply in one arm of an `if` and an add in the other were reported as a
  fusion, though they never run in the same pass. This is what rule M carries
  `control_region` for; rule F did not ask.

Neither occurs in any of the three corpora. They are recorded because "not
observed" is not "cannot happen", and the census cannot see either class.

**Three smaller corrections.** A width-mismatched finding withdrew its
suggestion but kept `native_insns`, so the report read "no suggestion offered
(4 -> 3 instructions)" -- no replacement, and the replacement is three
instructions; the count now goes with the instruction, as the v2.3.0 entry
records doing for rule R. A result-changing suggestion rendered through the
unqualified `suggestion:` line, which hands a reader a drop-in they must not
treat as one; it now reads `result-changing suggestion:`. And the width check
compared lane widths only, so an integer product reaching `_mm_add_ps` -- both
32-lane -- graded A naming an integer multiply-accumulate for a float
accumulator; it now carries the element kind beside the width.

Two claims in comments and documentation were overstated and are corrected
rather than restated. "A widening hop moves the product to a width the
recorded form does not accumulate at, by definition of widening" is not a
property rule F enforces -- it reads names, not types, and a hop that widens
nothing still grades B. The checked statement is narrower and holds entry by
entry. "Nothing pairs an integer add with a float multiply, the types do not
admit it" was false: it compiles under the lax vector conversions clang
applies by default, which is the configuration SIMDe-on-NEON is built with.

| corpus | before | after | rule F |
|---|---:|---:|---|
| SVT-AV1 | 3366 | 3402 | 1113 -> 1149 |
| VVenC | 605 | 614 | 291 -> 300 |
| VVdeC (holdout) | 582 | 597 | 143 -> 158 |

Gate unchanged at 204. Census 4016 / 3984 / 100.00%, with no edit to
`verify.py`.

### Rule F covers the single-precision float family

`_mm_mul_ps` reaching `_mm_add_ps` was never reported. The taxonomy defines
type F by mechanism -- SIMDe translating one intrinsic at a time and missing a
fusion -- and this is that mechanism: `_mm_mul_ps` expands to `vmulq_f32`
alone (`x86/sse.h:3516`), `_mm_add_ps` to `vaddq_f32` (`:901`), and
`vfmaq_f32` sits unused. Leaving it unregistered left the tool silent about an
inefficiency its own taxonomy covers.

What separates it from every integer case is the price, and that needed a
reason of its own. The three existing grade-C reasons all describe a transform
that is *conditionally* exact: satisfy the condition and the substitution
preserves results, and what a reader checks is whether the condition holds.
`vfmaq_f32` is never exact -- it rounds once where the separate multiply and
add round twice -- so what a reader settles is whether a different answer is
acceptable. In an encoder that is a quality question; in a decoder it can be a
conformance one. Labelling it `transform_requires_context` would have sent the
reader to check a code shape instead. So `transform_changes_result` is a fifth
`Reason`, backed by a fourth `TransformStatus`, `changes_result`.

The `suggestion` is kept, unlike a width mismatch. There the named instruction
was wrong and null was the honest answer; here it is right and has a cost.
What is withdrawn is "use it freely", not "it exists".

Thirteen findings, all grade C by construction:

| corpus | total | rule F | float |
|---|---:|---:|---:|
| SVT-AV1 | 3365 -> 3366 | 1112 -> 1113 | 1 |
| VVenC | 593 -> 605 | 279 -> 291 | 12 |
| VVdeC (holdout) | 582 (unchanged) | 143 (unchanged) | 0 |

VVenC's twelve are two Horner polynomials in its film-grain analysis, which is
what FMA exists for. Census re-ran at 3971 / 3939 / 100.00% with no change to
`verify.py`.

### Rule F stops naming an instruction that cannot be dropped in

`_mm_mul_epi32` products accumulated by `_mm_add_epi32` were reported at grade
**A** suggesting `vmlal_s32`, which accumulates into 64-bit lanes. The
accumulator there is 32. Five call sites in SVT-AV1, all grade A -- the layer
`--min-evidence A` exists to isolate. VVenC and the VVdeC holdout have none.

The cost table maps a suggestion per intrinsic, so the multiply alone picked
it; which add the product reaches is what decides whether it can be used, and
nothing consulted that. `accumulator_lanes` now sits beside `suggestion` in
`knowledge/patterns.yaml`, required for every `F.mul_add_no_fuse` entry the
same way `transform_status` is -- a `KeyError`, not a default, so an entry
that names an instruction without saying what it accumulates into cannot go
unchecked.

The findings stay. The multiply-add is real and unfused, so what is withdrawn
is the replacement: `suggestion` becomes null and the grade drops to C with a
new `reason`, `transform_width_mismatch`. It is distinct from the three
existing reasons because the rule reached an answer rather than declining to
-- neither "could not see" nor "did not check".

Counts do not move; the evidence split does, by exactly those five:

| corpus | total | evidence |
|---|---:|---|
| SVT-AV1 | 3365 (unchanged) | A 873 -> 868, C 2432 -> 2437 |
| VVenC | 593 (unchanged) | unchanged |

The census re-ran unchanged at 3958 / 3926 / 100.00%, and this time
`verify.py` needed no edit: it checks that the mechanism is present, not
which instruction is suggested. That makes it the independent confirmation
the previous entry's re-run could not be.

**A consequence worth stating.** Rule F emits no grade **B** on any of the
three corpora, because a widening hop moves the product to a width the recorded
fused form does not accumulate at -- which is what widening means. It emitted
no B on them before this check existed either, so nothing observed was lost. What changes is that the gap is now visible: the knowledge table
records no fused form for multiply-then-widen-then-accumulate, and
`vmlal_s32` is not the missing entry, because it takes the full 64-bit
product where `_mm_mullo_epi32` truncates to 32 first. The two disagree
exactly when the product overflows.

### Rule F reports a multiply written straight into the add

`acc = _mm_add_epi32(acc, _mm_madd_epi16(a, b))` was never reported. Rule F
required the product to be bound to a name first, so it saw the multiply-add
only when the author happened to introduce an intermediate -- a spelling
choice that changes nothing about the instructions emitted.

Byte position, which decides ordering for a named product, says the opposite
of the truth here: the add's call expression opens before the operand it is
waiting on. Containment decides it instead, and only where there is no name;
a named product still has to be produced before the add that consumes it.
The same applies one conversion further in, so a nested multiply reaching its
add through a widening call grades B as the named form does -- supported and
tested, though it occurs in none of the three corpora.

Findings move, and this is the first change since `v2.2.0` that reports call
sites the tool had never reported:

| corpus | v2.3.1 | now | rule F |
|---|---:|---:|---|
| SVT-AV1 `Source` | 3272 | 3365 | 1019 -> 1112 |
| VVenC `CommonLib/x86` | 449 | 593 | 135 -> 279 |
| VVdeC `CommonLib/x86` (holdout) | 516 | 582 | 77 -> 143 |

Every other type is unchanged to the finding in all three, which is what a
change confined to one rule should look like. VVenC more than doubles on one
idiom: its adaptive loop filter writes `accumA = _mm_add_epi32(accumA,
_mm_madd_epi16(val01A, coeff01A))` throughout.

The acceptance gate is unaffected: rule S still reports 204 `_mm_shuffle_epi8`
call sites against a `grep` count of 204.

The census was re-run over the larger population -- 3958 findings, 3926
structurally checkable, 100.00% agreement. That re-run is weaker evidence
than the previous ones and `docs/verification.md` says so: `verify.py` tested
for a *named* product and disagreed with all 237 new findings, so the checker
had to be extended alongside the rule. It was written from the claim rather
than the rule, deciding containment from byte extents in its own parse where
the rule walks its own argument model, but two implementations that changed
together prove less than two that did not.

Not addressed: the float family (`_mm_mul_ps` -> `_mm_add_ps`) is still
unregistered. `vfmaq_f32` rounds once where the separate multiply and add
round twice, so it is not the semantics-preserving substitution the integer
cases are, and whether it belongs in rule F at all is a taxonomy question
rather than a missing table entry. See #40.

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
