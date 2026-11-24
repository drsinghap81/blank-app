"""Nifty 1994-96 vs the 2024-26 move (24 Nov 2026, Amritpal: "check chart pattern on Nifty in 1995 and the latest rally").
Tries niftyindices.com historical data (NIFTY 50 back-calculated from 1990), then Yahoo Sensex (^BSESN, from 1997 only) as a fallback.
Prints weekly closes 1994-01 .. 1997-06 and 2024-06 .. today, with drawdown from the prior high and % move from the low."""
import json
import time

import pandas as pd
import requests
import yfinance as yf

H = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json; charset=UTF-8", "Origin": "https://www.niftyindices.com",
     "Referer": "https://www.niftyindices.com/reports/historical-data", "X-Requested-With": "XMLHttpRequest"}


def nifty_hist(a, b):
    s = requests.Session(); s.get("https://www.niftyindices.com/reports/historical-data", headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    body = {"cinfo": json.dumps({"name": "NIFTY 50", "startDate": a, "endDate": b, "indexName": "NIFTY 50"})}
    r = s.post("https://www.niftyindices.com/Backpage.aspx/getHistoricaldatatabletoString", headers=H, data=json.dumps(body), timeout=60)
    d = json.loads(json.loads(r.text)["d"]); x = pd.DataFrame(d)
    x["Date"] = pd.to_datetime(x["HistoricalDate"], format="mixed"); x["Close"] = pd.to_numeric(x["CLOSE"], errors="coerce")
    x["High"] = pd.to_numeric(x.get("HIGH"), errors="coerce"); x["Low"] = pd.to_numeric(x.get("LOW"), errors="coerce")
    return x.set_index("Date").sort_index()[["High", "Low", "Close"]]


parts = []
for a, b in [("01-Jan-1993", "31-Dec-1994"), ("01-Jan-1995", "31-Dec-1996"), ("01-Jan-1997", "31-Dec-1998")]:
    try:
        parts.append(nifty_hist(a, b)); print("R| got", a, b, len(parts[-1]), flush=True); time.sleep(2)
    except Exception as e:  # noqa: BLE001
        print("R| niftyindices failed", a, b, str(e)[:200], flush=True)
old = pd.concat(parts) if parts else None
new = yf.download("^NSEI", start="2024-01-01", progress=False, auto_adjust=True)["Close"].squeeze().dropna(); new.index = pd.to_datetime(new.index).tz_localize(None)
def show(c, lab):
    w = c.resample("W-FRI").last().dropna(); hi = w.cummax(); 
    print(f"R| ===== {lab}: weekly closes (date close | from prior high | from low so far) =====", flush=True)
    lo = w.cummin()
    for d, v in w.items():
        print(f"R| {d.date()} {v:9.1f} | {(v / hi[d] - 1) * 100:6.1f}% | +{(v / lo[d] - 1) * 100:5.1f}%", flush=True)
if old is not None and len(old):
    show(old.Close.loc["1993-06-01":"1997-12-31"], "NIFTY 1993-97")
else:
    s = yf.download("^BSESN", start="1990-01-01", progress=False, auto_adjust=True)["Close"].squeeze().dropna(); print("R| sensex from", s.index[0], flush=True)
show(new, "NIFTY 2024-26")
