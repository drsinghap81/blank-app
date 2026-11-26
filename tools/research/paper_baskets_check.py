"""Dry check of the basket paper books (26 Nov 2026): runs tools/paper20.py with the basket start moved back to 17 Nov and the
output written to /tmp, then prints each basket's summary. Nothing is committed."""
import json
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, ".."))
import paper20 as P  # noqa: E402

P.B_START = pd.Timestamp("2026-11-17"); P.OUT_REAL = P.OUT; P.OUT = "/tmp/paper20_check.json"
P.main()
J = json.load(open(P.OUT))
B = J.get("baskets") or {}
print("R| baskets start", B.get("start"), "pending", B.get("pending"), flush=True)
for k, b in (B.get("books") or {}).items():
    print("R|", k, b["name"], json.dumps(b["summary"]), "| last log:", " / ".join(l["t"] for l in b["log"][:4]), flush=True)
