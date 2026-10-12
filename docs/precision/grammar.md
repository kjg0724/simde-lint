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
tables, the per-rule searches, F's path policy and M's run semantics below
define them**, and nothing stronger -- and complete only over participants
spelled with their own names, since a participant reached through a `#define`
is invisible to the F, W and M searches rather than counted by them. Not ground truth, and not exact recall: which eligible relations are
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
- **Recognized**, for P's ordering only -- any call whose callee identifier
  begins with `_mm_`, `_mm256_` or `_mm512_`. Not the union of the tables
  above: rule P's own notion of a recognized call is every intrinsic call,
  and a narrower set would have made the enumeration diverge from the rule by
  construction. `_mm_blendv_epi8` consumes a compare in VVenC and is in no
  rule's family, and an enumerator that called it unrecognized would have
  excluded a relation the rule reports. The test is a prefix on the spelling,
  which needs no table and reads nothing from the tool.

**No kind or width compatibility table is needed.** Element kind and lane
width decide the grade rule F assigns, not whether it reports: a mismatch caps
the finding at C and keeps it. So eligibility here is the structural relation
alone, and a mismatch is an admitted relation whose adjudication records it.
What does limit the count is the unit -- one add, one finding -- which the
first-claim rule below encodes.

### Normalized text, and what equality means

Wherever this file says two pieces of source are equal, it means their
**normalized text** is equal: the node's non-comment leaf tokens, in source
order, joined by one space. So `f(a,b)` and `f(a, b)` are equal and
`_mm_mullo_epi16(a, b)` and `_mm_mulhi_epi16(a,b)` have equal argument lists,
which is what "equal as written" has to mean to be usable -- a definition
under which two spellings of one argument list differ by a space would make
rule W's pair test fail on formatting. Nothing else is normalized: no case
folding, no parenthesis removal, no reordering, and no token elided. `(1)` and
`1` are not equal; `( 1 )` and `(1)` are.

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
| `F.mul_add_no_fuse` | each call to an F multiply | every call to an F add that **contains** the anchor, or whose statement is a **later direct sibling** of the anchor's statement in the same compound statement; and every F add in the same relation to each F widening conversion the anchor is nested in or binds into | admitted when the anchor reaches the add over a path of zero or one widening conversion, each edge satisfying clauses 2 to 7 |
| `W.mul16_widen_roundtrip` | each call to `_mm_mullo_epi16` | every call to `_mm_unpacklo_epi16` or `_mm_unpackhi_epi16` that contains the anchor, or whose statement is a later direct sibling of the anchor's | admitted when a `_mm_mulhi_epi16` exists whose argument list's normalized text equals the anchor's, and both reach that one unpack with every edge satisfying clauses 2 to 7; one unpack is one relation |
| `M.scalar_insert_chain` | each **run-initial** insert: a call to an M insert that is the right-hand side of an assignment and is not the admitted successor of an earlier insert in a run | one slot per would-be extension, identified by that insert's file and line, taken in order | the run is admitted when its length is at least **3** |
| `P.cmp_immediate_use` | each call to a P compare | exactly one slot: the call with the next start position after the anchor's within the enclosing function, **whatever it is** -- a recognized call, a detectably macro-spelled call, an unrecognized call, or an indirect call | admitted when that call is recognized and satisfies clauses 2 to 7 with respect to the anchor |

**A consumer containing the anchor is in the search.** A start-position test
alone would have excluded the nesting relation clause 2 admits:
`_mm_add_epi32(acc, _mm_madd_epi16(a, b))` has the add starting before the
multiply, so "every later add" would never find it. Both directions are
searched -- containing, or a later sibling.

**The sibling requirement is part of the search, not an exclusion**, for F
and W. An earlier version searched the whole enclosing function and let
clause 3 exclude the pairs that were not siblings. That is quadratic in
function size, and the first dry run over the holdout produced 1117 of F's
1397 prospective relations and 69 of W's 82 as `not_siblings` -- pairs of
calls in different blocks of one function, which are not blocked relations
but unrelated calls. Nothing is observably stopping them, so by the
positively-observable rule they were never exclusions. They are now outside
the search population: neither exclusions nor negatives. `not_siblings`
remains a reason only where a participant is a descendant of the other's
compound statement, which the search cannot filter out in advance.

That correction dropped 1117 F pairs and 69 W pairs from the dry run. It is a
pre-adjudication grammar correction and not a changed result: no recall figure
had been produced, let alone published. The count of dropped pairs is recorded
here once rather than reported as a metric, which would carry the same
function-size noise under another heading.

**P's search is deliberately broad** and unchanged: its single slot is the
next call whatever it is, because the rule's premise is about adjacency among
recognized calls rather than about a binding. M's run semantics are unchanged
for the same reason: a run is built along one lvalue, not searched for.

