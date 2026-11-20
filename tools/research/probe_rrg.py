"""pilot: run the industry scan for ASX and print the rotation quadrants (20 Nov 2026)"""
import json
import sys
sys.path.insert(0, "tools")
import group_pulse as G
G.main("ASX")
d = json.load(open(G.CFG["ASX"]["out"] + "group_pulse.json"))
for r in d["sectors"]:
    print("R| SECTOR", r["sector"], (r.get("rrg") or {}).get("now"), "<-", (r.get("rrg") or {}).get("wk4"), (r.get("rrg") or {}).get("pts", [])[-1:], "1m", r.get("r1m"))
for r in d["rows"][:8]:
    print("R| GROUP", r["group"], (r.get("rrg") or {}).get("now"), "<-", (r.get("rrg") or {}).get("wk4"), (r.get("rrg") or {}).get("pts", [])[-1:])
print("R| counts", {q: sum(1 for r in d["rows"] if (r.get("rrg") or {}).get("now") == q) for q in ("Leading", "Weakening", "Lagging", "Improving")}, "none", sum(1 for r in d["rows"] if not r.get("rrg")))
