# Judging the sample

138 findings are drawn in `sample.json`. 25 of them are rule R, which the
census in `verify_r.py` already settles, so **113 need a human verdict**.

## The question

For each finding: **is the mechanism the rule names actually present at that
call site?**

That is the whole question. Whether the rewrite is safe, whether it is worth
doing, whether the instruction count is right — none of those. The evidence
grade already reports what the tool can and cannot establish about the
transform, and re-litigating it here would be judging the same thing twice
under a different name.

`codebook.md` has the per-rule criteria and was fixed before the sample was
drawn. Read it first; do not amend it while judging.

## Doing it

```bash
export SIMDE_LINT_SVT_AV1=/Users/solario/Solario/Solido/open-source/svt-av1
export SIMDE_LINT_VVENC=/Users/solario/Solario/Solido/open-source/vvenc

uv run python3 docs/precision/show.py 1 20      # findings 1-20, 5 lines of context
uv run python3 docs/precision/show.py 21 40
```

A third argument widens the context: `show.py 1 20 15`.

Record verdicts in `verdicts.json`:

```json
{ "verdicts": { "1": "TP", "2": "FP-shape", "3": "TP" } }
```

The vocabulary is the codebook's, and it distinguishes three ways a finding
can be wrong:

| | |
|---|---|
| `TP` | the named mechanism is present |
| `FP-shape` | right intrinsic, wrong structural claim |
| `FP-context` | right structure, but the call site is not one the mechanism applies to |
| `FP-knowledge` | the knowledge table's claim about SIMDe's expansion is wrong here |
| `UNJUDGED` | the source in the scanned tree does not settle it |

`UNJUDGED` is a real answer, reported separately and never folded into
either side.

## Then

```bash
uv run python3 docs/precision/estimate.py
```

It prints per-stratum precision and a population-weighted point estimate
with a simultaneous 95% lower bound (per-stratum Wilson at `alpha/H`, since
a pooled interval is not valid for an unequally allocated stratified
sample).

## What to watch for

**Rule R needs no judgement and is not in the 113.** Its 25 sampled findings
carry verdicts from the census, which checked all 1922.

**The large strata are the ones that move the number.** `F.mul_add_no_fuse`
at A and at C, and `S.pshufb_guard` at C, are 25 each and cover 41% of the
population between them. The five- and three-finding strata barely move the
weighted estimate; they are there to catch a rule that is wrong everywhere,
not to estimate its precision.

**A finding you are unsure about is `UNJUDGED`, not `TP`.** Resolving doubt
toward the tool is the failure mode this audit exists to detect.
