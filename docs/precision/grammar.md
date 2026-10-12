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

**Complete enumeration of the eligible syntactic candidates as the frozen
tables and the per-rule searches below define them**, and nothing stronger. Not ground truth, and not exact recall: which eligible relations are
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
reports its own parse failures as exclusions so that part of this overlap is
visible. Only part: `parse_error` counts errors in functions that contain an
identified anchor, and a failure severe enough to stop an anchor being
identified at all leaves no record anywhere. That residue is not measured by
this grammar and is not claimed to be.

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

### Frozen name tables

An enumerator reads no table from the tool. These sets are transcribed here by
hand, from the rules' own descriptions, and frozen: an enumerator either
embeds them or reads them from its own data file. If the tool registers a new
family these do not change until this file is edited, and the edit says which
published figure it invalidates.

- **F multiplies** -- `_mm_mullo_epi16`, `_mm_mullo_epi32`, `_mm_madd_epi16`,
  `_mm_mul_epi32`, `_mm_mul_ps`, `_mm256_mullo_epi16`, `_mm256_mullo_epi32`,
  `_mm256_madd_epi16`, `_mm256_mul_epi32`, `_mm256_mul_ps`.
- **F adds** -- `_mm_add_epi16`, `_mm_add_epi32`, `_mm_add_epi64`,
  `_mm_add_ps`, `_mm256_add_epi16`, `_mm256_add_epi32`, `_mm256_add_epi64`,
  `_mm256_add_ps`.
- **F widening conversions** -- `_mm_cvtepi16_epi32`, `_mm_cvtepi32_epi64`,
  `_mm256_cvtepi16_epi32`, `_mm256_cvtepi32_epi64`.
- **W** -- producer `_mm_mullo_epi16`, partner `_mm_mulhi_epi16`, consumers
  `_mm_unpacklo_epi16` and `_mm_unpackhi_epi16`.
- **M inserts** -- `_mm_insert_epi16`, `_mm_insert_epi32`, `_mm_insert_epi64`,
  `_mm256_insert_epi16`, `_mm256_insert_epi32`, `_mm256_insert_epi64`.
- **P compares** -- `_mm_cmpeq_epi32`, `_mm_cmpeq_epi64`, `_mm_cmpgt_epi8`,
  `_mm_cmpgt_epi16`, `_mm_cmpgt_epi32`, `_mm_cmpgt_epi64`,
  `_mm256_cmpgt_epi32`, `_mm256_cmpgt_epi64`.
- **Recognized**, for P's ordering only -- the union of every set above with
  `_mm_shuffle_epi8` and `_mm256_shuffle_epi8` (rule S), and `_mm_loadu_si32`,
  `_mm_loadu_si64`, `_mm_loadl_epi64`, `_mm_cvtsi32_si128` and
  `_mm_cvtsi64_si128` (rule R).

**No kind or width compatibility table is needed.** Rule F reports a relation
between any registered multiply and any registered add; element kind and lane
width decide the grade it assigns, not whether it reports. Eligibility here is
the relation alone, and a kind or width mismatch is an admitted relation whose
adjudication records the mismatch.

### Normalized text, and what equality means

Wherever this file says two pieces of source are equal, it means their
**normalized text** is equal byte for byte: the parse-tree text of the node
with comment nodes removed and every run of whitespace replaced by one space,
trimmed. Nothing else is normalized -- no case folding, no parenthesis
removal, no reordering.

**Stripping.** Where a clause asks whether a call expression "is" an
expression, the expression is first reduced by removing enclosing parentheses
and any cast whose operand is the remainder -- a C-style cast, a
`static_cast`, a `reinterpret_cast`, a `const_cast`. The call "is" the
expression when the reduction yields exactly that call expression. A call that
survives as a proper sub-expression of the reduction is not a binding; it may
be a nesting relation with respect to the enclosing call.

**Identifier identity.** A binding's declared identifier matches an argument
when their normalized texts are equal **and** no declaration of that
identifier appears between the two statements. A declaration between them is
the `shadowed_between` exclusion, not a resolution attempt.

**Lvalue equality**, for M, is normalized-text equality of the assignment's
left-hand side: `dd[0]` and `dd[1]` differ, `dd [0]` and `dd[0]` do not.

### Per-rule anchors, prospective consumers, and relations

The **prospective consumer search** is defined per rule and runs **before**
clauses 1 to 7. It fixes the denominator: every (anchor, prospective consumer)
pair is a prospective relation, and each is then admitted or excluded with one
primary reason. An anchor for which the search yields nothing is a
**negative**, not an exclusion.

