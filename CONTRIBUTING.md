# Contributing to simde-lint

## Running the test suite

```bash
uv run pytest -v
```

This runs the full suite, including fixture-based unit tests for every rule.
A subset of tests (`tests/test_verification.py`) additionally checks
detection against two external reference checkouts: SVT-AV1 and VVenC. Their
locations default to `~/Solario/Solido/open-source/svt-av1` and
`~/Solario/Solido/open-source/vvenc`, but are read from the environment
first:

- `SIMDE_LINT_SVT_AV1` — path to an SVT-AV1 checkout root (the tests look
  for `<root>/Source`)
- `SIMDE_LINT_VVENC` — path to a VVenC checkout root (the tests look for
  `<root>/source/Lib/CommonLib/x86`)

```bash
SIMDE_LINT_SVT_AV1=/path/to/svt-av1 SIMDE_LINT_VVENC=/path/to/vvenc \
  uv run pytest tests/test_verification.py -v
```

Those tests skip cleanly — not fail — when the checkout isn't present (via
either the environment variable or the default path), so the rest of the
suite stays runnable without either clone. Run a single test file the same
way:

```bash
uv run pytest tests/test_rule_suboptimal.py -v
```

## Adding an intrinsic to the knowledge tables

`src/simde_lint/knowledge/*.yaml` is pure data. No rule hardcodes an
instruction count, a NEON suggestion, or an alias spelling — rule R reads
`ctx.knowledge.redundant[...]`, and the other five read
`ctx.knowledge.cost(self.rule_id)`. Extending what a rule can see is
therefore a data change, not a code change, for any intrinsic that already
fits an implemented mechanism.

**Every entry must cite the SIMDe source line it was read from**, in the
form `x86/<header>.h:<line>` (e.g. `x86/sse2.h:5760`). Do not guess a value
or copy one from documentation — open the actual SIMDe header at the pinned
version and read the expansion. `test_every_cost_entry_cites_a_simde_source_line`
in `tests/test_knowledge.py` enforces the format, but not that you actually
looked — that part is on you.

**Every knowledge file that carries costs or names (`redundant.yaml`,
`patterns.yaml`, `aliases.yaml`) must declare the same top-level
`simde_version` string**, currently `"0.8.4"`. `load_knowledge()` raises
`ValueError` if they disagree — see
`test_disagreeing_simde_versions_fail_loudly` — because a mismatched set
would report one version's instruction counts against another version's
source citations, silently. `wrapper_macros.yaml` is the one exception: its
entries describe a consumer project's own declaration macros (e.g. SVT-AV1's
`DECLARE_ALIGNED`), not a SIMDe expansion, so it carries no version field.

To register a new redundant-load intrinsic (rule R), add an entry to
`knowledge/redundant.yaml`:

```yaml
_mm_your_intrinsic:
  simde_insns: 2
  native_insns: 1
  suggestion: vYourNeonOp
  source: x86/sseN.h:1234
  note: one sentence on what the SIMDe expansion actually does
```

Then add it to the expected key set in
`test_every_rule_that_reports_costs_has_a_pattern_entry` if it's a pattern
(rules S/W/F/M/P) rather than a redundant-load intrinsic (rule R) — the two
tables are checked separately since only rule R indexes by intrinsic name.

If the intrinsic is exposed under a `simde_` prefix or a local project macro
that should normalize onto a canonical x86 name your rules already look for,
add it to `knowledge/aliases.yaml` instead (or as well). Local, file-scoped
`#define` wrappers around an already-known intrinsic (VVenC's
`_my_cmpgt_epi64`, for instance) don't need an aliases.yaml entry at all —
`extract.py`'s `_file_macro_aliases` resolves those automatically by reading
the macro body; `aliases.yaml` is for cross-file, cross-project spellings
like the `simde_mm_*` prefix.

## Adding a rule module

A rule covers one **named mechanism** of a taxonomy type — not the whole
type. This is a deliberate scoping decision (see the design spec, Section
9), not a placeholder for "implement the rest later" in every case; some
mechanisms are explicitly out of scope for v1 (LoopFilter's transpose/blend
Type S, for example).

1. Create `src/simde_lint/rules/<name>.py`. A rule is any object satisfying
   the `Rule` protocol in `rules/base.py`:

   ```python
   class Rule(Protocol):
       type: str
       rule_id: str
       mechanism: str

       def match(self, unit: FunctionUnit, ctx: Context) -> Iterator[Finding]: ...
   ```

   `rule_id` follows the `<TYPE>.<mechanism>` convention (e.g.
   `S.pshufb_guard`, `M.scalar_set_build`). `mechanism` is the human-readable
   phrase that appears next to the bare type letter in every report line —
   see "Report output requirements" below.

