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
its alias resolution. A finding the tool reached only through a file-local
`#define` alias will therefore NOT match a direct call here and is reported
as `alias` rather than as a hit -- those are listed for hand review instead
of being silently credited.

    SIMDE_LINT_SVT_AV1=... SIMDE_LINT_VVENC=... \
        uv run python3 docs/precision/verify_r.py

Reports, per finding, one of:

    call        a call expression to the named intrinsic on that line
    alias       the line calls something else; needs hand review
    comment     the occurrence on that line is inside a comment
    string      the occurrence is inside a string literal
    absent      no occurrence of the name on that line at all

Only `call` counts as a confirmed true positive. Everything else is listed.
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


def classify(tree, source, line, name):
    """What is at `line` in this file, judged from the parse tree alone."""
    target = name.encode()
    hits = []

    def walk(node):
        if node.start_point[0] + 1 > line or node.end_point[0] + 1 < line:
            return
        if node.type in ("comment",):
            if target in source[node.start_byte:node.end_byte]:
                hits.append("comment")
            return
        if node.type in ("string_literal", "raw_string_literal", "char_literal"):
            if target in source[node.start_byte:node.end_byte]:
                hits.append("string")
            return
        if node.type == "call_expression":
            fn = node.child_by_field_name("function")
            if (fn is not None
                    and fn.start_point[0] + 1 == line
                    and source[fn.start_byte:fn.end_byte] == target):
                hits.append("call")
        for child in node.children:
            walk(child)

    walk(tree.root_node)
    if "call" in hits:
        return "call"
    for kind in ("comment", "string"):
        if kind in hits:
            return kind
    line_text = source.split(b"\n")[line - 1] if line - 1 < source.count(b"\n") + 1 else b""
    return "alias" if target in line_text else "absent"


def main():
    parser = Parser(LANGUAGE)
    trees = {}
    verdicts = Counter()
    flagged = []

    findings = []
    for corpus, (env_var, subdir) in CORPORA.items():
        findings += sweep(corpus_path(env_var, subdir))

    for finding in findings:
        path = finding["file"]
        if path not in trees:
            source = Path(path).read_bytes()
            trees[path] = (parser.parse(source), source)
        tree, source = trees[path]
        verdict = classify(tree, source, finding["line"], finding["intrinsic"])
        verdicts[verdict] += 1
        if verdict != "call":
            flagged.append((verdict, path, finding["line"], finding["intrinsic"]))

    total = sum(verdicts.values())
    print("rule R findings checked: %d (census, not a sample)\n" % total)
    for verdict, count in verdicts.most_common():
        print("  %-10s %5d  %5.1f%%" % (verdict, count, 100.0 * count / total))
    print("\nconfirmed true positives: %d / %d = %.2f%%"
          % (verdicts["call"], total, 100.0 * verdicts["call"] / total))

    if flagged:
        print("\nnot confirmed by this check -- hand review required:")
        for verdict, path, line, name in flagged:
            print("  %-8s %s:%d  %s" % (verdict, path, line, name))


if __name__ == "__main__":
    main()
