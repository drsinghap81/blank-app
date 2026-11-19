"""Inter-market clues for India's day (20 Nov 2026, Amritpal: "if Australia is ahead, do the sectors that run there that day
impact India ... any other market ... a clue for that day's momentum?").
Timing: ASX trades 04:30/05:30-10:30/11:30 IST, so most of its day is known at India's 09:15 open; the US closes ~01:30-02:30 IST
the night before. India's opening GAP already prices overnight news, so the useful question is India OPEN -> CLOSE.
Data: India indices from NSE (data/scan/index_ohlcv.csv.gz, 2016->); ASX indices and US ETFs from Yahoo.
Tests (daily, 2016-2026):
  A. index: ASX 200 same-day return / S&P 500 previous-night return  vs  Nifty gap and Nifty open->close
  B. sector pairs, relative to each market's index: ASX/US sector beat its index by > +1% (or lagged by < -1%) -> does the matching
     Indian sector beat Nifty open->close that day? (hit rate vs the sector's own base rate, average excess)
Output: data/research/intermarket.json"""
import json
import os

import numpy as np
import pandas as pd
import yfinance as yf

PAIRS = [  # (foreign, foreign index, India sector, label)
    ("^AXFJ", "^AXJO", "NIFTY BANK", "ASX Financials -> Bank Nifty"), ("^AXFJ", "^AXJO", "NIFTY FINANCIAL SERVICES", "ASX Financials -> Fin Services"),
    ("^AXMJ", "^AXJO", "NIFTY METAL", "ASX Materials -> Nifty Metal"), ("^AXEJ", "^AXJO", "NIFTY ENERGY", "ASX Energy -> Nifty Energy"),
    ("^AXIJ", "^AXJO", "NIFTY IT", "ASX IT -> Nifty IT"), ("^AXHJ", "^AXJO", "NIFTY PHARMA", "ASX Health -> Nifty Pharma"),
    ("^AXPJ", "^AXJO", "NIFTY REALTY", "ASX A-REIT -> Nifty Realty"), ("^AXDJ", "^AXJO", "NIFTY AUTO", "ASX Discretionary -> Nifty Auto"),
    ("^AXSJ", "^AXJO", "NIFTY FMCG", "ASX Staples -> Nifty FMCG"),
    ("XLK", "^GSPC", "NIFTY IT", "US Tech (prev night) -> Nifty IT"), ("SMH", "^GSPC", "NIFTY IT", "US Semis (prev night) -> Nifty IT"),
    ("XLF", "^GSPC", "NIFTY BANK", "US Financials (prev night) -> Bank Nifty"), ("XLE", "^GSPC", "NIFTY ENERGY", "US Energy (prev night) -> Nifty Energy"),
    ("XLB", "^GSPC", "NIFTY METAL", "US Materials (prev night) -> Nifty Metal"), ("XLV", "^GSPC", "NIFTY PHARMA", "US Health (prev night) -> Nifty Pharma"),
    ("XLY", "^GSPC", "NIFTY AUTO", "US Discretionary (prev night) -> Nifty Auto"), ("XLP", "^GSPC", "NIFTY FMCG", "US Staples (prev night) -> Nifty FMCG"),
]


def main():
    X = pd.read_csv("data/scan/index_ohlcv.csv.gz", parse_dates=["Date"])
    O = X.pivot_table(index="Date", columns="INDEX", values="Open"); C = X.pivot_table(index="Date", columns="INDEX", values="Close")
    O = O.where(O > 0)
    oc = C / O - 1                      # India open -> close
    gap = O / C.shift(1) - 1            # India gap
    tick = sorted({p[0] for p in PAIRS} | {p[1] for p in PAIRS})
    Y = yf.download(tick, start="2015-06-01", auto_adjust=True, progress=False)["Close"]
    Y.index = pd.to_datetime(Y.index).tz_localize(None)
    yr = Y.pct_change()
    # align: ASX same calendar date; US = the US session that ended before India's open (previous US trading date)
    idx = oc.index
    asx = yr.reindex(idx)                                   # same date
    us_prev = pd.DataFrame({t: yr[t].dropna().reindex(idx - pd.Timedelta(days=1), method="ffill").values for t in yr.columns}, index=idx)
    res = {"method": __doc__}
    n_oc, n_gap = oc["NIFTY 50"], gap["NIFTY 50"]
    def corr(a, b):
        m = a.notna() & b.notna(); return round(float(np.corrcoef(a[m], b[m])[0, 1]), 3), int(m.sum())
    res["index"] = {"ASX 200 same day vs Nifty gap": corr(asx["^AXJO"], n_gap), "ASX 200 same day vs Nifty open->close": corr(asx["^AXJO"], n_oc),
                    "S&P 500 prev night vs Nifty gap": corr(us_prev["^GSPC"], n_gap), "S&P 500 prev night vs Nifty open->close": corr(us_prev["^GSPC"], n_oc)}
    for k, v in res["index"].items():
        print("I|", k, "corr", v[0], "days", v[1], flush=True)
    # buckets for the index: ASX 200 day > +1% / < -1%
    for nm, s in (("ASX 200 same day", asx["^AXJO"]), ("S&P 500 prev night", us_prev["^GSPC"])):
        for lab, m in (("up > 1%", s > 0.01), ("down < -1%", s < -0.01), ("in between", (s.abs() <= 0.01))):
            z = n_oc[m & n_oc.notna()]; g = n_gap[m & n_gap.notna()]
            res.setdefault("index_buckets", {})[f"{nm} {lab}"] = dict(days=len(z), gap=round(float(g.mean() * 100), 2), oc=round(float(z.mean() * 100), 3), oc_up=round(float((z > 0).mean() * 100)))
            print("B|", nm, lab, res["index_buckets"][f"{nm} {lab}"], flush=True)
    # sector pairs
    for f, fi, ind, lab in PAIRS:
        src = asx if f.startswith("^AX") else us_prev
        if f not in src or fi not in src or ind not in oc:
            continue
        rel_f = src[f] - src[fi]                             # foreign sector vs its index
        rel_i = oc[ind] - oc["NIFTY 50"]                     # India sector vs Nifty, open -> close
        m = rel_f.notna() & rel_i.notna()
        base = rel_i[m]
        out = dict(days=int(m.sum()), corr=round(float(np.corrcoef(rel_f[m], rel_i[m])[0, 1]), 3), base_beat=round(float((base > 0).mean() * 100)))
        for tag, mm in (("strong", rel_f > 0.01), ("weak", rel_f < -0.01)):
            z = rel_i[m & mm]
            out[tag] = dict(days=len(z), beat=round(float((z > 0).mean() * 100)) if len(z) else None, avg_excess=round(float(z.mean() * 100), 3) if len(z) else None)
        # stability: two halves
        for half, hm in (("2016-20", rel_i.index < "2021-01-01"), ("2021-26", rel_i.index >= "2021-01-01")):
            z = rel_i[m & (rel_f > 0.01) & hm]; w = rel_i[m & (rel_f < -0.01) & hm]
            out[half] = dict(strong_avg=round(float(z.mean() * 100), 3) if len(z) else None, weak_avg=round(float(w.mean() * 100), 3) if len(w) else None)
        res.setdefault("pairs", {})[lab] = out
        print("P|", lab, out, flush=True)
    os.makedirs("data/research", exist_ok=True)
    json.dump(res, open("data/research/intermarket.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