**Prospective relations are unique (anchor, consumer) pairs.** F's second
search arm overlaps its first, since an add after a conversion is also an add
after the anchor. The pair is the unit, so the overlap collapses to one
record, and the path -- direct or through which conversion -- is recorded
beside it rather than multiplying the pairs.

**One add belongs to one multiply, and the order of operations matters.**
`docs/mechanisms.md` makes the add the counting unit: "two products reaching
one add is one finding". So the add is adjudicated **once**, and only then is
the instance attributed:

1. collect every admitted relation reaching that add;
2. adjudicate the add once -- is this a fusion opportunity the mechanism
   describes?
3. if it is, attribute the instance to the admitted relation whose anchor
   comes first by the position key below, and record every other admitted
   relation reaching it as `superseded_by_earlier_anchor`;
4. if it is not, every admitted relation reaching it is a non-instance and
   nothing is superseded -- there is no finding to own.

Attributing before adjudicating would have left the case where the earliest
anchor is judged a non-instance and a later one an instance with no defined
answer. The attribution is syntactic, the adjudication is a judgement, and
this is the order they run in.

**The position key** is a total order: start byte, then end byte, then the
index of the node in a pre-order walk of its file's tree. Two anchors with
equal start bytes are therefore ranked, not excluded -- which of two
equally-positioned anchors owns an add does not change the instance count,
so a tie needs an answer rather than an abstention. P's `ambiguous_order` is
different and stays: there a tie means the source order its premise rests on
is undetermined, and the honest record is to exclude it.

**M's run construction.** A run is over one lvalue `T`. It is the sequence, in
source order, of every statement in the run-initial insert's compound
statement that is an assignment whose left-hand side is lvalue-equal to `T`
and whose right-hand side is an M insert whose first argument is
identifier-identical to `T`.

What does **not** end a run: a statement that assigns some other target,
including an insert on another target. `docs/mechanisms.md` is explicit --
"an insert on another target does not end the chain" -- and an earlier draft
of this file said any next statement that was not an insert on `T` terminated
the run, which contradicted the contract and would have split chains the rule
reports whole.

What ends a run: the compound statement closing, a control, jump or `throw`
statement (clause 3 applied to the pair of inserts spanning it), or `T` being
assigned by something that is not an M insert.

The threshold is 3, the rule's documented default, taken as a constant rather
than read from the tool's configuration. A run of 1 or 2 is a negative.

Two ways an extension can fail, and they are not the same record. A run that
ends because nothing further assigns `T` with an insert produces **no
exclusion**: there was nothing there to exclude. A further insert on `T` that
exists but is blocked -- by a control statement or jump between, by a
non-insert assignment to `T` between, or by any of clauses 4 to 7 -- produces
**one exclusion record** with that insert as the prospective consumer, and
ends the run. The run's own identity, where it is admitted, is its last
insert's file and line.

**The binding identifier.** For a declaration it is the declared name. For an
assignment -- which declares nothing -- it is the left-hand side only when
that is a plain identifier. An assignment to any other lvalue (`dd[0]`, `*p`,
`s.m`) establishes no binding identifier and so admits no binding relation for
F, W or P; M does not use binding identity for its chain but lvalue equality,
which is a different test and does accept those forms.

**F's paths, and which one decides the record.** One (anchor, add) pair can
have several paths, defined by what lies between the endpoints rather than by
generic reachability.

An F widening conversion `C` **lies between** the anchor and the add when
`anchor -> C` and `C -> add` are both clause-2 edges. One definition for every
combination -- the anchor binding into `C` or nested in it, `C` binding into
the add or nested in it -- so the mixed cases need no separate wording. Then:

- the **direct** path exists when the anchor reaches the add by clause 2 and
  **no** F widening conversion lies between them;
- a **one-conversion** path exists per `C` lying between them, when no further
  F widening conversion lies on either of its two edges.

Clause 2's nesting is transitive -- any descendant of the consumer's argument
list reaches the consumer -- so without the direct path's exclusion
`_mm_add_epi32(acc, _mm_cvtepi16_epi32(_mm_mullo_epi16(a, b)))` would admit a
"direct" edge as well as the conversion path, land in the zero-conversion
stratum, and two nested conversions would evade the more-than-one rule
entirely. Enumerating the two concrete shapes instead of defining "between"
uniformly missed a third: `p = _mm_mullo_epi16(a, b);` then
`_mm_add_epi32(acc, _mm_cvtepi16_epi32(p))`, where the anchor binds into the
conversion and the conversion nests in the add.

The rest of the policy is fixed here because it changes the admitted,
exclusion and stratum counts.

