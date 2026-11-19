"""FII index-futures positioning as a market filter (19 Nov 2026, Amritpal: "Yes" to testing it next to the traffic light).

Data: NSE participant-wise open interest, published every evening (archives.nseindia.com/content/nsccl/fao_participant_oi_DDMMYYYY.csv).
FII long% = FII index-futures long / (long + short) contracts. Known after the close, so it can gate the NEXT morning's buys.
Tests:
  1. Nifty's next 5 / 20 sessions by FII long% bucket and by its 5-day change (rising / falling)
  2. live 9/21 engine (buy next open, 5-day-low stop, Supertrend exit, 1% risk) with no new buys when:
     FII long% < 25 / < 30 / in its bottom fifth of the past year / falling by >= 5 points over 5 days,
     each alone and together with the RED traffic light (the light is already live)
Output: data/research/gurjar_fii_oi.json"""
import io
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import requests
import yfinance as yf

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trend_bt_global import load, stats  # noqa: E402
import concentrated_921 as C  # noqa: E402
from signal_breadth import breadth  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36", "Accept": "*/*"}


def one(day):
    url = f"https://archives.nseindia.com/content/nsccl/fao_participant_oi_{day:%d%m%Y}.csv"
    for _ in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=20)
            if r.status_code == 404:
                return None
            if r.ok and b"FII" in r.content:
                t = pd.read_csv(io.BytesIO(r.content), skiprows=1)
                t.columns = [str(c).strip() for c in t.columns]
                t = t.set_index(t.columns[0]); t.index = [str(i).strip() for i in t.index]
                f = t.loc["FII"]
                return day, float(f["Future Index Long"]), float(f["Future Index Short"]), \
                    float(t.loc["Client"]["Future Index Long"]), float(t.loc["Client"]["Future Index Short"])
        except Exception:  # noqa: BLE001
            time.sleep(2)
    return None


def fii_series():
    days = pd.bdate_range("2016-01-01", pd.Timestamp.today())
    with ThreadPoolExecutor(8) as ex:
        rows = [r for r in ex.map(one, days) if r]
    F = pd.DataFrame(rows, columns=["Date", "fl", "fs", "cl", "cs"]).set_index("Date").sort_index()
    F["long"] = F.fl / (F.fl + F.fs) * 100
    F["client_long"] = F.cl / (F.cl + F.cs) * 100
    print("fii days", len(F), F.index.min(), F.index.max(), flush=True)
    return F


def main():
    F = fii_series()
    nif = yf.download("^NSEI", start="2015-01-01", auto_adjust=True, progress=False)["Close"].squeeze().dropna()
    nif.index = pd.to_datetime(nif.index).tz_localize(None)
    F = F[F.index.isin(nif.index)]
    L = F.long
    q20 = L.rolling(250, min_periods=120).quantile(0.2)
    ch5 = L - L.shift(5)
    res = dict(method=__doc__, days=len(F), first=str(F.index.min().date()),
               latest={str(k.date()): dict(fii_long=round(v.long, 1), client_long=round(v.client_long, 1)) for k, v in F.tail(10).iterrows()},
               long_pct_quantiles={str(q): round(float(L.quantile(q)), 1) for q in (0.1, 0.25, 0.5, 0.75, 0.9)})
    f5, f20 = nif.shift(-5) / nif - 1, nif.shift(-20) / nif - 1
    buckets = {"< 20": L < 20, "20-30": (L >= 20) & (L < 30), "30-45": (L >= 30) & (L < 45), "45-60": (L >= 45) & (L < 60), ">= 60": L >= 60,
               "bottom fifth of past year": L < q20, "fell >= 5 pts in 5 days": ch5 <= -5, "rose >= 5 pts in 5 days": ch5 >= 5, "all days": L.notna()}
    res["nifty_forward"] = {}
    for k, m in buckets.items():
        ix = m[m].index
        res["nifty_forward"][k] = dict(days=len(ix), next5=round(float(f5.reindex(ix).mean() * 100), 2), next20=round(float(f20.reindex(ix).mean() * 100), 2),
                                       up20=round(float((f20.reindex(ix) > 0).mean() * 100)))
        print("N|", k, res["nifty_forward"][k], flush=True)

    d, _ = load("NSE")
    d = d.sort_values(["SYMBOL", "Date"])
    g = d.groupby("SYMBOL").CLOSE
    d["r63"] = g.transform(lambda s: s / s.shift(63) - 1)
    B = breadth(d)
    w = nif.groupby(pd.Grouper(freq="W-FRI")).last().dropna(); below = (w < w.rolling(30).mean())
    B["idx_bad"] = below.reindex(B.index, method="ffill").shift(1).fillna(False).astype(bool)
    B["br_bad"] = B.W1.fillna(False).astype(bool)
    red = set(B.index[B.br_bad & B.idx_bad])
    fl = L.reindex(B.index).ffill()
    fq = q20.reindex(B.index).ffill(); fc = ch5.reindex(B.index).ffill()
    fii = {"FII long < 25%": set(B.index[fl < 25]), "FII long < 30%": set(B.index[fl < 30]),
           "FII long in bottom fifth of past year": set(B.index[fl < fq]), "FII long fell >= 5 pts in 5 days": set(B.index[fc <= -5])}
    gates = {"no filter": set(), "RED light (live)": red}
    for k, s in fii.items():
        gates[k] = s
        gates["RED light + " + k] = red | s
    res["gate_days_pct"] = {k: round(len([x for x in v if x >= pd.Timestamp("2016-06-01")]) / max(1, (B.index >= "2016-06-01").sum()) * 100, 1) for k, v in gates.items()}
    port = {}
    for label, args in (("10 positions, 3-month strength", (10, 0.01, "r63", 0)), ("5 positions, 3-month strength", (5, 0.01, "r63", 0)),
                        ("10 positions, random", (10, 0.01, "random", 0))):
        for gname, gate in gates.items():
            d2 = d.copy(); d2.loc[d2.Date.isin(gate), "sig"] = False
            eq, T = C.run(d2, *args)
            a, c = stats(eq, "2017-01-01", "2030-01-01"), stats(eq, "2022-01-01", "2030-01-01")
            k = f"{label} | {gname}"
            port[k] = dict(cagr=a["cagr"], maxdd=a["maxdd"], cagr_22_26=c["cagr"], dd_22_26=c["maxdd"], trades=len(T), days_blocked=res["gate_days_pct"][gname])
            print("R|", k, port[k], flush=True)
    res["portfolio"] = port
    os.makedirs("data/research", exist_ok=True)
    json.dump(res, open("data/research/gurjar_fii_oi.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
