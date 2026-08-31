"""Print each sampled finding with the source around it, for hand judging."""
import json, sys
from pathlib import Path

d = json.load(open("docs/precision/sample.json"))
lo, hi = (int(sys.argv[1]), int(sys.argv[2])) if len(sys.argv) > 2 else (0, 999)
ctx = int(sys.argv[3]) if len(sys.argv) > 3 else 5

for i, f in enumerate(d["sample"], 1):
    if not (lo <= i <= hi):
        continue
    print("=" * 74)
    print("#%d  %s / %s  %s" % (i, f["rule"], f["evidence"], f.get("reason") or ""))
    print("   %s:%d  %s  in %s" % (f["file"].split("/")[-1], f["line"],
                                   f["intrinsic"], f.get("function") or f.get("macro")))
    print("   claim: %s" % f["rationale"][:190])
    try:
        lines = Path(f["file"]).read_text(errors="replace").splitlines()
    except Exception as e:
        print("   !! %s" % e); continue
    a, b = max(0, f["line"] - ctx - 1), min(len(lines), f["line"] + ctx)
    for n in range(a, b):
        print("   %s%5d| %s" % (">" if n + 1 == f["line"] else " ", n + 1, lines[n][:110]))
    print()
