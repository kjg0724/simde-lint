"""An independent enumeration of `M.scalar_set_build`, built without the tool.

The recall table in `docs/verification.md` covered rules R and S only,
because both match registered intrinsic names and `grep` answers them. F, M
and W turn on structure, so their ground truth was said to need judgement.

That is true of three of the four mechanisms. `M.scalar_set_build` is the
exception: its description is "`_mm_set_epi64x`/`_mm_set_epi32`/`_mm_set_epi16`
assembling a vector from runtime scalars, all-literal calls excluded as
constant vectors". Both halves are decidable from the text of the call, so a
ground truth can be enumerated here and compared.

This file imports no `simde_lint`. It finds the calls with a regular
expression and classifies each argument list by whether anything in it is not
a literal, then prints the count a correct implementation must report.

    uv run python3 docs/precision/recall_set_build.py <root>...
"""
import os
import re
import sys
from collections import Counter

CALL = re.compile(r"_mm_set_epi(?:64x|32|16)\s*\(")
_NUMBER = re.compile(r"0[xX][0-9a-fA-F]+[uUlL]*|\d+[uUlL]*")
_IDENTIFIER = re.compile(r"[A-Za-z_]")


def _is_literal_only(args):
    """Whether every argument is a numeric literal.

    Written the hard way after the easy way was wrong twice. Matching the
    argument text against a character class of "things a number is spelled
    with" accepts `e0` and `e1` as hex, and `_mm_set_epi32(0, e1, 0, e0)` in
    SVT-AV1's synonyms.h is exactly that shape. Numbers are removed first,
    and whatever letter survives is an identifier.
    """
    return not _IDENTIFIER.search(_NUMBER.sub(" ", args))


def _argument_text(text, start):
    """The call's argument list, however many lines it spans.

    The first version read one line, so a call whose arguments continued
    below saw a fragment and was classified on it. Three of SVT-AV1's cdef
    call sites open the parenthesis at the end of a line.
    """
    depth = 0
    out = []
    for ch in text[start:]:
        if ch == "(":
            depth += 1
            if depth == 1:
                continue
        elif ch == ")":
            depth -= 1
            if depth == 0:
                break
        out.append(ch)
    return "".join(out)


def enumerate_sites(roots):
    every, runtime = 0, []
    for root in roots:
        for base, _, files in os.walk(root):
            for name in sorted(files):
                if not name.endswith((".h", ".hpp", ".c", ".cc", ".cpp")):
                    continue
                path = os.path.join(base, name)
                with open(path, encoding="utf-8", errors="replace") as handle:
                    text = handle.read()
                for match in CALL.finditer(text):
                    every += 1
                    args = _argument_text(text, match.end() - 1)
                    if not _is_literal_only(args):
                        line = text.count("\n", 0, match.start()) + 1
                        runtime.append((path, line))
    return every, runtime


def main():
    roots = sys.argv[1:]
    if not roots:
        print(__doc__.strip().splitlines()[-1].strip())
        return 1
    every, runtime = enumerate_sites(roots)
    print("set_epi64x/32/16 call sites:        %d" % every)
    print("assembled from runtime scalars:     %d  <- enumerated population" % len(runtime))
    print("all-literal (constant vectors):     %d" % (every - len(runtime)))
    print()
    for name, count in Counter(os.path.basename(p) for p, _ in runtime).most_common():
        print("  %5d  %s" % (count, name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