2. A rule sees only the `FunctionUnit` IR and the `Context` (`ctx.symbols`,
   `ctx.knowledge`, `ctx.config`). Rules never import each other and never
   inspect tree-sitter nodes directly — `parser.py` and `extract.py` are the
   only modules that touch the tree-sitter API. If your mechanism needs
   something the IR doesn't currently expose (a new `ValueKind`, a new field
   on `IntrinsicCall`), that's an IR change to propose, not a reason to reach
   past it.

3. **Declare which evidence grades the rule can emit, and mean it.** Every
   rule in this codebase states its possible grades in a comment or
   docstring and only ever constructs `Finding`s with grades from that set.
   The current table:

   | Rule | Grades |
   |---|---|
   | R | {A} |
   | S | {A, B, C} |
   | W | {A, B} |
   | F | {A, B} |
   | M (either mechanism) | {A, B} |
   | P | {A} |

   `tests/test_evidence_conformance.py` enforces this table: it runs every
   rule over every fixture in `tests/fixtures/rules/` and asserts each
   rule's emitted grade set is a subset of the row above. If your rule
   grows a grade beyond its declared set, that test fails — update the
   table (and the rule's own docstring) deliberately, don't just let the
   rule drift.

   **Grade C carries a structured `reason`, not free prose.** Any rule that
   can emit C must set `Finding.reason` to one of two `Reason` values:
   - `Reason.UNRESOLVED` — the rule could not see far enough to judge at
     all (a runtime-loaded value, a call result with unknown lanes, a
     symbol not defined in the scanned inputs).
   - `Reason.GUARD_REQUIRED` — the rule saw everything relevant and
     confirmed the guard it's examining is load-bearing (rule S: a mask
     whose lanes are fully known but include one outside the safe range).

   Both share grade C because v1 acts on them identically: do not
   transform without human confirmation. `reason` is `None` for grades A
   and B — see `Reason`'s docstring in `finding.py` for the full rationale,
   including why a fourth grade isn't warranted today. `S.pshufb_guard` is
   the only rule that currently emits C; see `SuboptimalRule._grade` for
   the pattern to follow if a future rule needs it too.

   A rule with no source of uncertainty (structural or purely syntactic
   matching) should emit only A — don't invent a B or C case to look more
   nuanced than the mechanism actually is. A rule whose premise depends on
   an operand value it may not be able to resolve needs at least a B/C split
   so `--min-evidence` means something for it.

4. Register the rule in `src/simde_lint/rules/__init__.py`'s `ALL_RULES`
   list. The registry runs every rule independently over every function
   unit and never merges, deduplicates, or reduces their output — see the
   next section.

5. Add fixture tests: `tests/fixtures/rules/<name>_positive.c` (at least one
   call site the rule should catch, ideally covering more than one evidence
   grade) and `tests/fixtures/rules/<name>_negative.c` (a call site that
   looks similar but should not match — a different intrinsic, a shape just
   outside the mechanism). Use the `run_rule` fixture from
   `tests/conftest.py`, following the pattern in any existing
   `tests/test_rule_*.py` file.

## The prohibition on merging findings

**One location may legitimately produce more than one finding, and this
must never be collapsed.** The taxonomy paper states directly that a code
region can exhibit several inefficiency types at once — VVenC's DepQuant
reports R, S, and P findings on overlapping code, for instance. No rule, no
part of `analyze()`, and no reporter may deduplicate findings by location,
merge two rules' output into one, or pick a "primary" type for a site that
matched more than one rule. If you find yourself writing logic that groups
findings by `(file, line)` and keeps only one, stop — that is very likely
this prohibition, not a legitimate cleanup.

The one place findings *are* grouped for display is the report summary,
which groups by `rule` id (not by bare type) precisely so two mechanisms of
the same type — currently `M.scalar_insert_chain` and `M.scalar_set_build`
— are never collapsed into a single count. See `report/text.py` and
`report/json.py`.

## Report output requirements

`rule_mechanism` must appear next to the bare type letter on every finding
line, in both text and JSON output (`S (pshufb->tbl guard only)` in text; the
`rule_mechanism` field in JSON). Omitting it would let a reader misread "Type
S: 0" as the tool failing to detect Type S entirely, when the correct
reading is that the one implemented S mechanism is absent from that
particular file while a different, unimplemented S mechanism might be
present.

## Style

- Code, comments, commit messages, and all documentation are English.
- No tool-generated traces of any kind in code, comments, commits, issues,
  or docs.
- Python >= 3.10. Runtime dependencies are limited to `tree-sitter`,
  `tree-sitter-cpp`, and `PyYAML`; `pytest` is the only dev dependency. Don't
  add a new dependency for something a few lines of standard library can do.
