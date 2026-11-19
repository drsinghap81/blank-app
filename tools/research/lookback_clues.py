"""One-off (19 Nov 2026, Amritpal): before today's move, did delivery, volume, tightness, futures OI or PCR give a clue?
Winners = the 30 top gainers of 19 Nov that beat their industry, sector, themes and Nifty (gainers_today.py).
Control = liquid NSE stocks (>= Rs 5 cr/day) that did NOT rise more than 1% today. Everything measured up to YESTERDAY's close.
  price/volume (Yahoo): value 5d/50d, 10-day range %, ATR(5)/ATR(20), 5- and 20-day return, distance from EMA 20, RSI 14
  delivery (NSE MTO files): delivery % last 5 sessions minus the 20 before; delivered quantity 5d avg / 20d avg
  F&O (NSE F&O bhavcopy, F&O stocks only): futures OI change over 5 sessions, price change -> long build-up; option PCR change
A clue matters only if winners differ clearly from the control group (median and share above a level)."""
import io
import time
import zipfile
from datetime import timedelta

import numpy as np
import pandas as pd
import requests
import yfinance as yf

W = ["GLOBUSSPR", "VOLTAS", "BLUESTARCO", "TATATECH", "IREDA", "SJS", "PROTEAN", "ARIS", "MARUTI", "WOCKPHARMA", "PGEL", "ASHAPURMIN",
     "ADVENZYMES", "COLPAL", "HAVELLS", "SYMPHONY", "GHCLTEXTIL", "VENUSREM", "DABUR", "PREMEXPLN", "GABRIEL", "TVSMOTOR", "IDFCFIRSTB",
     "TMPV", "DIXON", "AEROPLANE", "SEDEMAC", "DHOOTTRANS", "MOTHERSON", "HINDUNILVR"]
s = requests.Session()
s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36", "Referer": "https://www.nseindia.com/"})


def get(url):
    for _ in range(3):
        try:
            r = s.get(url, timeout=40)
            if r.status_code == 200:
                return r.content
            if r.status_code == 404:
                return None
        except Exception:  # noqa: BLE001
            time.sleep(2)
    return None


# ---- universe + price/volume (Yahoo)
import sys, os  # noqa: E401,E402
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from global_universe import symbols  # noqa: E402
tick = list(symbols("NSE").ticker)
P = {}
for i in range(0, len(tick), 250):
    D = yf.download(tick[i:i + 250], period="4mo", interval="1d", progress=False, auto_adjust=True, threads=True)
    for k in ("Open", "High", "Low", "Close", "Volume"):
        P.setdefault(k, []).append(D[k])
    time.sleep(3)
O, H, L, C, V = (pd.concat(P[k], axis=1) for k in ("Open", "High", "Low", "Close", "Volume"))
today = C.index[-1]; chg = (C.iloc[-1] / C.iloc[-2] - 1) * 100
C1, H1, L1, V1 = C.iloc[:-1], H.iloc[:-1], L.iloc[:-1], V.iloc[:-1]           # up to yesterday
val = C1 * V1; avg20 = val.iloc[-20:].mean() / 1e7
liq = [t for t in C.columns if avg20.get(t, 0) >= 5]
win = [t + ".NS" for t in W if t + ".NS" in C.columns]
ctl = [t for t in liq if t not in win and pd.notna(chg.get(t)) and chg[t] <= 1.0]
days = list(C1.index[-25:])                                                    # last 25 sessions before today
print("today", today.date(), "winners", len(win), "control", len(ctl), "sessions", days[0].date(), "->", days[-1].date())


def pv(t):
    c, h, l = C1[t].dropna(), H1[t], L1[t]
    if len(c) < 60:
        return None
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    d = c.diff(); up = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean(); dn = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    e20 = c.ewm(span=20, adjust=False).mean()
    return dict(vol5_50=float(val[t].iloc[-5:].mean() / val[t].iloc[-50:].mean()), range10=float((h.iloc[-10:].max() / l.iloc[-10:].min() - 1) * 100),
                atr5_20=float(tr.iloc[-5:].mean() / tr.iloc[-20:].mean()), ret5=float((c.iloc[-1] / c.iloc[-6] - 1) * 100),
                ret20=float((c.iloc[-1] / c.iloc[-21] - 1) * 100), dist_e20=float((c.iloc[-1] / e20.iloc[-1] - 1) * 100),
                rsi=float((100 - 100 / (1 + up / dn)).iloc[-1]))


