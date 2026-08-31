"""Check every finding against an independent reading of the source.

The tool says a mechanism is present at a call site. This decides the same
question from scratch and reports where the two disagree.

Nothing here is sampled: all findings in both corpora are checked. That is
possible because the codebook's test for a true positive is structural --
"is the named mechanism present at that call site" -- and structure is what
a parser sees. A stratified sample exists to estimate what a census can
simply count.

**Independence.** This file imports no `simde_lint`. It re-parses the
sources with tree-sitter and reimplements each predicate from the rule's
own description, so an agreement means two implementations reached the same
answer rather than one implementation agreeing with itself. It runs the
tool only to obtain the findings under test.

**What it cannot decide.** One of the codebook's verdicts is not
structural: FP-context asks whether a call site is one the mechanism
applies to at all -- whether the file compiles on ARM through SIMDe rather
than being an x86-native path or dead code. That needs the build system,
which neither the tool nor this checker has. It is a property of a file,
not of a finding, and is left to the reader; `--files` lists the distinct
files a corpus's findings touch so the question can be answered once per
file instead of once per finding.

**What it shares with the tool, and therefore cannot catch.** Both read the
same tree-sitter parse. A defect in how the parser handles a construct is
invisible to both at once -- recovery from an ERROR node cost eleven
findings on the holdout corpus and nothing said so. `unparsed_regions` in
the tool covers that half; neither is the whole claim alone.

    SIMDE_LINT_SVT_AV1=... SIMDE_LINT_VVENC=... \
        uv run python3 docs/precision/verify.py
    uv run python3 docs/precision/verify.py --files
    uv run python3 docs/precision/verify.py --json
"""
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

import tree_sitter_cpp
from tree_sitter import Language, Parser

REPO = Path(__file__).resolve().parents[2]
CORPORA = {
    "svt-av1": ("SIMDE_LINT_SVT_AV1", "Source"),
    "vvenc": ("SIMDE_LINT_VVENC", "source/Lib/CommonLib/x86"),
}
LANGUAGE = Language(tree_sitter_cpp.language())
INT_LITERAL = re.compile(r"^[-+~\s(]*(0[xX][0-9a-fA-F]+|\d+)[uUlL]*[\s)]*$")


def corpus_path(env_var, subdir):
    root = os.environ.get(env_var)
    if not root:
        sys.exit("%s is not set; point it at the pinned checkout." % env_var)
    path = Path(root) / subdir
    if not path.is_dir():
        sys.exit("%s does not contain %s: %s" % (env_var, subdir, path))
    return path


def sweep(path):
    proc = subprocess.run(
        ["uv", "run", "simde-lint", str(path), "--format", "json"],
        capture_output=True, text=True, cwd=REPO,
    )
    if proc.returncode != 0:
        sys.exit("sweep of %s exited %d: %s" % (path, proc.returncode, proc.stderr))
    return json.loads(proc.stdout)["findings"]


class Call:
    """One call expression, with what it was assigned to and what it took."""

    __slots__ = ("name", "line", "args", "target", "start", "end")

    def __init__(self, name, line, args, target, start, end):
        self.name = name
        self.line = line
        self.args = args
        self.target = target
        self.start = start
        self.end = end


def _text(source, node):
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _assignment_target(node, source):
    """What this call's result is written to, as written.

    The subscript is kept: `dd[0]` and `dd[1]` are different vectors, and a
    checker that dropped the index would merge two short insert chains into
    one long enough to look like a chain.
    """
    current = node.parent
    while current is not None:
        if current.type == "assignment_expression":
            left = current.child_by_field_name("left")
            return _text(source, left).strip() if left is not None else None
        if current.type == "init_declarator":
            name = current.child_by_field_name("declarator")
            return _text(source, name).strip() if name is not None else None
        if current.type in ("function_definition", "translation_unit"):
            return None
        current = current.parent
    return None


def read_calls(path, parser, cache):
    """Every call in a file, indexed by line and in source order."""
    if path in cache:
        return cache[path]
    source = Path(path).read_bytes()
    tree = parser.parse(source)
    calls = []
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type == "call_expression":
            fn = node.child_by_field_name("function")
            arglist = node.child_by_field_name("arguments")
            if fn is not None and fn.type == "identifier":
                args = []
                if arglist is not None:
                    args = [
                        _text(source, c).strip()
                        for c in arglist.children
                        if c.type not in ("(", ")", ",")
                    ]
                calls.append(Call(
                    _text(source, fn), fn.start_point[0] + 1, args,
                    _assignment_target(node, source), node.start_byte, node.end_byte,
                ))
        stack.extend(node.children)
    calls.sort(key=lambda c: c.start)
    by_line = defaultdict(list)
    for call in calls:
        by_line[call.line].append(call)
    cache[path] = (calls, by_line, source,
                   single_call_defines(tree.root_node, source, parser))
    return cache[path]


