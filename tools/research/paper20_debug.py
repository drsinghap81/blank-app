"""Debug for tools/paper20.py (26 Nov 2026): GOLDBEES / INR closes since 2 Nov and why the Pulse replay picks nothing."""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import paper20 as P  # noqa: E402

C, O, V = P.download(["GOLDBEES.NS", "INR=X", "^NSEI", "KOTAKBANK.NS", "ICICIBANK.NS"])
print("R| closes", C.loc["2026-11-02":].round(2).to_string().replace("\n", " || "))
print("R| opens", O.loc["2026-11-02":, ["GOLDBEES.NS"]].round(2).to_string().replace("\n", " || "))
print("R| volume nan share", V.isna().mean().round(2).to_dict())
G = json.load(open("data/scan/group_pulse.json"))
IND = {}
for r in (G.get("nse") or {}).get("rows") or []:
    liq = [m["symbol"] for m in r["members"] if m.get("liquid")]
    if len(liq) >= 3:
        IND[r["basic"]] = liq
syms = sorted({s for v in IND.values() for s in v})[:300]
C, O, V = P.download([s + ".NS" for s in syms] + ["^NSEI"])
C.columns = [c.replace(".NS", "") for c in C.columns]; V.columns = [c.replace(".NS", "") for c in V.columns]
nifty = C["^NSEI"].ffill(); cols = [s for s in syms if s in C.columns]
print("R| C shape", C.shape, "V nan", round(float(V[cols].isna().mean().mean()), 3), "index", C.index[:2].tolist(), C.index[-2:].tolist())
liq = ((C[cols] * V[cols]).rolling(60, min_periods=40).median() >= P.MINVAL) & (C[cols] >= P.MINPX)
print("R| liquid share last day", round(float(liq.iloc[-1].mean()), 3))
IND2 = {k: [s for s in v if s in cols] for k, v in IND.items()}
PP = P.pulse_picks(C[cols], V[cols], nifty, {k: v for k, v in IND2.items() if len(v) >= 3})
print("R| picks", {str(k.date()): v for k, v in PP.items()})
