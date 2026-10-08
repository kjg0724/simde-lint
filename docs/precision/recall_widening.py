"""A candidate enumeration for `W.mul16_widen_roundtrip`, built without the tool.

**Candidates, not confirmed round-trips.** What this file counts is a syntactic
shape: three calls, paired by argument text. A round-trip is a claim about
values, and three of the four ways that claim can fail are invisible here --
the unpack taking the halves in the wrong order, an operand rebound between the
two multiplies, and a producer sitting inside a construct the consumer is
outside. All three were measured as grade-A defects in the rule, and this
enumerator counted each of them as an ordinary instance, so its agreement with
the tool never established that either was right. It cannot be used to validate
the predicates that now reject them.

Nor should those predicates be copied in here. An enumerator that applies the
rule's own tests and then agrees with the rule has established nothing; the
value of this file is that it is cruder in a direction a reader can see. What
turns a candidate count into a recall figure is adjudication of the difference,
by hand, in the source -- which is what issue #75 is for. Until that exists,
the number below is a population of candidates and must be labelled as one.

The counting unit, from `docs/mechanisms.md`: **one consuming unpack**. A
`_mm_mullo_epi16`/`_mm_mulhi_epi16` pair over operands equal as written, and
one finding for each unpack that names both results. A pair rebuilding all
eight lanes is two.

The first version of this file took one consumer per pair and stopped, which
is what the implementation did -- so it agreed with the tool and preserved the
omission instead of exposing it. It had been written from the README row,
which says what the rule matches; the counting unit was in the module
docstring, which it did not read. That is the reason `docs/mechanisms.md`
exists.

This file imports no `simde_lint`. It finds the three calls with regular
expressions and pairs them by argument text, which is a cruder test than the
rule's: it does not ask whether either name is redefined in between, nor
whether the three calls can all execute. Where it reports a site the tool does
not, that difference is the answer and has to be read in the source.

    uv run python3 docs/precision/recall_widening.py <root>...
"""
import os
import re
import sys
from collections import Counter

# The binding may end in `;` or in `,` -- a declarator list writes both
# multiplies in one statement, and VVenC's RdCost does:
#     const __m128i xmlo = _mm_mullo_epi16(xcur, xcur),
#                   xmhi = _mm_mulhi_epi16(xcur, xcur);
# Requiring `;` missed the first of the pair and with it the whole site.
BOUND = re.compile(
    r"(?P<target>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*"
    r"_mm_(?P<kind>mullo|mulhi)_epi16\s*\((?P<args>[^;]*?)\)\s*[;,]"
)
UNPACK = re.compile(r"_mm_unpack(?:lo|hi)_epi16\s*\((?P<args>[^;]*?)\)")


def _normalized(args):
    """Argument text with whitespace removed, so spelling differences in
    layout do not make the same operands look different."""
    return re.sub(r"\s+", "", args)


def _names(args):
    return set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", args))


def enumerate_sites(roots):
    sites = []
    for root in roots:
        for base, _, files in os.walk(root):
            for name in sorted(files):
                if not name.endswith((".h", ".hpp", ".c", ".cc", ".cpp")):
                    continue
                path = os.path.join(base, name)
                with open(path, encoding="utf-8", errors="replace") as handle:
                    text = handle.read()
                los = [m for m in BOUND.finditer(text) if m.group("kind") == "mullo"]
                his = [m for m in BOUND.finditer(text) if m.group("kind") == "mulhi"]
                unpacks = list(UNPACK.finditer(text))
                claimed_hi, claimed_unpack = set(), set()
                for lo in los:
                    partner = None
                    for hi in his:
                        if hi.start() in claimed_hi:
                            continue
                        if _normalized(hi.group("args")) != _normalized(lo.group("args")):
                            continue
                        partner = hi
                        break
                    if partner is None:
                        continue
                    consumers = []
                    for unpack in unpacks:
                        if unpack.start() in claimed_unpack:
                            continue
                        if unpack.start() < partner.end():
                            continue
                        taken = _names(unpack.group("args"))
                        if lo.group("target") in taken and partner.group("target") in taken:
                            consumers.append(unpack)
                    if not consumers:
                        continue
                    claimed_hi.add(partner.start())
                    for consumer in consumers:
                        claimed_unpack.add(consumer.start())
                        sites.append((path, text.count("\n", 0, lo.start()) + 1))
    return sites


def main():
    roots = sys.argv[1:]
    if not roots:
        print("usage: recall_widening.py <root>...")
        return 1
    sites = enumerate_sites(roots)
    print("consuming unpacks fed by a mullo/mulhi pair: %d  <- enumerated population" % len(sites))
    for name, count in Counter(os.path.basename(p) for p, _ in sites).most_common():
        print("  %5d  %s" % (count, name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
