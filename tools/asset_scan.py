"""Other assets (15 Nov 2026): commodities, currencies, crypto and world indices with the month-close ATH check used for
stocks and ETFs. For each: last completed monthly close vs the old all-time-high monthly close, base (months since that
high), the fall inside the base, and the 30-week SMA trend. Yahoo data; commodity futures are front-month continuous
contracts (not roll-adjusted), so long-run levels are approximate. Not tested as a trading system. -> data/scan/assets.json"""
import json, os, sys, time
from datetime import datetime, timezone
import numpy as np, pandas as pd, yfinance as yf
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fund_scan import mclose_state  # noqa: E402

A = {
    "Metals": {"GC=F": "Gold", "SI=F": "Silver", "PL=F": "Platinum", "PA=F": "Palladium", "HG=F": "Copper", "ALI=F": "Aluminium"},
    "Energy": {"CL=F": "Crude oil (WTI)", "BZ=F": "Crude oil (Brent)", "NG=F": "Natural gas", "HO=F": "Heating oil", "RB=F": "Gasoline"},
    "Agriculture": {"ZC=F": "Corn", "ZW=F": "Wheat", "ZS=F": "Soybeans", "ZM=F": "Soybean meal", "ZL=F": "Soybean oil", "KC=F": "Coffee",
                    "CC=F": "Cocoa", "SB=F": "Sugar", "CT=F": "Cotton", "OJ=F": "Orange juice", "LE=F": "Live cattle", "HE=F": "Lean hogs"},
    "Currencies": {"DX-Y.NYB": "US dollar index", "USDINR=X": "US dollar in rupees", "EURUSD=X": "Euro in US$", "GBPUSD=X": "Pound in US$",
                   "AUDUSD=X": "Australian dollar in US$", "USDJPY=X": "US dollar in yen", "USDCNY=X": "US dollar in yuan", "AUDINR=X": "Australian dollar in rupees"},
    "Crypto": {"BTC-USD": "Bitcoin", "ETH-USD": "Ether", "SOL-USD": "Solana", "XRP-USD": "XRP"},
    "Bonds": {"^TNX": "US 10-year yield", "^TYX": "US 30-year yield", "^FVX": "US 5-year yield"},
    "World indices": {"^GSPC": "S&P 500", "^NDX": "Nasdaq 100", "^DJI": "Dow Jones", "^RUT": "Russell 2000", "^NSEI": "Nifty 50", "^BSESN": "Sensex",
                      "^NSEBANK": "Nifty Bank", "^AXJO": "ASX 200", "^FTSE": "FTSE 100", "^GDAXI": "DAX", "^FCHI": "CAC 40", "^STOXX50E": "Euro Stoxx 50",
                      "^N225": "Nikkei 225", "^HSI": "Hang Seng", "000001.SS": "Shanghai Composite", "^KS11": "KOSPI", "^TWII": "Taiwan", "^BVSP": "Brazil Bovespa"},
}
INR = {"GC=F": "Gold in rupees", "SI=F": "Silver in rupees", "HG=F": "Copper in rupees", "ALI=F": "Aluminium in rupees",
       "CL=F": "Crude oil in rupees", "NG=F": "Natural gas in rupees"}   # ~MCX: global futures x US$/Rs (excludes Indian duties/premiums)
RAW = {}
rows = []


def add_row(t, nm, grp, x):
    mc = x.Close.resample("ME").last().dropna(); per = mc.index.to_period("M")
    lm = pd.Timestamp(datetime.now(timezone.utc).date()).to_period("M") - 1
    done = mc[per <= lm]
    if len(done) < 14:
        return
    a = int(np.argmax(done.to_numpy())); old = float(done.iloc[a])
    w = x.Close.resample("W-FRI").last().dropna(); sma = w.rolling(30).mean()
    r = dict(key=t, name=nm, group=grp, close=float(x.Close.iloc[-1]), asof=str(x.index[-1].date()), first=str(x.index[0].date()),
             ath_close=old, ath_month=str(per[per <= lm][a]), base_months=int(len(done) - 1 - a), below_ath_pct=round((1 - float(x.Close.iloc[-1]) / old) * 100, 2),
             sma_rising=bool(len(sma.dropna()) > 5 and w.iloc[-1] > sma.iloc[-1] > sma.iloc[-5]), mclose=None)
    try:
        r["mclose"] = mclose_state(x)
    except Exception as e:  # noqa: BLE001
        print("mclose fail", t, e)
    if r["mclose"]:                                  # the breakout month is the new ATH: report the OLD high it cleared
        r.update(ath_close=r["mclose"]["old_ath"], ath_month=r["mclose"]["ath_month"], base_months=r["mclose"]["base_months"])
    r["depth"] = r["mclose"]["depth"] if r["mclose"] else (round(float(done.iloc[a + 1:].min() / old - 1), 4) if a + 1 < len(done) else None)
    rows.append(r)


for grp, D in A.items():
    for t, nm in D.items():
        x = None
        for _ in range(3):
            try:
                x = yf.download(t, period="max", interval="1d", auto_adjust=False, progress=False)
                break
            except Exception as e:  # noqa: BLE001
                print("retry", t, e); time.sleep(5)
        if x is None or x.empty:
            print("no data", t); continue
        if isinstance(x.columns, pd.MultiIndex):
            x.columns = x.columns.get_level_values(0)
        x = x[["Open", "High", "Low", "Close"]].dropna(subset=["Close"]); x = x[x.Close > 0]
        if len(x) < 400:
            continue
        RAW[t] = x
        add_row(t, nm, grp, x)
        time.sleep(0.5)
fx = RAW.get("USDINR=X")
if fx is not None:
    f = fx.Close
    for t, nm in INR.items():
        if t in RAW:
            x = RAW[t]; k = f.reindex(x.index, method="ffill")
            xi = x[["Open", "High", "Low", "Close"]].mul(k, axis=0).dropna()
            if len(xi) >= 400:
                add_row(t + ":INR", nm, "In rupees (≈MCX)", xi)
os.makedirs("data/scan", exist_ok=True)
json.dump(dict(generated=datetime.now(timezone.utc).isoformat(timespec="minutes"),
               month=str(pd.Timestamp(datetime.now(timezone.utc).date()).to_period("M") - 1), rows=rows),
          open("data/scan/assets.json", "w"), separators=(",", ":"))
print(len(rows), "assets;", sum(1 for r in rows if r["mclose"]), "closed last month above an ATH >= 12 months old:",
      [r["name"] for r in rows if r["mclose"]])
