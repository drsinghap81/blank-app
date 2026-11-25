"""25 Nov 2026 (Amritpal: "my portfolio has given up all gains but the market is up - see what's up today and did our systems ever
track them"): every liquid NSE stock's move today (Yahoo, ~15 min delayed) vs the previous close, and for the biggest gainers
whether the app had them on any list (plan buys / watch, ATH near / breakouts / day closes, flags, VCP, bottom patterns, the
forward-test log, Today's calls). Prints R| lines for all stocks (the app's own data only - no account data)."""
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from global_universe import symbols  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
def J(p):
    try:
        return json.load(open(p))
    except Exception:  # noqa: BLE001
        return {}
TAG = {}
def tag(s, t):
    TAG.setdefault(s, []).append(t)
P = J("data/scan/trade_plan.json")
for r in (P.get("top") or []) + (P.get("swing") or []):
    tag(r["symbol"], f"plan:{r.get('system')}")
for r in P.get("watch") or []:
    tag(r.get("symbol"), "plan watch")
A = J("data/scan/ath.json")
for k in ("breakouts", "near", "day_close", "week_close", "month_close"):
    for r in A.get(k) or []:
        tag(r["symbol"], f"ath {k}")
for f, k in (("flags.json", "flag"), ("vcp.json", "vcp"), ("patterns.json", "pattern")):
    for r in J("data/scan/" + f).get("rows") or []:
        if (r.get("kind") or "stock") == "stock":
            tag(r["symbol"], f"{k} {r.get('status')}")
for r in J("data/scan/setup_log.json").get("rows") or []:
    tag(r["sym"], f"fwd {r.get('sys')}")
G = J("data/scan/group_pulse.json"); GS = G.get("stock") or {}
tick = [t for t in symbols("NSE").ticker]
rows = []
for a in range(0, len(tick), 200):
    ch = tick[a:a + 200]
    for _ in range(3):
        try:
            d = yf.download(ch + ["^NSEI"], period="5d", interval="1d", auto_adjust=False, progress=False, group_by="column", threads=True); break
        except Exception as e:  # noqa: BLE001
            time.sleep(10); d = None
    if d is None or d.empty:
        continue
    for t in ch:
        try:
            c = d["Close"][t].dropna(); v = d["Volume"][t].dropna()
        except Exception:  # noqa: BLE001
            continue
        if len(c) < 2 or c.index[-1].date() != datetime.now(IST).date():
            continue
        val = float(c.iloc[-2] * v.iloc[:-1].mean()) if len(v) > 1 else 0
        rows.append((t.replace(".NS", ""), float(c.iloc[-1] / c.iloc[-2] - 1) * 100, float(c.iloc[-1]), val))
    nif = d["Close"]["^NSEI"].dropna()
X = pd.DataFrame(rows, columns=["s", "chg", "px", "val"])
L = X[X.val >= 2e7].sort_values("chg", ascending=False)
print(f"R| as of {datetime.now(IST).strftime('%H:%M')} IST: Nifty {float(nif.iloc[-1] / nif.iloc[-2] - 1) * 100:+.2f}% today | liquid stocks {len(L)}: "
      f"up {(L.chg > 0).mean() * 100:.0f}%, median {L.chg.median():+.2f}%", flush=True)
print("R| TOP 30 GAINERS (liquid) and whether the app had them:", flush=True)
for r in L.head(30).itertuples():
    print(f"R| {r.s:12s} {r.chg:+6.2f}% | {(GS.get(r.s) or ['-'])[0][:26]:26s} | {', '.join(sorted(set(TAG.get(r.s, [])))) or 'not on any list'}", flush=True)
print("R| ALL:" + ";".join(f"{r.s}:{r.chg:.2f}:{r.px:.2f}" for r in X.itertuples()), flush=True)