def _sole_callee(body, parser):
    """The function a body calls, if the body is exactly that one call."""
    stripped = body.strip()
    while stripped.startswith(b"(") and stripped.endswith(b")"):
        inner = stripped[1:-1].strip()
        if _balanced(inner):
            stripped = inner
        else:
            break
    snippet = b"void _probe_(void) { " + stripped + b"; }"
    tree = parser.parse(snippet)
    calls = []
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type == "call_expression":
            fn = node.child_by_field_name("function")
            if fn is not None:
                calls.append((_text(snippet, fn), node))
        stack.extend(node.children)
    if len(calls) != 1:
        return None
    called, node = calls[0]
    # The one call must BE the body, not merely sit inside it: `f(x) + 1`
    # has one call and is not a forward.
    return called if snippet[node.start_byte:node.end_byte].strip() == stripped else None


def _balanced(text):
    depth = 0
    for byte in text:
        if byte == ord("("):
            depth += 1
        elif byte == ord(")"):
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def single_call_defines(root, source, parser):
    """Map each single-call `#define NAME(args)` to the intrinsic it forwards to.

    Definitions come from `preproc_function_def` nodes, so a `#define`
    written inside a comment or a string is not one -- the parser decided
    that, and this does not second-guess it with a regex. A body must be
    exactly one call: `f(p) + 1` is not a forward and `f(g(p))` is a
    composition. A name defined more than once is dropped, since which
    branch is live depends on configuration this file cannot see.
    """
    definitions = {}
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type == "preproc_function_def":
            name_node = node.child_by_field_name("name")
            value = node.child_by_field_name("value")
            if name_node is not None and value is not None:
                name = _text(source, name_node)
                body = source[value.start_byte:value.end_byte].strip()
                definitions.setdefault(name, []).append(_sole_callee(body, parser))
        stack.extend(node.children)
    return {
        name: targets[0]
        for name, targets in definitions.items()
        if len(targets) == 1 and targets[0] is not None
    }


def _uses(call, name):
    """Whether `name` appears as an operand of this call, at any depth.

    Depth matters: `_mm_add_epi32(_mm_add_epi32(res_0, res_2), x)` consumes
    res_0, and a check that only looked at the outer arguments would call
    that a false positive.
    """
    if name is None:
        return False
    pattern = re.compile(r"\b%s\b" % re.escape(name))
    return any(pattern.search(arg) for arg in call.args)


# Each checker returns (ok, detail). `ok` is None when the claim's own text
# could not be read -- that is a defect in this file, not a disagreement, and
# is reported separately so it cannot be mistaken for one.

def check_name_only(finding, ctx):
    """R and S: the named intrinsic is called at the reported line.

    Neither rule has a structural premise. R reports every call to one of
    five registered intrinsics; S reports every shuffle call, and grades it
    on the mask afterwards. So the claim reduces to the call being there,
    under the spelling the finding records.
    """
    _, by_line, _, defines = ctx
    raw = finding.get("raw_name")
    wanted = raw or finding["intrinsic"]
    if not any(c.name == wanted for c in by_line.get(finding["line"], [])):
        return False, "no call to %s at this line" % wanted
    if raw and raw != finding["intrinsic"]:
        # The finding says it reached the intrinsic through this spelling.
        # Taking that on trust would be checking the tool with the tool.
        if defines.get(raw) != finding["intrinsic"]:
            return False, ("%s is called here, but no single-call #define in "
                           "this file forwards it to %s" % (raw, finding["intrinsic"]))
        return True, "call to %s, forwarded to %s by a local #define" % (raw, wanted)
    return True, "call to %s present" % wanted


