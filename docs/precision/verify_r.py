"""Independently check every rule-R finding, without using the tool.

Rule R has no structural predicate: it reports each call to one of five
registered intrinsics. So "is this a true positive" reduces to a question
that does not need judgement -- is there a real call to that intrinsic at
that file and line, rather than a mention in a comment, a string, or a
preprocessor branch that cannot be taken?

That is checkable, so it is checked here for all 1922 findings rather than
sampled. The point is only useful if the check is independent, so this file
shares nothing with the analyser: it re-parses the source with tree-sitter
from scratch and does not import simde_lint, its lexer, its extractor, or
its alias resolution.

**What this checker claims, exactly.** It does not resolve macros in
general, and an earlier version that tried to was wrong in the direction
that inflates the number: a regex over raw text accepted a `#define` written
inside a block comment, and accepted a body that was one intrinsic call plus
something else. Both would have credited a finding for the wrong reason.

So it claims less. Each finding names the spelling written at its call site
(`raw_name`, absent when the call is direct), and the checker verifies that
exact spelling:

  * a direct finding must have a call to its intrinsic at that line;
  * an aliased finding must have a call to its `raw_name` at that line, and
    `raw_name` must be defined in that file, exactly once, by a `#define`
    whose entire body is a single call to the finding's intrinsic.

Definitions are read from tree-sitter's `preproc_function_def` nodes, so a
`#define` inside a comment or a string is not a definition here -- the
parser has already decided that, and the checker does not second-guess it
with a regex. A name defined more than once is not resolved at all: which
branch is live depends on configuration this file cannot see.

Calls written *inside* a `#define` body stay unconfirmed. Confirming them
means reparsing macro bodies as the analyser does, and a second macro
extractor built to check the first would be the circularity this file
exists to avoid.

    SIMDE_LINT_SVT_AV1=... SIMDE_LINT_VVENC=... \
        uv run python3 docs/precision/verify_r.py

Reports, per finding, one of:

    call        a call to the finding's own intrinsic on that line
    aliased     a call to the finding's raw_name, whose single-call
                `#define` in that file forwards to the intrinsic
    macro       the line is inside a `#define` body; not confirmable here
    comment     the occurrence on that line is inside a comment
    string      the occurrence is inside a string literal
    absent      nothing on that line matches what the finding claims

`call` and `aliased` count as confirmed. Everything else is listed.

**One limit worth naming.** Findings carry a line but not a column, so two
findings of the same spelling on one line cannot be told apart. Neither
corpus has that shape, and the checker would credit both or neither rather
than silently pick one.
"""
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import tree_sitter_cpp
from tree_sitter import Language, Parser

REPO = Path(__file__).resolve().parents[2]
CORPORA = {
    "svt-av1": ("SIMDE_LINT_SVT_AV1", "Source"),
    "vvenc": ("SIMDE_LINT_VVENC", "source/Lib/CommonLib/x86"),
}
LANGUAGE = Language(tree_sitter_cpp.language())
CONFIRMED = ("call", "aliased")


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
        ["uv", "run", "simde-lint", str(path), "--type", "R", "--format", "json"],
        capture_output=True, text=True, cwd=REPO,
    )
    if proc.returncode != 0:
        sys.exit("sweep of %s exited %d: %s" % (path, proc.returncode, proc.stderr))
    return json.loads(proc.stdout)["findings"]


def _calls_in(node, source):
    """Every call expression under `node`, as (function name, node)."""
    found = []
    stack = [node]
    while stack:
        current = stack.pop()
        if current.type == "call_expression":
            fn = current.child_by_field_name("function")
            if fn is not None:
                found.append((source[fn.start_byte:fn.end_byte], current))
        stack.extend(current.children)
    return found


