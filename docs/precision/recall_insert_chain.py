"""Ground truth for `M.scalar_insert_chain`, built without the tool.

The rule's description: a same-target chain of `_mm_insert_epi16/epi32/epi64`
or `_mm256_insert_epi16/epi32/epi64` at or above a threshold, default three.

Two clauses, both decidable from the text. "Same-target" is the lvalue each
call is bound to, kept as written -- `dd[0]` and `dd[1]` are different places
even though they share an identifier, which is a distinction the tool had to
be taught (see "What the census found"). "Chain" is a run of such bindings
with nothing else between them.

This file imports no `simde_lint`. Where it disagrees with the tool the
difference has to be read in the source, and so far, on two other mechanisms,
the enumeration has been the side in error both times.

    uv run python3 docs/precision/recall_insert_chain.py <root>... [--threshold N]
"""
import os
import re
import sys
from collections import Counter

# The rule's registered set, transcribed from its description rather than
# widened to every insert that exists.
INSERT = re.compile(
    r"(?P<target>[A-Za-z_][A-Za-z0-9_]*(?:\s*\[[^\]]*\])?)\s*=\s*"
    r"_mm(?:256)?_insert_epi(?:16|32|64)\s*\("
)
# Any assignment to a place, used to decide when a target stops being the one
# the chain is building.
ASSIGN = re.compile(r"(?P<target>[A-Za-z_][A-Za-z0-9_]*(?:\s*\[[^\]]*\])?)\s*=(?!=)")


def _normalized(target):
    return re.sub(r"\s+", "", target)


def enumerate_chains(roots, threshold=3):
    """Runs of inserts on one target, within one brace block.

    The description says "a same-target chain", not "consecutive statements",
    and real chains interleave: SVT-AV1's `pickrst` builds `dd[0]` and `dd[1]`
    alternately. A call on another target does not end the chain on this one.
    What ends it is the block closing, or the target being assigned by
    something that is not an insert.
    """
    chains = []
    for root in roots:
        for base, _, files in os.walk(root):
            for name in sorted(files):
                if not name.endswith((".h", ".hpp", ".c", ".cc", ".cpp")):
                    continue
                path = os.path.join(base, name)
                with open(path, encoding="utf-8", errors="replace") as handle:
                    text = handle.read()

                inserts = {m.start(): _normalized(m.group("target"))
                           for m in INSERT.finditer(text)}
                if not inserts:
                    continue

                # Walk the file once, tracking brace depth. Each depth keeps
                # its own per-target counts, so a block closing ends every
                # chain inside it -- the cheap stand-in for a control region.
                counts = [{}]
                depth = 0
                events = sorted(
                    [(pos, "insert") for pos in inserts]
                    + [(m.start(), "assign") for m in ASSIGN.finditer(text)]
                    + [(i, "open") for i, ch in enumerate(text) if ch == "{"]
                    + [(i, "close") for i, ch in enumerate(text) if ch == "}"]
                )

                def flush(scope):
                    for target, positions in scope.items():
                        if len(positions) >= threshold:
                            chains.append((path, text.count("\n", 0, positions[0]) + 1))

                for pos, kind in events:
                    if kind == "open":
                        depth += 1
                        counts.append({})
                    elif kind == "close":
                        if depth == 0:
                            continue
                        flush(counts.pop())
                        depth -= 1
                    elif kind == "insert":
                        counts[-1].setdefault(inserts[pos], []).append(pos)
                    else:
                        if pos in inserts:
                            continue
                        m = ASSIGN.match(text, pos)
                        if m is None:
                            continue
                        target = _normalized(m.group("target"))
                        scope = counts[-1]
                        if target in scope:
                            if len(scope[target]) >= threshold:
                                chains.append(
                                    (path, text.count("\n", 0, scope[target][0]) + 1))
                            del scope[target]
                while counts:
                    flush(counts.pop())
    return chains


def main():
    argv = sys.argv[1:]
    threshold = 3
    if "--threshold" in argv:
        i = argv.index("--threshold")
        threshold = int(argv[i + 1])
        del argv[i:i + 2]
    if not argv:
        print("usage: recall_insert_chain.py <root>... [--threshold N]")
        return 1
    chains = enumerate_chains(argv, threshold)
    print("same-target insert runs of %d or more: %d  <- ground truth"
          % (threshold, len(chains)))
    for name, count in Counter(os.path.basename(p) for p, _ in chains).most_common():
        print("  %5d  %s" % (count, name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
