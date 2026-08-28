"""Draw the stratified precision sample from the pinned revisions.

Sampling is by (rule, evidence) so that a rule contributing 1816 findings and
one contributing 1 both get looked at, and so that grade C -- where the tool
says least -- is not crowded out by grade A. Precision is reported per rule
and re-weighted to the population, never as a raw sample average.

    python3 docs/precision/sample.py --out docs/precision/sample.json
"""
import argparse, json, os, random, subprocess, sys
from collections import defaultdict
from pathlib import Path

# Checkout locations come from the environment, never from a default path.
# A baked-in default would publish one machine's directory layout and would
# silently sweep the wrong tree on anyone else's. Same contract as
# tests/test_verification.py.
CORPORA = {
    "svt-av1": ("SIMDE_LINT_SVT_AV1", "Source"),
    "vvenc": ("SIMDE_LINT_VVENC", "source/Lib/CommonLib/x86"),
}
# Allocation. Equal allocation across strata answers "does each rule and
# grade behave", but it cannot carry a population-level precision claim: a
# stratum holding half the findings and a stratum holding three of them
# would contribute the same evidence. Strata at or above LARGE_STRATUM get
# LARGE_N so that the population-weighted interval is driven by the strata
# that actually dominate the population; the rest are censused or get
# SMALL_N, which is enough to catch a rule that is wrong everywhere.
LARGE_STRATUM = 100
LARGE_N = 25
SMALL_N = 5
REPO = Path(__file__).resolve().parents[2]


def allocate(stratum_size):
    return min(stratum_size, LARGE_N if stratum_size >= LARGE_STRATUM else SMALL_N)


def corpus_path(env_var, subdir):
    root = os.environ.get(env_var)
    if not root:
        sys.exit(f"{env_var} is not set; point it at the pinned checkout.")
    path = Path(root) / subdir
    if not path.is_dir():
        sys.exit(f"{env_var} does not contain {subdir}: {path}")
    return path


def sweep(path):
    proc = subprocess.run(
        ["uv", "run", "simde-lint", str(path), "--format", "json"],
        capture_output=True, text=True, cwd=REPO,
    )
    if proc.returncode != 0:
        sys.exit(f"sweep of {path} exited {proc.returncode}: {proc.stderr}")
    return json.loads(proc.stdout)["findings"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    pop, strata = [], defaultdict(list)
    for corpus, (env_var, subdir) in CORPORA.items():
        for f in sweep(corpus_path(env_var, subdir)):
            f["corpus"] = corpus
            pop.append(f)
            strata[(f["rule"], f["evidence"])].append(f)

    random.seed(args.seed)
    sample = []
    for key in sorted(strata):
        rows = strata[key]
        sample += random.sample(rows, allocate(len(rows)))

    print("population %d, strata %d, sample %d\n" % (len(pop), len(strata), len(sample)))
    print("%-30s %6s %8s %7s" % ("stratum", "pop", "sampled", "share"))
    print("-" * 56)
    for key in sorted(strata, key=lambda k: -len(strata[k])):
        n = len(strata[key])
        print("%-30s %6d %8d %6.1f%%" % ("%s / %s" % key, n, allocate(n), 100.0 * n / len(pop)))

    json.dump(
        {
            "seed": args.seed,
            "large_stratum": LARGE_STRATUM,
            "large_n": LARGE_N,
            "small_n": SMALL_N,
            "population": len(pop),
            "stratum_sizes": {"%s|%s" % k: len(v) for k, v in sorted(strata.items())},
            "sample": sample,
        },
        open(args.out, "w"), indent=2,
    )
    print("\nwrote %s" % args.out)


if __name__ == "__main__":
    main()