def check_fusion(finding, ctx):
    """F: the multiply's result is an operand of the add the claim names."""
    _, by_line, _, _ = ctx
    match = re.search(r"at line (\d+) reaches (\S+) at line (\d+)", finding["rationale"])
    if not match:
        return None, "claim not parsed"
    add_name, add_line = match.group(2), int(match.group(3))
    muls = [c for c in by_line.get(finding["line"], [])
            if c.name == (finding.get("raw_name") or finding["intrinsic"])]
    if not muls:
        return False, "no multiply at this line"
    adds = [c for c in by_line.get(add_line, []) if c.name == add_name]
    if not adds:
        return False, "no %s at line %d" % (add_name, add_line)
    for mul in muls:
        if mul.target and any(_uses(a, mul.target) for a in adds):
            return True, "%s reaches %s at %d" % (mul.target, add_name, add_line)
    # A widening hop is a claim about an intermediate, named in the rationale.
    hop = re.search(r"through (\S+) at line (\d+)", finding["rationale"])
    if hop:
        hops = [c for c in by_line.get(int(hop.group(2)), []) if c.name == hop.group(1)]
        for mul in muls:
            for h in hops:
                if mul.target and _uses(h, mul.target) and h.target \
                        and any(_uses(a, h.target) for a in adds):
                    return True, "reaches through %s" % hop.group(1)
    return False, "the multiply's result is not an operand of that add"


def check_widening(finding, ctx):
    """W: mullo and mulhi share operands and both feed the unpack."""
    _, by_line, _, _ = ctx
    match = re.search(
        r"at line (\d+) and (\S+) at line (\d+) share operands and feed (\S+) at line (\d+)",
        finding["rationale"])
    if not match:
        return None, "claim not parsed"
    hi_name, hi_line = match.group(2), int(match.group(3))
    unpack_name, unpack_line = match.group(4), int(match.group(5))
    los = [c for c in by_line.get(finding["line"], []) if c.name == finding["intrinsic"]]
    his = [c for c in by_line.get(hi_line, []) if c.name == hi_name]
    unpacks = [c for c in by_line.get(unpack_line, []) if c.name == unpack_name]
    if not (los and his and unpacks):
        return False, "one of the three calls is not where the claim puts it"
    for lo in los:
        for hi in his:
            if lo.args != hi.args:
                continue
            for unpack in unpacks:
                if _uses(unpack, lo.target) and _uses(unpack, hi.target):
                    return True, "shared operands %s, both feed %s" % (lo.args, unpack_name)
    return False, "operands differ, or the unpack does not take both results"


def check_pipeline(finding, ctx):
    """P: the compare's result is consumed by the next call, nothing between."""
    calls, by_line, _, _ = ctx
    match = re.search(r"is consumed by (\S+) at line (\d+)", finding["rationale"])
    if not match:
        return None, "claim not parsed"
    use_name, use_line = match.group(1), int(match.group(2))
    cmps = [c for c in by_line.get(finding["line"], [])
            if c.name == (finding.get("raw_name") or finding["intrinsic"])]
    uses = [c for c in by_line.get(use_line, []) if c.name == use_name]
    if not (cmps and uses):
        return False, "compare or consumer is not where the claim puts it"
    for cmp_call in cmps:
        for use in uses:
            if not _uses(use, cmp_call.target):
                continue
            between = [c for c in calls
                       if cmp_call.end <= c.start < use.start and c is not use
                       and not (use.start <= c.start and c.end <= use.end)]
            if between:
                return False, "independent work between them: %s" % (
                    ", ".join(sorted({c.name for c in between}))[:60])
            return True, "consumed by %s with nothing between" % use_name
    return False, "the consumer does not take the compare's result"


def check_insert_chain(finding, ctx):
    """M chain: enough inserts on ONE target, counted with the subscript kept.

    `dd[0]` and `dd[1]` are different vectors. A chain is what a single lane
    load would replace, so inserts into different array elements are
    different chains however adjacent they are in the source.
    """
    calls, _, _, _ = ctx
    match = re.search(r"(\d+) scalar inserts assemble (\S+) between lines (\d+) and (\d+)",
                      finding["rationale"])
    if not match:
        return None, "claim not parsed"
    claimed, name, first, last = (int(match.group(1)), match.group(2),
                                  int(match.group(3)), int(match.group(4)))
    runs = Counter()
    for call in calls:
        if "insert" not in call.name or not (first <= call.line <= last):
            continue
        # The claim names an assignment target; match it as one. A prefix
        # match would let `dd` collect `dd[0]` and `dd[1]` alike, which is
        # the merge this check exists to detect.
        if call.target and (call.target == name
                            or call.target.split("[")[0] == name.split("[")[0]):
            runs[call.target] += 1
    if not runs:
        return False, "no inserts on %s in that span" % name
    longest = max(runs.values())
    threshold = 3
    if longest < threshold:
        return False, ("claimed %d on %s, but they split across %s -- longest single "
                       "target is %d, below the threshold of %d"
                       % (claimed, name, dict(runs), longest, threshold))
    if len(runs) > 1:
        return True, ("chain present on %s, though the claimed %d spans %s"
                      % (max(runs, key=runs.get), claimed, dict(runs)))
    return True, "%d inserts on %s" % (longest, next(iter(runs)))


