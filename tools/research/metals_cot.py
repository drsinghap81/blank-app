"""Gold / silver: is a short squeeze setting up like PSU banks in Oct-Nov 2026? (22 Nov 2026, Amritpal)

PSU-bank recipe: price fell, the big speculators were very short (FII index-futures long % 9-12%), then they covered.
Metals equivalent: CFTC Commitments of Traders, disaggregated futures-only (COMEX gold 088691, silver 084691), weekly (Tuesday
positions, published Friday). Managed money = hedge funds / CTAs. Measures:
  mm_net_pct   (managed-money long - short) / open interest
  mm_long_share  long / (long + short)  (like FII long %)
  rank         where today's net sits in the past 3 years (0 = most bearish)
Test 2006-26: weeks when the net is in its bottom 10% of the past 3 years (very bearish positioning) -> metal's next 4 / 13 / 26
weeks vs all weeks; and 'covering starts' = net rises by >= 5% of OI over 3 weeks from the bottom 10%. Prices: Yahoo GC=F / SI=F
weekly closes, used from the Friday after the report (no look-ahead). Output data/research/metals_cot.json"""
import json
import os

import numpy as np
import pandas as pd
import requests
import yfinance as yf

API = "https://publicreporting.cftc.gov/resource/72hh-3qpy.json"
MET = {"Gold": ("088691", "GC=F"), "Silver": ("084691", "SI=F")}


def cot(code):
    r = requests.get(API, params={"cftc_contract_market_code": code, "$limit": 5000, "$order": "report_date_as_yyyy_mm_dd"}, timeout=60)
    r.raise_for_status(); d = pd.DataFrame(r.json())
    d["date"] = pd.to_datetime(d.report_date_as_yyyy_mm_dd)
    for k in ("m_money_positions_long_all", "m_money_positions_short_all", "open_interest_all", "swap_positions_long_all", "swap__positions_short_all",
              "prod_merc_positions_long", "prod_merc_positions_short"):
        if k in d:
            d[k] = pd.to_numeric(d[k], errors="coerce")
    d = d.set_index("date").sort_index()
    L, S, OI = d.m_money_positions_long_all, d.m_money_positions_short_all, d.open_interest_all
    return pd.DataFrame({"mm_long": L, "mm_short": S, "oi": OI, "mm_net_pct": (L - S) / OI * 100, "mm_long_share": L / (L + S) * 100})


def main():
    res = dict(method=__doc__)
    for nm, (code, tk) in MET.items():
        C = cot(code)
        px = yf.download(tk, start="2005-01-01", auto_adjust=True, progress=False)["Close"].squeeze().dropna()
        px.index = pd.to_datetime(px.index).tz_localize(None)
        wk = px.resample("W-FRI").last()
        C["avail"] = C.index + pd.Timedelta(days=3)                     # Tuesday positions known Friday
        C["px"] = [float(wk.asof(a)) for a in C.avail]
        C["rank"] = C.mm_net_pct.rolling(156, min_periods=100).apply(lambda w: (w[:-1] < w[-1]).mean(), raw=True)
        C["chg3"] = C.mm_net_pct - C.mm_net_pct.shift(3)
        for h in (4, 13, 26):
            C[f"f{h}"] = C.px.shift(-h) / C.px - 1
        C["dd52"] = C.px / C.px.rolling(52, min_periods=30).max() - 1
        T = C.dropna(subset=["rank"])
        def st(m):
            o = {}
            for h in (4, 13, 26):
                v = T.loc[m, f"f{h}"].dropna()
                o[f"{h}w"] = dict(n=int(len(v)), avg=round(float(v.mean()) * 100, 2) if len(v) else None, up=round(float((v > 0).mean()) * 100) if len(v) else None)
            return o
        bottom = T["rank"] <= 0.10
        cover = (T["rank"].shift(3) <= 0.10) & (T.chg3 >= 5)
        cover = cover & ~cover.shift(1, fill_value=False) & ~cover.shift(2, fill_value=False)
        fell = T.dd52 <= -0.10
        out = {"all weeks": st(T.index == T.index), "positioning bottom 10% (3y)": st(bottom), "bottom 10% AND price >= 10% below 52w high": st(bottom & fell),
               "covering starts (net +5% of OI in 3 weeks from bottom 10%)": st(cover), "positioning top 10% (crowded long)": st(T["rank"] >= 0.90)}
        ev = T[cover].index
        out["covering events"] = [str(x.date()) for x in ev[-12:]]
        last = C.iloc[-12:]
        out["latest"] = [dict(date=str(i.date()), price=round(r.px, 1), mm_long_share=round(r.mm_long_share, 1), mm_net_pct_oi=round(r.mm_net_pct, 1),
                              rank_3y=None if pd.isna(r["rank"]) else round(float(r["rank"]) * 100), off_52w_high=round(r.dd52 * 100, 1)) for i, r in last.iterrows()]
        res[nm] = out
        print(f"R| {nm} latest", out["latest"][-6:], flush=True)
        for k, v in out.items():
            if k not in ("latest", "covering events"):
                print(f"R| {nm} | {k} | {v}", flush=True)
        print(f"R| {nm} covering events (last 12): {out['covering events']}", flush=True)
    os.makedirs("data/research", exist_ok=True)
    json.dump(res, open("data/research/metals_cot.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
