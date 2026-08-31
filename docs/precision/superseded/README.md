# Superseded: the sampled audit

Kept because deleting an audit's working papers to make a later result look
tidier is the one thing an audit must not do. None of this is current, and
nothing in the paper cites it.

Two designs were tried and both are here.

**36 findings, three per stratum.** Equal allocation gave a stratum holding
51.8% of the population the same weight as one holding three findings, and
the pooled Wilson interval reported beside it is not valid for an unequally
allocated stratified sample -- the point estimate was population-weighted
while the interval was not. Computed correctly this sample supports a
population-weighted lower bound of **26.8%**, not the 90.4% first published.

**138 findings, 25 from strata of 100 or more.** A defensible sample. Its
lower bound was 72.2%.

Both were replaced for the same reason: the question they estimate can be
answered exactly. The codebook's test for a true positive is structural, and
structure is what a parser sees, so `../verify.py` checks all 3713 findings
instead of drawing from them. A census does not need an interval, and it
does not need a judge -- which also removes the "one judge, no blinding"
caveat the sampled design could only disclose and not fix.

`sample.py`, `estimate.py`, `show.py`, `seed_r_verdicts.py`, `verify_r.py`
and `HOWTO-judge.md` are the tooling for those two designs. `verify_r.py`
covered rule R alone; `../verify.py` covers all seven mechanisms and
subsumes it.

The codebook is not superseded and stays in the parent directory. It fixes
what counts as a true positive, and `verify.py` implements it.