def check_set_build(finding, ctx):
    """M build: a set_epi* whose operands are runtime values, not literals."""
    _, by_line, _, _ = ctx
    builds = [c for c in by_line.get(finding["line"], [])
              if c.name == (finding.get("raw_name") or finding["intrinsic"])]
    if not builds:
        return False, "no %s at this line" % finding["intrinsic"]
    for build in builds:
        runtime = [a for a in build.args if not INT_LITERAL.match(a)]
        if runtime:
            claimed = re.search(r"assembles (\d+) runtime scalars", finding["rationale"])
            if claimed and int(claimed.group(1)) != len(runtime):
                return True, ("built from runtime scalars, though %s of the %s operands "
                              "are literals" % (len(build.args) - len(runtime),
                                                len(build.args)))
            return True, "%d runtime operands" % len(runtime)
    return False, "every operand is a literal"


CHECKS = {
    "R.zero_init_partial_load": check_name_only,
    "S.pshufb_guard": check_name_only,
    "F.mul_add_no_fuse": check_fusion,
    "W.mul16_widen_roundtrip": check_widening,
    "P.cmp_immediate_use": check_pipeline,
    "M.scalar_insert_chain": check_insert_chain,
    "M.scalar_set_build": check_set_build,
}


def main():
    parser = Parser(LANGUAGE)
    cache = {}
    findings = []
    for corpus, (env_var, subdir) in CORPORA.items():
        findings += sweep(corpus_path(env_var, subdir))

    if "--files" in sys.argv:
        # FP-context is a property of a file, so it is asked once per file.
        per_file = Counter(f["file"] for f in findings)
        print("%d findings across %d files. FP-context is decided per file, "
              "not per finding.\n" % (len(findings), len(per_file)))
        for path, count in sorted(per_file.items(), key=lambda kv: -kv[1]):
            print("  %5d  %s" % (count, path))
        return

    rows, disagree, unparsed_claims = [], [], []
    tally = Counter()
    for finding in findings:
        if finding.get("scope") == "macro":
            # Judged against the macro body, which this file does not reparse.
            tally["macro"] += 1
            rows.append(dict(finding, verdict="macro", detail="inside a #define body"))
            continue
        ctx = read_calls(finding["file"], parser, cache)
        ok, detail = CHECKS[finding["rule"]](finding, ctx)
        verdict = {True: "agree", False: "disagree", None: "unreadable"}[ok]
        tally[verdict] += 1
        row = dict(finding, verdict=verdict, detail=detail)
        rows.append(row)
        if ok is False:
            disagree.append(row)
        elif ok is None:
            unparsed_claims.append(row)

    if "--json" in sys.argv:
        json.dump({"findings": rows}, sys.stdout)
        return

    total = sum(tally.values())
    print("findings checked: %d (census, not a sample)\n" % total)
    for verdict, count in tally.most_common():
        print("  %-12s %6d  %5.1f%%" % (verdict, count, 100.0 * count / total))
    checked = tally["agree"] + tally["disagree"]
    if checked:
        print("\nagreement on structurally checkable findings: %d / %d = %.2f%%"
              % (tally["agree"], checked, 100.0 * tally["agree"] / checked))

    by_rule = Counter(r["rule"] for r in disagree)
    if by_rule:
        print("\ndisagreements by rule:")
        for rule, count in by_rule.most_common():
            print("  %-26s %d" % (rule, count))
    if disagree:
        print("\nEvery disagreement, for review:")
        for row in disagree:
            print("  %s:%d  %s" % (row["file"], row["line"], row["rule"]))
            print("      %s" % row["detail"])
    if unparsed_claims:
        print("\n%d claim(s) this checker could not read -- its own gap, not a "
              "disagreement:" % len(unparsed_claims))
        for row in unparsed_claims[:10]:
            print("  %s:%d  %s" % (row["file"], row["line"], row["rule"]))


if __name__ == "__main__":
    main()
