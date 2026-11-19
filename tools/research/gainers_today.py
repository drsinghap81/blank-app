"""One-off (19 Nov 2026, Amritpal): today's top gainers among liquid NSE stocks that beat their industry, sector, themes and Nifty,
and where each one appeared in our systems (lists in data/scan as of the last scan). Yahoo daily bars (today's partial bar)."""
import json
import os
import sys

import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from global_universe import symbols  # noqa: E402
from sector_state import INDUSTRY_INDEX  # noqa: E402

u = symbols("NSE"); tick = list(u.ticker)
C, V = [], []
for i in range(0, len(tick), 250):
    D = yf.download(tick[i:i + 250] + (["^NSEI"] if i == 0 else []), period="1mo", interval="1d", progress=False, auto_adjust=True, threads=True)
    C.append(D["Close"]); V.append(D["Volume"])
Cl = pd.concat(C, axis=1); Vo = pd.concat(V, axis=1)
day = Cl.index[-1]; chg = (Cl.iloc[-1] / Cl.iloc[-2] - 1) * 100
val = (Cl * Vo).iloc[-21:-1].mean() / 1e7                     # Rs cr a day, 20 days before today
nifty = float(chg["^NSEI"])
S = json.load(open("data/scan/sectors.json")); ind = S["symbols"]; th = S.get("themes", {})
base = {t: t[:-3] for t in tick}
by_ind, by_sec, by_th = {}, {}, {}
for t, s in base.items():
    if t in chg and pd.notna(chg[t]):
        i = ind.get(s)
        if i:
            by_ind.setdefault(i, []).append(chg[t]); by_sec.setdefault(INDUSTRY_INDEX.get(i, i), []).append(chg[t])
        for x in th.get(s, []):
            by_th.setdefault(x, []).append(chg[t])
med = lambda L: float(pd.Series(L).median()) if L else None  # noqa: E731

# our systems (last scan)
L = lambda f: json.load(open("data/scan/" + f)) if os.path.exists("data/scan/" + f) else {}  # noqa: E731
tr, at, vc, ip, pt, gm, tp, tu = L("trend_scan.json"), L("ath.json"), L("vcp.json"), L("ipo.json"), L("patterns.json"), L("growth_mom.json"), L("trade_plan.json"), L("turtle.json")
sysm = {}
put = lambda s, txt: sysm.setdefault(s, []).append(txt)  # noqa: E731
for r in tr.get("rows", []):
    put(r["symbol"], f"Trend list: {r.get('list')} ({r.get('tag')})")
for r in tr.get("early", []):
    put(r["symbol"], f"9/21 {r.get('setup', '')[:14]}: {r.get('status')} (signal {r.get('signal_date')})")
for r in tr.get("bases", []):
    put(r["symbol"], f"Tight base: {r.get('status')}")
for s in tr.get("stack", []):
    put(s, "MA stack")
for k in ("breakouts", "near", "month_close", "week_close", "day_close", "week_short", "day_short"):
    for r in at.get(k, []):
        put(r["symbol"], f"ATH {k}" + (f" ({r.get('date')})" if r.get("date") else ""))
for r in at.get("tracked", []):
    if r.get("status") == "open":
        put(r["symbol"], f"ATH trade open since {r.get('date')}")
for r in vc.get("rows", []):
    put(r["symbol"], "VCP setup")
for k in ("breakouts", "near"):
    for r in ip.get(k, []):
        put(r["symbol"], f"IPO cup {k}")
for r in pt.get("rows", []):
    put(r["symbol"], f"Bottom pattern: {r.get('pattern') or r.get('kind') or ''}")
for r in gm.get("picks", []):
    put(r["symbol"], "Growth+momentum pick")
for k in ("top", "swing"):
    for r in tp.get(k, []) or []:
        put(r["symbol"], f"Live plan: {r.get('system')} ({r.get('kind')})")
for r in tu.get("rows", []):
    if r["key"].endswith(".NS") and r.get("status") != "flat":
        put(r["key"][:-3], f"Turtle {r['status']}")

rows = []
for t, s in base.items():
    c = chg.get(t)
    if c is None or pd.isna(c) or (val.get(t) or 0) < 5 or (Cl[t].iloc[-1] or 0) < 50:
        continue
    i = ind.get(s); im = med(by_ind.get(i, [])) if i else None; sm = med(by_sec.get(INDUSTRY_INDEX.get(i, i), [])) if i else None
    tms = {x: med(by_th.get(x, [])) for x in th.get(s, [])}
    beat = c > nifty and (im is None or c > im) and (sm is None or c > sm) and all(c > v for v in tms.values() if v is not None)
    rows.append(dict(sym=s, chg=round(float(c), 2), val_cr=round(float(val[t]), 1), industry=i, ind_med=None if im is None else round(im, 2),
                     sector=INDUSTRY_INDEX.get(i) if i else None, sec_med=None if sm is None else round(sm, 2),
                     themes={k.replace("NIFTY ", ""): round(v, 2) for k, v in tms.items() if v is not None}, beat_all=bool(beat),
                     systems=sysm.get(s, [])))
rows.sort(key=lambda r: -r["chg"])
top = [r for r in rows if r["beat_all"]][:30]
print("day", day.date(), "Nifty", round(nifty, 2), "liquid stocks", len(rows), "up", sum(r["chg"] > 0 for r in rows))
for r in top:
    print("R|", json.dumps(r, ensure_ascii=False))
inn = [r for r in top if r["systems"]]
print("S| in our systems:", len(inn), "of", len(top))
