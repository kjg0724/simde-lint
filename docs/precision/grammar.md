# The grammar an enumerator is complete over

This file is written before any enumerator conforming to it exists, and
before any figure produced by one has been seen. That ordering is the point.
An enumerator that treats "I could not read this" as "there is nothing here"
produces a recall figure that flatters itself, and an exclusion list written
after the results is a list of whatever made the numbers agree. So the
excluded constructs are named here first, with how each is detected, and the
commit that adds this file adds no enumerator.

**What existed when this was drafted.** Three enumerators --
`recall_insert_chain.py`, `recall_set_build.py`, `recall_widening.py` -- and
the figures they produce, which `docs/verification.md` publishes for rules M
and W; earlier F, M, P and W figures in `docs/precision/superseded/`; and the
tool's own holdout totals (`R 224, S 196, F 161, W 18, M 2, P 2`). None of
those implements this grammar. What had not been seen was any
grammar-conforming enumeration or any agreement figure from one.

## Why the restriction exists

Rules R and S need no relation grammar. They report every call to a
registered name, so a name-matched pass over a comment-stripped file
enumerates the same population the rule reports, and `docs/verification.md`
publishes their agreement that way. That pass is not unconditionally complete
either -- it shares the corpus's unparsable regions and resolves no
preprocessor -- and the figures there carry those limits.

F, M's insert chain, W and P do not report call sites. They report relations
between call sites: a multiply whose product an add consumes, a run of
inserts on one target, a `mullo`/`mulhi` pair feeding an unpack, a compare the
next call uses. A relation is a claim about what reaches what, and reading
that off source is decidable only where the source says it plainly. This file
says where that is.

**`M.scalar_set_build` is outside this grammar.** Its unit is one call and its
classification comes from that call's own argument list, so it needs no
relation and gains nothing from being forced through one.
`recall_set_build.py` already enumerates it and `docs/verification.md`
publishes the agreement.

## What an enumerator over this grammar may claim

