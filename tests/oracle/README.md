# Oracle corpus

Expected findings decided by reading the rule descriptions and the source,
before and independently of what the tool reports. `expected.yaml` is written
by hand. Nothing in this directory may be generated from tool output — that
would reproduce the failure it exists to catch.

The rest of the suite compares the tool against a second reading built from
the same inference: the fixture tests assert what the rule was written to do,
and `docs/precision/verify.py` re-implements each predicate. Both have missed
defects that shared their blind spot. `verify.py` could not see rule F's
nested multiply-add because its own predicate also required a named product,
and it had to be extended alongside the rule.

A hand-decided expectation cannot acquire the implementation's blind spot. It
can be wrong — a human decided it — but it is wrong independently, which is
the property the rest of the evidence base does not have.

## Adding a case

1. Write the C file. Keep it small enough to reason about completely.
2. Decide the expected findings from the codebook and the rule's stated
   mechanism. Do not run the tool first.
3. Add the entry to `expected.yaml`, with `why` naming the reasoning.
4. Run the suite. If the tool disagrees, decide which is wrong on the merits
   before changing either.

An empty `findings` list is a claim, not an omission: it says this file
contains no instance of any mechanism.
