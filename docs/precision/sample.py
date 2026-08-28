"""Draw the stratified precision sample from the pinned revisions.

Sampling is by (rule, evidence) so that a rule contributing 1816 findings and
one contributing 1 both get looked at, and so that grade C -- where the tool
says least -- is not crowded out by grade A. Precision is reported per rule
and re-weighted to the population, never as a raw sample average.

    python3 docs/precision/sample.py --out docs/precision/sample.json
"""
import argparse, json, random, subprocess, sys
from collections import defaultdict
from pathlib import Path

CORPORA = {
    "svt-av1": "/Users/solario/Solario/Solido/open-source/svt-av1/Source",
    "vvenc": "/Users/solario/Solario/Solido/open-source/vvenc/source/Lib/CommonLib/x86",
}
PER_STRATUM = 3


def sweep(path):
    out = subprocess.run(
        ["uv", "run", "simde-lint", path, "--format", "json"],
        capture_output=True, text=True,
        cwd="/Users/solario/Solario/Solido/open-source/simde-lint",
    ).stdout
    return json.loads(out)["findings"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    pop, strata = [], defaultdict(list)
    for corpus, path in CORPORA.items():
        for f in sweep(path):
            f["corpus"] = corpus
            pop.append(f)
            strata[(f["rule"], f["evidence"])].append(f)

    random.seed(args.seed)
    sample = []
    for key in sorted(strata):
        rows = strata[key]
        sample += random.sample(rows, min(PER_STRATUM, len(rows)))

    print("population %d, strata %d, sample %d\n" % (len(pop), len(strata), len(sample)))
    print("%-28s %6s %8s %7s" % ("stratum", "pop", "sampled", "share"))
    print("-" * 54)
    for key in sorted(strata):
        n = len(strata[key])
        k = min(PER_STRATUM, n)
        print("%-28s %6d %8d %6.1f%%" % ("%s / %s" % key, n, k, 100.0 * n / len(pop)))

    json.dump(
        {
            "seed": args.seed,
            "per_stratum": PER_STRATUM,
            "population": len(pop),
            "stratum_sizes": {"%s|%s" % k: len(v) for k, v in sorted(strata.items())},
            "sample": sample,
        },
        open(args.out, "w"), indent=2,
    )
    print("\nwrote %s" % args.out)


if __name__ == "__main__":
    main()