**Complete enumeration of the eligible syntactic candidates**, and nothing
stronger. Not ground truth, and not exact recall: which eligible relations are
instances of a mechanism is adjudicated by hand (see "The adjudication is a
judgement"). The automatic half enumerates; the judgement half decides.

## Independence

An enumerator built over this grammar **may**: use a general C/C++ parser or
its raw syntax tree; identify the enclosing function, compound statement,
control statements and their arms; and scan intervening statements for
rebinding and for exits.

It **may not**: import `simde_lint`; reuse its IR, its region identifiers,
`reaches_on_every_path`, its call extraction, its alias expansion or any rule
predicate; translate the tool's region output into its own decisions; or copy
its control-flow algorithm.

It uses `tree_sitter_cpp`, the same parser the tool uses. That is a disclosed
shared dependency, not independence: a construct the parser mishandles is
mishandled for both at once, which is the failure Section 5 of
`docs/verification.md` records for `ERROR` nodes. A conforming enumerator
reports its own parse failures as exclusions so that this overlap is visible
in the figures rather than assumed away.

## The grammar

An enumerator is complete over relations whose every participant satisfies all
of the following.

1. **Named directly.** Each participating call expression's callee is an
   identifier that is a registered intrinsic name for the rule in question.
   A call through a function pointer, a wrapper function, or a name a
   `#define` forwards is not a participant.

2. **Related by a binding or by nesting.** The producer reaches the consumer
   in one of exactly two ways:
   - **binding**: the producer is the right-hand side of an assignment, or the
     initializer of a declaration, whose declared identifier appears as an
     argument of the consumer;
   - **nesting**: the producer's call expression is a descendant of the
     consumer's argument list.

   A value that travels any other way -- through memory, through another
   function, through a reference parameter, across a function boundary -- is
   not a relation this grammar admits.

3. **Siblings in one compound statement.** For a binding relation, the
   producer's statement and the consumer's statement are both direct children
   of the same compound statement, and no statement between them is a control
   statement (`if`, `for`, `while`, `do`, `switch`, or a labelled statement),
   a jump (`return`, `goto`, `break`, `continue`), or a `throw`. For a nesting
   relation the two share one statement and this clause is satisfied by
   construction.

   This replaces an earlier "no brace between the call sites" clause, which
   was neither necessary nor sufficient: it excluded two calls inside one
   braced `if` body while admitting a rebinding under an unbraced `if`, and
   said nothing about unbraced loops, `switch` labels, ternaries,
   short-circuit operators or early exits. Being direct children of one
   compound statement is cruder than a control-flow analysis and actually
   enforces the slice it promises.

4. **Not rebound or possibly rebound between them.** For a binding relation,
   no statement between producer and consumer may assign to the binding,
   apply a compound assignment or an increment to it, take its address, or
   pass it to any call by pointer or by non-const reference. The last is the
   conservative half: whether such a call mutates it is not decidable here, so
   the relation is excluded rather than assumed intact.

5. **In an evaluated context.** Neither participant is inside `sizeof`,
   `decltype`, `noexcept`, `alignof`, a `requires` clause, or a `static_assert`
   condition, and neither is an operand of a conditional expression (`?:`) or
   of `&&`/`||` whose evaluation the other does not share.

6. **Attributed to the body it is written in.** A lambda body, or any other
   nested function-like body, is its own compound statement. A call inside one
   is never a sibling of a call outside it.

7. **Outside comments and string literals.** Decided by the parse tree, not by
   text matching: a registered name inside a comment or a literal is not a
   call expression and is not a candidate.

### Per-rule candidate anchors and relation shapes

The "candidate" population is the denominator of every figure, so each rule
states its own.

| Rule | Candidate anchor | Relation the grammar admits |
|---|---|---|
| `F.mul_add_no_fuse` | each call to a registered multiply family (`mullo_epi16/epi32`, `madd_epi16`, `mul_epi32`, `mul_ps`, 128 and 256 bit) | anchor to an `add` of matching element kind and lane width, by a path of **zero or one** registered widening conversion, each edge satisfying clauses 2-6 |
| `W.mul16_widen_roundtrip` | each call to `_mm_mullo_epi16` | the `mulhi_epi16` over operands equal as written, and the `_mm_unpacklo_epi16` or `_mm_unpackhi_epi16` consuming both, each edge satisfying clauses 2-6; one consuming unpack is one relation |
| `M.scalar_insert_chain` | each call to a registered insert family | the next insert bound to the same lvalue as written, clauses 3-6 applying to each adjacent pair; a run of them is one relation |
| `P.cmp_immediate_use` | each call to a registered compare family | the **next recognized call** in source order, where "recognized" means a call whose callee identifier is a registered intrinsic of any rule, and where both are siblings per clause 3 |

**F's one-hop path is inside the grammar**, being two applications of clause
2, and the direct and one-hop strata are reported separately. A path of more
than one conversion is outside rule F's own contract, so it is a **negative**
with respect to F and not a grammar exclusion.

**P's ordering is defined here** because "the next recognized call" needs one.
Recognized calls are ordered by the start position of their call expressions,
nested calls included, so a call written inside another's arguments precedes
the enclosing call's own position only if its start position is earlier --
which, for an argument, it is not. The consumer is the recognized call with
the next start position after the anchor's, and the relation is excluded if
that call is not a sibling of the anchor per clause 3.

## Exclusions

An exclusion is **counted and reported, never scored as a negative**. A
candidate anchor with no admitted relation is a negative and is reported as
one; a candidate whose relation is blocked by an observable construct is an
exclusion.

**Exclusions are limited to constructs positively observable from an
identified candidate.** An anchor whose value is passed to an unknown function
is a negative with respect to this grammar, not an exclusion: there is no way
to tell a hidden relation from no relation without the resolution the grammar
declines to do, and counting the hypothesis as an exclusion would inflate the
excluded figure with mechanisms that may not exist. The one wrapper case that
is observable, and therefore counted, is a `#define` in the same file whose
body contains a registered intrinsic and whose name appears as a callee: that
is a macro-spelled participant the text shows.

| Reason | Clause | Positively observed as |
|---|---|---|
| `macro_spelled` | 1 | a callee identifier that a same-file `#define` defines, whose body contains a registered intrinsic |
| `indirect_callee` | 1 | a call expression whose callee is not an identifier |
| `control_between` | 3 | a control, jump or `throw` statement between two sibling participants |
| `not_siblings` | 3 | participants in different compound statements, one of them a descendant of the other's |
| `rebound_between` | 4 | an assignment, compound assignment or increment to the binding between them |
| `address_taken` | 4 | the binding's address taken, or the binding passed by pointer or non-const reference, between them |
| `unevaluated_context` | 5 | a participant inside `sizeof`, `decltype`, `noexcept`, `alignof`, `requires` or `static_assert` |
| `conditional_operand` | 5 | a participant as an operand of `?:`, `&&` or `||` that the other does not share |
| `parse_error` | -- | an `ERROR` or `MISSING` node in the participant's enclosing function |
| `no_ancestry` | -- | the enclosing function or compound statement could not be identified |

### The unit of exclusion

One record per **(rule, anchor, prospective consumer)** triple, with exactly
one primary reason. An anchor with several prospective consumers produces
several records. Where more than one reason applies, the primary reason is the
first that matches in the order the table above lists, and the record carries
the full set alongside it so that a precedence change does not silently
rewrite history. The anchor is identified by file and line, the prospective
consumer by file and line or by `none`.

A conforming enumerator reports, per rule and per corpus: candidate anchors
seen, relations admitted, relations adjudicated as instances, negatives, and
exclusions by reason.

## What may be published, by coverage

Coverage is adjudicated candidates over candidate anchors, per rule and per
corpus. These thresholds are fixed here, before any coverage figure has been
measured, so that the form of the claim is not chosen to suit the number.

- **At least 50%**: a slice-recall percentage may be a headline result, always
  with the coverage and the exclusions printed beside it.
- **10% to 49.9%**: publishable only as "recall on the eligible syntactic
  slice", never as recall for the rule or for the corpus.
- **Below 10%**: counts and site-level agreement only. No percentage.

So a figure over a tenth of the candidates, after nine tenths were excluded,
may be published as: "on the eligible slice, covering 10% of candidate
anchors, observed recall was X of Y; this does not estimate corpus-wide
recall." It cannot support a general recall claim.

## What this grammar does not make exact

Stated here rather than discovered later:

- **It is not the taxonomy.** The grammar is over the intrinsic families each
  rule registers. A shape in the paper's taxonomy that no rule registers is
  invisible to the tool and to an enumerator built from the rule's own
  description, both at once. No figure produced under this grammar bears on
  that.
- **It shares the corpus and the parser.** A construct the tool and the
  enumerator misread the same way -- the eleven call sites past an `ERROR`
  node that Section 5 records -- is invisible to the comparison. The
  `parse_error` exclusion exists so the overlap is at least counted.
- **The adjudication is a judgement.** The grammar decides which relations an
  enumerator may claim; which of them are instances is decided by hand, and a
  hand is not independent of the person whose tool it checks. The adjudicated
  slice is published so the judgement can be disputed, which is the only
  remedy available.
- **Exactness is over the slice.** Where the excluded count is large the
  figure describes a part of the corpus, and the part is reported with it.

## Provenance of the three earlier enumerators

`recall_insert_chain.py`, `recall_set_build.py` and `recall_widening.py`
predate this grammar and do not implement it. They are regex passes with no
sibling, rebinding, evaluated-context or ancestry clause, and
`recall_widening.py` is already labelled a candidate enumeration rather than a
recall figure. They stay as they are: the figures `docs/verification.md`
publishes were produced by them, and rewriting them in place would destroy
the reproducibility of statements already made. Enumerators conforming to this
grammar are separate entry points, and where their populations differ from the
earlier ones, the new figures are marked as superseding rather than silently
replacing them.

## Stability

Changing a clause here changes what an enumerator may claim, so a change is a
change to the evidence and not to its presentation. Any later edit states what
it changes, why, and which published figure it invalidates.
