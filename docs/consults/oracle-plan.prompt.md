# simde-lint: closing issue #48, or establishing that it cannot be closed as written

**Every factual claim below is under test, not a premise.** I wrote them and I
have been wrong repeatedly in exactly this area — three times in the last week
a check I wrote to verify the tool was itself the thing that was wrong. If a
claim here is false, saying so is more useful than answering the question built
on it. If the whole framing is wrong, say that.

## Read these yourself

Repository: `~/Solario/Solido/open-source/simde-lint`, branch `main`.

- `tests/oracle/` — README, `expected.yaml`, `cases/`, and `tests/test_oracle.py`
- `docs/precision/verify.py` and `docs/precision/recall_*.py`
- `docs/verification.md` — Section 0, and the recall section near the end
- `src/simde_lint/rules/` — seven rules: R, S, W, F, M (two mechanisms), P
- `git log --oneline v2.3.1..main` and `CHANGELOG.md` for what has moved

## What the tool is

A CLI that detects six SIMDe-emulation inefficiency types in C/C++ source with
tree-sitter. A finding names a call site, a taxonomy type, an evidence grade
A/B/C, and for C a structured reason. Three reference corpora: SVT-AV1 3404,
VVenC 620, VVdeC 600 (holdout).

## The problem, as issue #48 states it

Verification shares the implementation's inference, so a defect in one is
invisible to the other. This is not hypothetical here:

`docs/precision/verify.py` is an independent checker that re-implements each
rule's predicate and imports no `simde_lint`. It could not see rule F's nested
multiply-add — `acc = _mm_add_epi32(acc, _mm_madd_epi16(a, b))` — because its
own predicate also required the product to be bound to a name. It had to be
extended alongside the rule, and that re-run is weaker evidence than the ones
where it did not move.

## What has been built against it

1. `tests/oracle/`: expectations decided by hand from each rule's published
   description, before running the tool, with the reasoning recorded per case.
   Nine cases, all seven rules, each with a positive shape and a negative one
   beside it. A test validates the expectation vocabulary, after four
   deliberately mistyped keys once left the corpus green.

2. Three independent enumerators (`docs/precision/recall_*.py`) that count a
   mechanism's population without importing the tool, for
   `M.scalar_set_build`, `W.mul16_widen_roundtrip` and
   `M.scalar_insert_chain`. Before them, recall was claimed for two
   name-matched mechanisms only.

3. Along the way these found real defects: a 16-lane multiply-accumulate family
   unregistered (14 SVT-AV1 sites reported nothing), the 256-bit insert family
   unregistered (2 chains), and ten more in a code review of v2.5.0.

## What is NOT in question

- The corpora figures reproduce, the acceptance gate holds (rule S reports 204
  `_mm_shuffle_epi8` call sites against `grep`'s 204), and the precision census
  agrees 3992/3992.
- Section 0's facts: SVT-AV1 contains no `simde` string and compiles a separate
  `ASM_NEON` tree, and VVenC has native NEON for all but two measured modules.
  So these counts are a census of call sites carrying each pattern, not an
  emulation cost being paid. I am not asking you to relitigate that.
- That an independent check is worth having. Two of the three enumerators were
  themselves wrong on first run, and that is expected — a check that can only
  agree proves nothing.

## The failure I keep repeating, and question 2 is about

A reviewer found that a fix I made in `v2.4.0`/`v2.5.0` — requiring two calls
to share a `control_region`, to reject arms of an `if` that cannot both
execute — also rejected **nesting**, where one region encloses the other and
both do run. It suppressed six real VVenC findings.

The oracle did not catch it. Its case covered exclusive arms, the shape the fix
was written for, and not the neighbouring shape the fix would break. The same
pattern appeared twice more in the same review: the portable-fallback rationale
was tested at a matching accumulator width and not at a mismatched one.

A peer session reports hitting the same class independently: measuring a
four-intrinsic idiom by looking at only the one intrinsic the finding is
anchored to, and reaching a conclusion on an incomplete count.

So: cases written by the person making a change cover what that person was
thinking about. Adding more cases does not fix that by itself.

## The candidate answers — treat each as a hypothesis under test

**H1. Metamorphic pairs as the unit of a case.** Advice I already have is to
build cases as pairs that must move together or not at all: named product
against nested product, one region against exclusive arms, direct path against
one widening hop, one multiply against two sharing an add, a reassignment
present against absent. Does this actually prevent the neighbour-shape gap, or
does it just relabel it? What makes a pair *complete*?

**H2. F and P get no independent enumerator, by design.** Counting rule F
independently means deciding, without the tool: direct and indirect def-use,
redefinition, nested operands, the widening hop, exclusive control regions, how
many findings one add shared by two multiplies is, and element kind against
accumulator width. That is rule F implemented a second time, back inside the
first one's assumptions — or a clang AST and a compile database, which is a
different project. Is abandoning a mechanical count for these two correct, and
if so what is the honest substitute?

**H3. #48 cannot be "closed" as written and should be restated.** Its text asks
for a corpus whose expected positions, grades, reasons and costs are decided
independently. Coverage of that has no definition, so nothing decides when it
is done. Should it be replaced by something checkable, and by what?

## What I am asking for

A plan I can execute, or a well-argued refusal. Specifically:

1. A condition under which #48 is finished, stated so that it can be checked
   rather than judged. If no such condition exists, say so and say what to do
   with the issue instead.

2. A discipline that stops a case set from covering only the shapes its author
   was fixing. If H1 is that discipline, say what makes a pair set adequate; if
   it is not, say what replaces it.

3. A ruling on H2, including whether there is a partial cut for F and P that is
   worth having — some sub-question that can be decided independently even
   though the whole cannot.

Order the work, and say what each step would cost against what it would catch.
If part of this is not worth doing, say which part and why — I would rather
drop something than do it badly.

## Output

Plain prose, in whatever language you prefer. No preamble. Lead with whichever
of my claims above you found to be false, if any.