M = {t: pv(t) for t in win + ctl}
M = {t: m for t, m in M.items() if m}

# ---- delivery (NSE MTO)
DL = {}
for d in days:
    b = get(f"https://nsearchives.nseindia.com/archives/equities/mto/MTO_{d:%d%m%Y}.DAT") or get(f"https://archives.nseindia.com/archives/equities/mto/MTO_{d:%d%m%Y}.DAT")
    if not b:
        continue
    for line in io.StringIO(b.decode("latin-1")):
        p = [x.strip() for x in line.split(",")]
        if len(p) >= 7 and p[0] == "20" and p[3] == "EQ":
            try:
                DL.setdefault(p[2] + ".NS", {})[d] = (float(p[5]), float(p[6]))
            except ValueError:
                pass
print("delivery files", len({d for v in DL.values() for d in v}))
for t, m in M.items():
    x = DL.get(t)
    if x and len(x) >= 15:
        ds = sorted(x); pct = [x[d][1] for d in ds]; qty = [x[d][0] for d in ds]
        m["deliv_pct_chg"] = float(np.mean(pct[-5:]) - np.mean(pct[-25:-5])); m["deliv_pct"] = float(np.mean(pct[-5:]))
        m["deliv_qty5_20"] = float(np.mean(qty[-5:]) / max(1.0, np.mean(qty[-20:])))

# ---- F&O (bhavcopy yesterday vs 5 sessions earlier)
def fo(d):
    b = get(f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000.csv.zip")
    if not b or b[:2] != b"PK":
        return None
    z = zipfile.ZipFile(io.BytesIO(b)); return pd.read_csv(z.open(z.namelist()[0]))


F1, F0 = fo(days[-1]), fo(days[-6])
if F1 is not None and F0 is not None:
    def agg(F):
        fut = F[F.FinInstrmTp == "STF"].groupby("TckrSymb").agg(oi=("OpnIntrst", "sum"))
        op = F[F.FinInstrmTp == "STO"]
        pcr = op[op.OptnTp == "PE"].groupby("TckrSymb").OpnIntrst.sum() / op[op.OptnTp == "CE"].groupby("TckrSymb").OpnIntrst.sum()
        return fut.join(pcr.rename("pcr"), how="left")
    A1, A0 = agg(F1), agg(F0)
    for t, m in M.items():
        k = t[:-3]
        if k in A1.index and k in A0.index and A0.at[k, "oi"] > 0:
            m["fut_oi_chg5"] = float((A1.at[k, "oi"] / A0.at[k, "oi"] - 1) * 100)
            m["long_buildup"] = bool(m["fut_oi_chg5"] > 5 and m["ret5"] > 0)
            if pd.notna(A1.at[k, "pcr"]) and pd.notna(A0.at[k, "pcr"]):
                m["pcr"] = float(A1.at[k, "pcr"]); m["pcr_chg5"] = float(A1.at[k, "pcr"] - A0.at[k, "pcr"])
else:
    print("F&O bhavcopy not available")

# ---- compare
tests = [("vol5_50", ">", 1.3), ("range10", "<", 8), ("atr5_20", "<", 0.8), ("ret5", ">", 0), ("ret20", ">", 0), ("dist_e20", "<", 2),
         ("rsi", ">", 50), ("deliv_pct_chg", ">", 3), ("deliv_qty5_20", ">", 1.3), ("fut_oi_chg5", ">", 5), ("pcr_chg5", ">", 0.05), ("long_buildup", "=", True)]
for k, op, lv in tests:
    w = [M[t][k] for t in win if t in M and k in M[t]]; c = [M[t][k] for t in ctl if t in M and k in M[t]]
    if not w or not c:
        continue
    f = (lambda v: v > lv) if op == ">" else (lambda v: v < lv) if op == "<" else (lambda v: v is lv)
    sw, sc = np.mean([f(v) for v in w]) * 100, np.mean([f(v) for v in c]) * 100
    mw, mc = (np.median([float(v) for v in w]), np.median([float(v) for v in c])) if op != "=" else (None, None)
    print(f"C| {k}: winners median {mw if mw is None else round(mw, 2)} vs control {mc if mc is None else round(mc, 2)} | {op}{lv}: winners {sw:.0f}% vs control {sc:.0f}% (n {len(w)}/{len(c)})")
for t in win:
    if t in M:
        print("W|", t[:-3], {k: (round(v, 2) if isinstance(v, float) else v) for k, v in M[t].items()})
