# Superseded precision audit (36 findings, three per stratum)

These are the audit's first sample, its verdicts and its write-up. They are
kept because deleting judged data to make a later number look better is the
one thing an audit must never do. They are **not** the current audit, and
nothing in the paper should cite them.

Two independent reasons they no longer apply.

**The strata changed.** v2.0.0 narrowed rule F's grade cap to key on whether
a fused form is established rather than on whether the instruction count is
known. 275 SVT-AV1 findings moved from grade C to grade A, so the
`F.mul_add_no_fuse` strata this sample was drawn from — 637 at C, and the A
stratum it fed — no longer exist at those sizes. A verdict is about a
finding in a stratum; the stratum is gone.

**The allocation could not carry the claim.** Three per stratum gave the
same weight to a stratum holding 51.8% of the population and one holding
three findings, and the pooled Wilson interval reported alongside it is not
valid for an unequally allocated stratified sample. The point estimate was
population-weighted while the interval was not, which is a contradiction
inside one sentence.

Computed correctly, this sample supports a population-weighted lower bound
of **26.8%**, not the 90.4% that was published. That is what three per
stratum buys. The current design draws 25 from strata of 100 or more and 5
below, 138 in all, and `estimate.py` combines per-stratum Wilson bounds at
`alpha/H` under the population weights.

The codebook is not superseded and stays in the parent directory: it fixed
the judging rules before either sample was drawn, and it is the same
codebook the new sample is judged under.
