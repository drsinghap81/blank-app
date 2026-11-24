"""Which assets hedge each other (24 Nov 2026, Amritpal). Monthly returns 2010 -> today (Yahoo, adjusted), in local currency and
for India investors in rupees (USD assets x USDINR). Correlation matrix (all months, and the last 5 years), and what each asset did
in Nifty's 15 worst months and in the S&P 500's 15 worst months (average return, % of those months it rose). Also the app's systems'
monthly curves where available (data/research/alloc_curves.json is not needed - kept to markets)."""
import numpy as np
import pandas as pd
import yfinance as yf

T = {"Nifty 50": "^NSEI", "Bank Nifty": "^NSEBANK", "Nifty Midcap": "^NSEMDCP50", "S&P 500": "^GSPC", "Nasdaq 100": "^NDX",
     "Gold $": "GC=F", "Silver $": "SI=F", "Crude $": "CL=F", "US long bonds (TLT)": "TLT", "US 7-10y bonds (IEF)": "IEF",
     "US dollar index": "DX-Y.NYB", "USDINR": "INR=X", "Japanese yen (JPY per $)": "JPY=X", "Swiss franc (CHF per $)": "CHF=X",
     "Bitcoin": "BTC-USD", "India gold ETF (GOLDBEES)": "GOLDBEES.NS", "India liquid/gilt (GILT5YBEES)": "GILT5YBEES.NS", "VIX": "^VIX"}
px = {}
for k, t in T.items():
    try:
        d = yf.download(t, start="2009-12-01", progress=False, auto_adjust=True)["Close"].squeeze().dropna()
        d.index = pd.to_datetime(d.index).tz_localize(None); px[k] = d.resample("ME").last()
    except Exception as e:  # noqa: BLE001
        print("R| skip", k, e)
P = pd.DataFrame(px); R = P.pct_change().dropna(how="all")
R = R[R.index >= "2010-02-01"]
inr = R["USDINR"]
for k in ("S&P 500", "Nasdaq 100", "Gold $", "Silver $", "US long bonds (TLT)", "Bitcoin"):
    if k in R:
        R[k.replace(" $", "") + " in ₹"] = (1 + R[k]) * (1 + inr) - 1
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 40)
for lab, X in (("all 2010-26", R), ("last 5 years", R[R.index > R.index[-1] - pd.DateOffset(years=5)])):
    C = X.corr()
    for a in ("Nifty 50", "S&P 500"):
        s = C[a].drop(a).sort_values()
        print(f"R| corr with {a} ({lab}): " + " | ".join(f"{k} {v:+.2f}" for k, v in s.items()), flush=True)
for a in ("Nifty 50", "S&P 500"):
    worst = R[a].nsmallest(15).index
    out = []
    for k in R.columns:
        if k == a:
            continue
        v = R.loc[worst, k].dropna()
        if len(v) >= 8:
            out.append((k, v.mean() * 100, (v > 0).mean() * 100, len(v)))
    out.sort(key=lambda z: -z[1])
    print(f"R| in {a}'s 15 worst months (avg {R.loc[worst, a].mean() * 100:.1f}%): " + " | ".join(f"{k} {m:+.1f}% ({u:.0f}% up, n {n})" for k, m, u, n in out), flush=True)
