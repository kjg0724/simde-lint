"""Fill in the rule-R verdicts from the census, so they are not judged twice.

Rule R's stratum is settled by `verify_r.py`, which checks all 1922 findings
rather than the 25 that happen to be sampled. Asking a human to re-judge
those 25 by hand would not add information -- it would substitute a smaller,
weaker instrument for a larger one, and risk disagreeing with it.

So this writes their verdicts from the census's own classification and
leaves every other stratum untouched. It never overwrites a verdict that is
already there: a human judgement wins over this script, always.

    python3 docs/precision/seed_r_verdicts.py
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIRMED = ("call", "aliased")


def main():
    sample = json.loads((HERE / "sample.json").read_text())["sample"]
    verdicts_path = HERE / "verdicts.json"
    document = (
        json.loads(verdicts_path.read_text()) if verdicts_path.exists() else {"verdicts": {}}
    )
    verdicts = document.setdefault("verdicts", {})

    proc = subprocess.run(
        [sys.executable, str(HERE / "verify_r.py"), "--json"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        sys.exit("verify_r.py exited %d: %s" % (proc.returncode, proc.stderr))
    census = {
        (row["file"], row["line"], row["intrinsic"]): row["verdict"]
        for row in json.loads(proc.stdout)["findings"]
    }

    written = skipped = 0
    for index, finding in enumerate(sample, 1):
        if not finding["rule"].startswith("R."):
            continue
        if str(index) in verdicts:
            skipped += 1
            continue
        key = (finding["file"], finding["line"], finding["intrinsic"])
        if key not in census:
            sys.exit("finding %d is not in the census; sample and sweep disagree" % index)
        verdicts[str(index)] = "TP" if census[key] in CONFIRMED else "UNJUDGED"
        written += 1

    document["rule_r_source"] = "verify_r.py census over all rule-R findings"
    verdicts_path.write_text(json.dumps(document, indent=2) + "\n")
    print("wrote %d rule-R verdicts, left %d already-judged alone" % (written, skipped))
    print("%d of %d findings still need a verdict"
          % (len(sample) - len(verdicts), len(sample)))


if __name__ == "__main__":
    main()
