"""Ground truth for `W.mul16_widen_roundtrip`, built without the tool.

The rule's description: `_mm_mullo_epi16` + `_mm_mulhi_epi16` over the same
operands, consumed by `_mm_unpacklo_epi16`/`_mm_unpackhi_epi16`, within one
unit. Every clause is decidable from the text of the calls -- the operands are
compared as written, and "consumed by" means the unpack names both results.

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
                    consumer = None
                    for unpack in unpacks:
                        if unpack.start() in claimed_unpack:
                            continue
                        if unpack.start() < partner.end():
                            continue
                        taken = _names(unpack.group("args"))
                        if lo.group("target") in taken and partner.group("target") in taken:
                            consumer = unpack
                            break
                    if consumer is None:
                        continue
                    claimed_hi.add(partner.start())
                    claimed_unpack.add(consumer.start())
                    sites.append((path, text.count("\n", 0, lo.start()) + 1))
    return sites


def main():
    roots = sys.argv[1:]
    if not roots:
        print("usage: recall_widening.py <root>...")
        return 1
    sites = enumerate_sites(roots)
    print("mullo/mulhi round-trips into an unpack: %d  <- ground truth" % len(sites))
    for name, count in Counter(os.path.basename(p) for p, _ in sites).most_common():
        print("  %5d  %s" % (count, name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
