"""Population-weighted precision and a defensible interval for it.

The sample is stratified by (rule, evidence) with unequal allocation, so a
pooled binomial interval over the whole sample is not valid: it would treat
a stratum holding half the population and a stratum holding three findings
as equally informative. It also disagrees with the point estimate, which is
population-weighted.

What this computes instead:

    p_hat = sum_h W_h * p_hat_h                     W_h = N_h / N

and, for the lower bound, a per-stratum Wilson bound at level 1 - alpha/H
(Bonferroni over the H strata) combined with the same weights:

    L = sum_h W_h * L_h

The design-based variance is not usable here: every stratum came back at
p_hat_h = 1, which makes the sample variance exactly zero and the resulting
interval a point. The Bonferroni-weighted bound stays finite at p_hat = 1,
holds simultaneously over the strata, and is conservative -- it is the
honest answer to "what does this sample actually support", not the smallest
number that can be defended.

    python3 docs/precision/estimate.py
"""
import json
import math
import statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent
ALPHA = 0.05


def wilson_lower(successes, n, alpha):
    if n == 0:
        return 0.0
    z = abs(statistics.NormalDist().inv_cdf(alpha / 2))
    p = successes / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (centre - margin) / denom)


def main():
    sample = json.loads((HERE / "sample.json").read_text())
    verdicts_path = HERE / "verdicts.json"
    if not verdicts_path.exists():
        raise SystemExit(
            "docs/precision/verdicts.json does not exist yet.\n"
            "The sample is drawn but not judged; see HOWTO-judge.md."
        )
    verdicts = json.loads(verdicts_path.read_text())["verdicts"]

    missing = [
        str(i) for i in range(1, len(sample["sample"]) + 1) if str(i) not in verdicts
    ]
    if missing:
        raise SystemExit(
            "%d of %d findings have no verdict (first: %s).\n"
            "Judging half a stratum and weighting it as if whole would "
            "misstate the interval, so this refuses to guess."
            % (len(missing), len(sample["sample"]), ", ".join(missing[:8]))
        )

    sizes = sample["stratum_sizes"]
    N = sample["population"]
    H = len(sizes)

    # The verdict vocabulary is the codebook's, fixed before the sample was
    # drawn: TP, three kinds of false positive, and UNJUDGED.
    #
    # UNJUDGED is a third answer, not a failure. Counting it as a false
    # positive would charge the tool for what the source does not settle;
    # counting it as TP would credit it with the same. It leaves the
    # stratum's denominator and is reported separately, so a reader can see
    # how much of the sample it took.
    #
    # The FP kinds are collapsed for the interval -- an incorrect finding is
    # incorrect however it went wrong -- but counted separately below,
    # because which kind dominates says something the rate does not.
    FALSE = ("FP-shape", "FP-context", "FP-knowledge")
    drawn, tp, unjudged = {}, {}, {}
    kinds = {}
    for i, finding in enumerate(sample["sample"], 1):
        key = "%s|%s" % (finding["rule"], finding["evidence"])
        verdict = verdicts[str(i)]
        if verdict == "UNJUDGED":
            unjudged[key] = unjudged.get(key, 0) + 1
            continue
        if verdict != "TP" and verdict not in FALSE:
            raise SystemExit(
                "finding %d has verdict %r; expected TP, %s or UNJUDGED"
                % (i, verdict, ", ".join(FALSE))
            )
        if verdict != "TP":
            kinds[verdict] = kinds.get(verdict, 0) + 1
        drawn[key] = drawn.get(key, 0) + 1
        tp[key] = tp.get(key, 0) + (verdict == "TP")

    print("population %d, strata %d, sample %d, alpha %.3f "
          "(per-stratum %.5f, Bonferroni over %d)"
          % (N, H, sum(drawn.values()), ALPHA, ALPHA / H, H))
    print("\n%-32s %6s %5s %5s %8s %9s" %
          ("stratum", "pop", "n", "TP", "prec", "lower"))
    print("-" * 70)

    point = lower = 0.0
    for key in sorted(sizes, key=lambda k: -sizes[k]):
        n, k, w = drawn.get(key, 0), tp.get(key, 0), sizes[key] / N
        if n == 0:
            print("%-32s %6d %5s %5s %8s %9s"
                  % (key.replace("|", " / "), sizes[key], "-", "-", "-", "-"))
            continue
        p_h = k / n
        l_h = wilson_lower(k, n, ALPHA / H)
        point += w * p_h
        lower += w * l_h
        print("%-32s %6d %5d %5d %7.1f%% %8.1f%%"
              % (key.replace("|", " / "), sizes[key], n, k, 100 * p_h, 100 * l_h))

    print("-" * 70)
    print("%-32s %6d %5d %5d %7.1f%% %8.1f%%"
          % ("population-weighted", N, sum(drawn.values()), sum(tp.values()),
             100 * point, 100 * lower))
    print("\nprecision %.1f%%, simultaneous 95%% lower bound %.1f%%"
          % (100 * point, 100 * lower))
    if kinds:
        print("\nfalse positives by kind:")
        for kind in sorted(kinds, key=lambda k: -kinds[k]):
            print("  %-16s %d" % (kind, kinds[kind]))
    if unjudged:
        total_unjudged = sum(unjudged.values())
        print("\n%d finding(s) were UNJUDGED and left the denominator:"
              % total_unjudged)
        for key in sorted(unjudged, key=lambda k: -unjudged[k]):
            print("  %-32s %d" % (key.replace("|", " / "), unjudged[key]))
        print("The estimate above is conditional on a finding being judgeable "
              "from source.")


if __name__ == "__main__":
    main()
