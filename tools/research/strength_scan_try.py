"""dry run of tools/strength_scan.py on the research runner (prints a summary; nothing committed)."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import strength_scan as S  # noqa: E402

S.main()
d = json.load(open(S.OUT))
print("R| asof", d["asof"], "gate", d["gate"], "stocks", len(d["s"]), "size", os.path.getsize(S.OUT))
for k in ("LAURUSLABS", "TITAN", "RADICO", "TFCILTD", "RELIANCE"):
    print("R|", k, d["s"].get(k))
for r in d["rows"][:12]:
    print("R| row", json.dumps(r))
