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

One shape is resolved here rather than deferred, with its own much simpler
predicate: a file-local `#define NAME(args) TARGET(...)` whose body is a
single call. That is a dozen lines of regex over the file's own text, not a
second copy of the analyser's agreement logic, so a call site reached
through such an alias can be credited without the check borrowing anything
it is supposed to be independent of. SVT-AV1's `ssim_avx2.c` defines two of
them under `#ifndef` guards.

Calls written *inside* a `#define` body are a different matter and stay
uncredited. Confirming those means reparsing macro bodies the way the
analyser does, and building a second macro extractor to check the first
would be exactly the circularity this file exists to avoid. They are listed
instead.

    SIMDE_LINT_SVT_AV1=... SIMDE_LINT_VVENC=... \
        uv run python3 docs/precision/verify_r.py

Reports, per finding, one of:

    call        a call expression to the named intrinsic on that line
    aliased     a call through a single-call `#define` resolving to it
    macro       the line is inside a `#define` body; not confirmable here
    comment     the occurrence on that line is inside a comment
    string      the occurrence is inside a string literal
    absent      no occurrence of the name on that line at all

`call` and `aliased` count as confirmed. `macro`, `comment`, `string` and
`absent` are listed rather than credited.
"""
import json
import os
import re
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

# `#define NAME(args) TARGET(...)` where the body is one call. Deliberately
# narrow: it does not follow chains, does not check that the parameters are
# used, and gives up on anything else. It only has to be right about the
# shape it claims, and a wider predicate would start to resemble the thing
# it is checking.
_SINGLE_CALL_DEFINE = re.compile(
    r"^\s*#\s*define\s+(?P<name>_mm[A-Za-z0-9_]*)\s*\([^)]*\)\s*"
    r"(?P<target>_mm[A-Za-z0-9_]*)\s*\(",
    re.MULTILINE,
)


def local_aliases(source: bytes) -> dict[str, str]:
    """Map each single-call `#define` name to the intrinsic it forwards to."""
    text = source.decode("utf-8", errors="replace")
    aliases: dict[str, str] = {}
    for match in _SINGLE_CALL_DEFINE.finditer(text):
        name, target = match.group("name"), match.group("target")
        if name != target:
            aliases[name] = target
    return aliases


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


def classify(tree, source, line, name, aliases):
    """What is at `line` in this file, judged from the parse tree alone."""
    target = name.encode()
    # Spellings that reach this intrinsic: itself, plus any single-call
    # `#define` in this file that forwards to it.
    spellings = {target} | {
        alias.encode() for alias, resolved in aliases.items() if resolved == name
    }
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
        if node.type == "preproc_function_def":
            # A call written inside a #define body. Confirming it needs the
            # body reparsed, which is the analyser's job and not this
            # file's; say so rather than guess.
            if node.start_point[0] + 1 <= line <= node.end_point[0] + 1:
                if target in source[node.start_byte:node.end_byte]:
                    hits.append("macro")
                return
        if node.type == "call_expression":
            fn = node.child_by_field_name("function")
            if fn is not None and fn.start_point[0] + 1 == line:
                spelling = source[fn.start_byte:fn.end_byte]
                if spelling == target:
                    hits.append("call")
                elif spelling in spellings:
                    hits.append("aliased")
        for child in node.children:
            walk(child)

    walk(tree.root_node)
    for kind in ("call", "aliased", "macro", "comment", "string"):
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
            trees[path] = (parser.parse(source), source, local_aliases(source))
        tree, source, aliases = trees[path]
        verdict = classify(tree, source, finding["line"], finding["intrinsic"], aliases)
        verdicts[verdict] += 1
        if verdict not in ("call", "aliased"):
            flagged.append((verdict, path, finding["line"], finding["intrinsic"]))

    total = sum(verdicts.values())
    print("rule R findings checked: %d (census, not a sample)\n" % total)
    for verdict, count in verdicts.most_common():
        print("  %-10s %5d  %5.1f%%" % (verdict, count, 100.0 * count / total))
    confirmed = verdicts["call"] + verdicts["aliased"]
    print("\nconfirmed true positives: %d / %d = %.2f%%  (%d direct, %d through a local alias)"
          % (confirmed, total, 100.0 * confirmed / total, verdicts["call"], verdicts["aliased"]))

    if flagged:
        print("\nnot confirmed by this check -- hand review required:")
        for verdict, path, line, name in flagged:
            print("  %-8s %s:%d  %s" % (verdict, path, line, name))


if __name__ == "__main__":
    main()