def single_call_defines(root, source, parser):
    """Map a `#define NAME(args)` to the one intrinsic its body calls.

    Definitions are located in the parse tree, not by regex over text: a
    `#define` written inside a comment or a string is not a
    `preproc_function_def`, so it cannot reach this map at all. The parser
    has already decided that question and this does not second-guess it.

    tree-sitter leaves a `#define` body as an opaque `preproc_arg`, so the
    body is reparsed here to see inside it. That is a snippet through the
    same public parser, not the analyser's macro extractor -- the thing this
    file must not borrow is `macros.py`'s alias logic, not the idea of
    parsing.

    The body must be exactly one call and nothing else. `f(x) + 1` has one
    call but is not one; `f(g(x))` is a composition. A name defined more
    than once is dropped whatever its bodies say, since which branch is live
    depends on configuration this file cannot see.
    """
    definitions = {}
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type == "preproc_function_def":
            name_node = node.child_by_field_name("name")
            value = node.child_by_field_name("value")
            if name_node is not None and value is not None:
                name = source[name_node.start_byte:name_node.end_byte].decode()
                body = source[value.start_byte:value.end_byte].strip()
                definitions.setdefault(name, []).append(_sole_callee(body, parser))
        stack.extend(node.children)
    return {
        name: targets[0]
        for name, targets in definitions.items()
        if len(targets) == 1 and targets[0] is not None
    }


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
    calls = _calls_in(tree.root_node, snippet)
    if len(calls) != 1:
        return None
    called, call_node = calls[0]
    # The one call must BE the body, not merely sit inside it: `f(x) + 1`
    # would otherwise pass.
    whole = snippet[call_node.start_byte:call_node.end_byte].strip()
    return called.decode() if whole == stripped else None


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


def classify(tree, source, line, intrinsic, raw_name, defines):
    """What is at `line`, judged against what this finding actually claims."""
    # The spelling the call site is said to use, and what it must resolve to.
    wanted = (raw_name or intrinsic).encode()
    if raw_name and defines.get(raw_name) != intrinsic:
        # The finding says it reached `intrinsic` through `raw_name`, and
        # this checker cannot confirm that forward. Not a contradiction of
        # the tool -- it resolves chains and #if branches this does not.
        return "absent"

    hits = []

    def walk(node):
        if node.start_point[0] + 1 > line or node.end_point[0] + 1 < line:
            return
        if node.type == "comment":
            if wanted in source[node.start_byte:node.end_byte]:
                hits.append("comment")
            return
        if node.type in ("string_literal", "raw_string_literal", "char_literal"):
            if wanted in source[node.start_byte:node.end_byte]:
                hits.append("string")
            return
        if node.type == "preproc_function_def":
            if node.start_point[0] + 1 <= line <= node.end_point[0] + 1:
                if wanted in source[node.start_byte:node.end_byte]:
                    hits.append("macro")
                return
        if node.type == "call_expression":
            fn = node.child_by_field_name("function")
            if (fn is not None
                    and fn.start_point[0] + 1 == line
                    and source[fn.start_byte:fn.end_byte] == wanted):
                hits.append("aliased" if raw_name else "call")
        for child in node.children:
            walk(child)

    walk(tree.root_node)
    for kind in ("call", "aliased", "macro", "comment", "string"):
        if kind in hits:
            return kind
    return "absent"


def main():
    parser = Parser(LANGUAGE)
    parsed = {}
    verdicts = Counter()
    rows, flagged = [], []

    findings = []
    for corpus, (env_var, subdir) in CORPORA.items():
        findings += sweep(corpus_path(env_var, subdir))

    for finding in findings:
        path = finding["file"]
        if path not in parsed:
            source = Path(path).read_bytes()
            tree = parser.parse(source)
            parsed[path] = (tree, source, single_call_defines(tree.root_node, source, parser))
        tree, source, defines = parsed[path]
        verdict = classify(
            tree, source, finding["line"], finding["intrinsic"],
            finding.get("raw_name"), defines,
        )
        verdicts[verdict] += 1
        rows.append({
            "file": path, "line": finding["line"],
            "intrinsic": finding["intrinsic"], "raw_name": finding.get("raw_name"),
            "verdict": verdict,
        })
        if verdict not in CONFIRMED:
            flagged.append((verdict, path, finding["line"], finding["intrinsic"]))

    if "--json" in sys.argv:
        json.dump({"findings": rows}, sys.stdout)
        return

    total = sum(verdicts.values())
    print("rule R findings checked: %d (census, not a sample)\n" % total)
    for verdict, count in verdicts.most_common():
        print("  %-10s %5d  %5.1f%%" % (verdict, count, 100.0 * count / total))
    confirmed = sum(verdicts[k] for k in CONFIRMED)
    print("\nconfirmed true positives: %d / %d = %.2f%%  (%d direct, %d through a local alias)"
          % (confirmed, total, 100.0 * confirmed / total,
             verdicts["call"], verdicts["aliased"]))

    if flagged:
        print("\nnot confirmed by this check -- hand review required:")
        for verdict, path, line, name in flagged:
            print("  %-8s %s:%d  %s" % (verdict, path, line, name))


if __name__ == "__main__":
    main()
