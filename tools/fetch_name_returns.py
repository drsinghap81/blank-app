"""Price returns for every listed Indian stock (NSE main + SME, and BSE-only scrips), keyed by ISIN and name,
so other tools (e.g. the StockEdge star-investor analysis) can match stocks by company name.

Output data/ret/returns.csv:
  isin, name, ticker, last_date, close, r3m, r1y, r2y, first_date,
  q202409 ... q202609  (split/bonus-adjusted close on the last trading day of each quarter)
"""
import io
import os
import time
import zipfile
from datetime import date, timedelta

import pandas as pd
import requests
import yfinance as yf

OUT = "data/ret"
os.makedirs(OUT, exist_ok=True)
s = requests.Session()
s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
                  "Referer": "https://www.nseindia.com/"})


def get(url):
    for _ in range(3):
        try:
            r = s.get(url, timeout=40)
            if r.status_code == 200:
                return r.content
        except Exception:  # noqa: BLE001
            pass
        time.sleep(2)
    return None


def nse_lists():
    rows = []
    for u in ("https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
              "https://nsearchives.nseindia.com/emerge/corporates/content/SME_EQUITY_L.csv"):
        b = get(u)
        if not b:
            print("missing", u); continue
        d = pd.read_csv(io.BytesIO(b))
        d.columns = [c.strip().upper() for c in d.columns]
        print(u, list(d.columns))
        col = lambda key: next(c for c in d.columns if key in c)
        rows.append(pd.DataFrame({"isin": d[col("ISIN")].astype(str).str.strip(), "name": d[col("NAME")].astype(str).str.strip(),
                                  "ticker": d[col("SYMBOL")].astype(str).str.strip() + ".NS"}))
    return pd.concat(rows) if rows else pd.DataFrame(columns=["isin", "name", "ticker"])


def bse_list():
    d0 = date.today()
    for back in range(0, 10):
        d = d0 - timedelta(days=back)
        if d.weekday() >= 5:
            continue
        b = get(f"https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{d:%Y%m%d}_F_0000.CSV")
        if b and b[:5] != b"<!DOC":
            x = pd.read_csv(io.BytesIO(b))
            x = x[x.ISIN.astype(str).str.startswith("INE")]
            print("BSE bhavcopy", d, len(x))
            return pd.DataFrame({"isin": x.ISIN.str.strip(), "name": x.FinInstrmNm.astype(str).str.strip(),
                                 "ticker": x.FinInstrmId.astype(str) + ".BO"})
    print("no BSE bhavcopy")
    return pd.DataFrame(columns=["isin", "name", "ticker"])


def main():
    n, b = nse_lists(), bse_list()
    print("NSE", len(n), "BSE", len(b))
    u = pd.concat([n, b[~b["isin"].isin(n["isin"])]]).drop_duplicates("isin")
    bse_names = b.set_index("isin").name.to_dict()
    u["bse_name"] = u["isin"].map(bse_names)
    tick = list(u.ticker)
    closes = {}
    for i in range(0, len(tick), 150):
        chunk = tick[i:i + 150]
        try:
            d = yf.download(chunk, start=(date.today() - timedelta(days=800)).isoformat(), auto_adjust=True,
                            progress=False, group_by="column", threads=True)
            c = d["Close"] if isinstance(d.columns, pd.MultiIndex) else d[["Close"]].rename(columns={"Close": chunk[0]})
            for t in c.columns:
                sr = c[t].dropna()
                if len(sr):
                    closes[t] = sr
        except Exception as e:  # noqa: BLE001
            print("chunk fail", i, e)
        print(i, len(closes), flush=True)
    qs = pd.period_range("2024Q3", "2026Q3", freq="Q")
    out = []
    for _, r in u.iterrows():
        sr = closes.get(r.ticker)
        rec = dict(isin=r["isin"], name=r["name"], bse_name=r.bse_name, ticker=r.ticker)
        if sr is not None and len(sr) > 5:
            last = sr.index[-1]
            rec.update(last_date=last.date(), close=round(float(sr.iloc[-1]), 3), first_date=sr.index[0].date())
            for lab, days in (("r3m", 91), ("r1y", 365), ("r2y", 730)):
                p = sr[sr.index <= last - pd.Timedelta(days=days)]
                rec[lab] = round((sr.iloc[-1] / p.iloc[-1] - 1) * 100, 2) if len(p) and (last - p.index[-1]).days < days + 10 else None
            for q in qs:
                p = sr[sr.index <= q.end_time]
                rec[f"q{q.year}{q.quarter * 3:02d}"] = round(float(p.iloc[-1]), 3) if len(p) and (q.end_time - p.index[-1]).days < 20 else None
        out.append(rec)
    df = pd.DataFrame(out)
    df.to_csv(f"{OUT}/returns.csv", index=False)
    print("rows", len(df), "with r2y", df.r2y.notna().sum() if "r2y" in df else 0)


if __name__ == "__main__":
    main()