| Rule | Candidate anchor | Prospective consumer search | Relation |
|---|---|---|---|
| `F.mul_add_no_fuse` | each call to an F multiply | every call to an F add whose call expression starts after the anchor's, within the anchor's enclosing function; and for each F widening conversion the anchor is nested in or binds into, every F add starting after that conversion | admitted when the anchor reaches the add over a path of zero or one widening conversion, each edge satisfying clauses 2 to 7 |
| `W.mul16_widen_roundtrip` | each call to `_mm_mullo_epi16` | every call to `_mm_unpacklo_epi16` or `_mm_unpackhi_epi16` starting after the anchor, within the enclosing function | admitted when a `_mm_mulhi_epi16` exists whose argument list's normalized text equals the anchor's, and both reach that one unpack with every edge satisfying clauses 2 to 7; one unpack is one relation |
| `M.scalar_insert_chain` | each **run-initial** insert: a call to an M insert that is the right-hand side of an assignment and is not the admitted successor of an earlier insert in a run | the run, constructed below | admitted when the run's length is at least **3** |
| `P.cmp_immediate_use` | each call to a P compare | exactly one: the recognized call with the next start position after the anchor's, within the enclosing function | admitted when that call satisfies clauses 2 to 7 with respect to the anchor |

**M's run construction.** From a run-initial insert, the run extends to the
next statement that is a sibling per clause 3, is an assignment whose
left-hand side is lvalue-equal to the run's, and whose right-hand side is an M
insert whose first argument is identifier-identical to that lvalue. Extension
stops at the first statement that is not that. The threshold is 3, the rule's
documented default, taken as a constant rather than read from the tool's
configuration. A run of 1 or 2 is a negative.

**P's ordering.** Recognized calls are ordered by the start position of their
call expressions, nested calls included. Measured against the parser this
enumerator uses: in `outer(inner())` the enclosing call expression starts at
`outer` and the argument call starts later, at `inner`, so start-position
order is the enclosing call and then the nested one, and an enclosing call is
never "next" after a compare nested in its own arguments. Two call
expressions with **equal** start positions are ineligible and recorded as
`ambiguous_order` -- a tie-breaker fixed in advance rather than an ordering
invented when one is met.

**F's strata.** Zero-conversion and one-conversion paths are reported
separately. A path of more than one conversion is outside rule F's own
contract and is a **negative** with respect to F, not an exclusion.

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
| `macro_spelled` | 1 | the callee identifier of a prospective participant has **exactly one** `#define` in the same file, that definition is outside every `#if`/`#ifdef`, the file has no `#undef` of the name, and the replacement text contains a name from a frozen table |
| `macro_ambiguous` | 1 | that identifier has more than one `#define` in the file, or a definition inside a conditional, or an `#undef` -- the honest record for a spelling this grammar cannot pin |
| `indirect_callee` | 1 | a prospective consumer slot is filled by a call expression whose callee is not an identifier. An indirect call filling no slot of any identified anchor is not counted at all |
| `control_between` | 3 | a control, jump or `throw` statement between two sibling participants |
| `not_siblings` | 3 | the two participants' nearest enclosing compound statements are different nodes |
| `rebound_between` | 4 | an assignment, compound assignment, `++` or `--` whose target's normalized text equals the binding's, in a statement between them |
| `passed_to_a_call_between` | 4 | the binding's identifier as the operand of a unary `&`, or anywhere inside any call expression's argument list, in a statement between them. Purely syntactic and deliberately conservative: whether such a call mutates it needs overload resolution, which this grammar does not do, so the relation is excluded rather than assumed intact |
| `shadowed_between` | 4 | a declaration of the binding's identifier in a statement between them |
| `unevaluated_context` | 5 | a participant descended from a `sizeof`, `decltype`, `noexcept`, `alignof`, `requires` or `static_assert` node |
| `conditional_operand` | 5 | a participant descended from a conditional expression's consequence or alternative, or from the right operand of `&&` or `||`, that the other participant is not also descended from |
| `ambiguous_order` | P only | two recognized call expressions share a start position |
| `parse_error` | -- | an `ERROR` or `MISSING` node anywhere in the anchor's enclosing function |

### The unit of exclusion

One record per **(rule, anchor, prospective consumer)** triple, with exactly
one primary reason. An anchor with several prospective consumers produces
several records, and `parse_error` in its enclosing function produces one per
triple rather than one per function. Where more than one reason applies the
primary reason is the first that matches in the order the table lists, and the
record carries the full set alongside it, so that changing the precedence does
not silently rewrite history. The anchor is identified by file and line, the
prospective consumer by file and line.

**An anchor whose search yields no prospective consumer is a negative** and
gets no record. **A call with no enclosing function is not an anchor** -- not
counted as a candidate, no record, and so `no_ancestry` is not an exclusion
reason: a construct that cannot be attributed to a body is outside the
population this grammar describes, and saying so is more honest than counting
it.

A conforming enumerator reports, per rule and per corpus: candidate anchors
seen, prospective relations, relations admitted, relations adjudicated as
instances, negatives, and exclusions by primary reason.

## What may be published, by coverage

Coverage is **adjudicated anchors over candidate anchors**, per rule and per
corpus. Both count anchors, never relations: F and W can admit several
relations per anchor, so a relation numerator over an anchor denominator could
exceed 100%. An anchor counts as adjudicated when every prospective relation
it generates has been either admitted and judged or excluded. These thresholds
are fixed here, before any coverage figure has been measured, so that the form
of the claim is not chosen to suit the number.

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