- The pair is **admitted** if at least one of its paths is admitted. One
  rejected path does not exclude a pair another path reaches.
- The pair's **stratum** is zero-conversion if the direct path is admitted,
  and one-conversion otherwise. Where several one-conversion paths are
  admitted it is still one record in that stratum, with every conversion
  listed.
- The pair is **excluded** only when no path is admitted. Its primary reason
  is then the first in the exclusion table's order among the reasons the
  rejected paths produced, and the record carries the full set, so a pair
  blocked two different ways on two different paths says both.
- A path of more than one conversion is outside rule F's own contract. It is a
  **negative** with respect to F, never an exclusion, and never a path this
  policy ranks.

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
| `macro_spelled` | 1, P only | P's single slot is filled by a call whose callee identifier has **exactly one** `#define` in the same file, outside every `#if`/`#ifdef`, with no `#undef` of the name anywhere in it, and whose replacement text contains a name from a frozen table |
| `macro_ambiguous` | 1, P only | P's slot is filled by a call whose callee has more than one `#define`, or a definition inside a conditional, or an `#undef` -- the honest record for a spelling this grammar cannot pin |
| `unrecognized_consumer` | 1, P only | P's slot is filled by a call to a name in no frozen table and with no `#define` in the file. Not the same as a macro: the next call is simply something else |
| `indirect_callee` | 1, P only | P's slot is filled by a call expression whose callee is not an identifier |
| `control_between` | 3 | a control, jump or `throw` statement between two sibling participants |
| `not_siblings` | 3 | the two participants' nearest enclosing compound statements are different nodes |
| `rebound_between` | 4 | an assignment, compound assignment, `++` or `--` whose target's normalized text equals the binding's, in a statement between them |
| `passed_to_a_call_between` | 4 | the binding's identifier as the operand of a unary `&`, or anywhere inside any call expression's argument list, in a statement between them. Purely syntactic and deliberately conservative: whether such a call mutates it needs overload resolution, which this grammar does not do, so the relation is excluded rather than assumed intact |
| `shadowed_between` | 4 | a declaration of the binding's identifier in a statement between them |
| `unevaluated_context` | 5 | a participant descended from a `sizeof`, `decltype`, `noexcept`, `alignof`, `requires` or `static_assert` node |
| `conditional_operand` | 5 | a participant descended from a conditional expression's consequence or alternative, or from the right operand of `&&` or `||`, that the other participant is not also descended from |
| `ambiguous_order` | P only | two recognized call expressions share a start position |
| `parse_error` | -- | an `ERROR` or `MISSING` node anywhere in the anchor's enclosing function. The anchor is additionally **not adjudicated** -- see below -- whether or not it generates a prospective relation |

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
seen, prospective relations, relations admitted, relations admitted but
`superseded_by_earlier_anchor`, relations adjudicated as instances, negatives,
and exclusions by primary reason. The superseded count is separate from both
the instances and the exclusions: the relation is there and the grammar admits
it, and what the rule's unit says is that another anchor owns the finding.

## What may be published, by coverage

Coverage is **adjudicated anchors over candidate anchors**, per rule and per
corpus. Both count anchors, never relations: F and W can admit several
relations per anchor, so a relation numerator over an anchor denominator could
exceed 100%. An anchor counts as adjudicated when every prospective relation
it generates has been either admitted and judged or excluded. An anchor that
generates **no** prospective relation is adjudicated vacuously and counts,
which would let a corpus of trivial negatives report high coverage -- so the
figure is published twice: over all candidate anchors, and over the anchors
that generate at least one prospective relation. Neither number hides the
other.

**An anchor in a function containing an `ERROR` or `MISSING` node is not
adjudicated at all**, with or without a prospective relation, and is counted
separately as a parse-failure anchor. Without that, a known parse failure
would raise the all-anchor coverage numerator: the anchor would generate no
relation, be adjudicated vacuously, and count as covered, which is the
opposite of what the failure means. These thresholds
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

- **A negative is a syntactic verdict and must be reported as one.** An
  enumerator says "no admitted relation within the observable search" or "no
  prospective relation at all", and never "no mechanism here". The two are
  reported as separate counts for the same reason: one is a search that looked
  and found nothing, the other is a search with nothing to look at.
- **A macro-spelled participant is invisible to F, W and M.** Their searches
  select calls by frozen name, so a participant spelled through a `#define`
  never fills a slot and never becomes an exclusion -- it is simply not seen,
  and the anchor reads as a negative. Only P's search has a slot that any call
  can fill, which is why the macro and indirect reasons are P's alone. An
  enumerator cannot count what its own search cannot reach, and saying so is
  the alternative to a reason that looks countable and is not.
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
