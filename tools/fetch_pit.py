"""Point-in-time F&O stock universe with cash-market prices.
For each trading day: which stocks had STOCK FUTURES (F&O bhavcopy), and their EQ-series
OHLC, previous close (NSE adjusts it on ex-dates -> split/bonus factors) and volume from
the cash bhavcopy. Includes stocks later removed from F&O or delisted (no survivorship bias).
Usage: python fetch_pit.py START END OUT.csv"""
import io, sys, time, zipfile
import pandas as pd, requests

s = requests.Session()
s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
                  "Referer": "https://www.nseindia.com/"})


def get(url):
    for _ in range(3):
        try:
            r = s.get(url, timeout=30)
            if r.status_code == 200 and r.content[:2] == b"PK":
                z = zipfile.ZipFile(io.BytesIO(r.content))
                return pd.read_csv(z.open(z.namelist()[0]))
            return None
        except Exception:
            time.sleep(2)
    return None


def fo_symbols(d):
    if d >= pd.Timestamp("2024-07-01"):
        b = get(f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000.csv.zip")
        if b is not None:
            return set(b.loc[b.FinInstrmTp == "STF", "TckrSymb"])
    if d < pd.Timestamp("2024-07-15"):
        mon = d.strftime("%b").upper()
        b = get(f"https://archives.nseindia.com/content/historical/DERIVATIVES/{d.year}/{mon}/fo{d:%d}{mon}{d.year}bhav.csv.zip")
        if b is not None:
            b.columns = [c.strip() for c in b.columns]
            return set(b.loc[b.INSTRUMENT == "FUTSTK", "SYMBOL"])
    return None


def cash(d):
    if d >= pd.Timestamp("2024-07-01"):
        b = get(f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{d:%Y%m%d}_F_0000.csv.zip")
        if b is not None:
            b = b[b.SctySrs == "EQ"]
            return pd.DataFrame({"SYMBOL": b.TckrSymb, "OPEN": b.OpnPric, "HIGH": b.HghPric, "LOW": b.LwPric,
                                 "CLOSE": b.ClsPric, "PREVCLOSE": b.PrvsClsgPric, "VOLUME": b.TtlTradgVol})
    if d < pd.Timestamp("2024-07-15"):
        mon = d.strftime("%b").upper()
        b = get(f"https://archives.nseindia.com/content/historical/EQUITIES/{d.year}/{mon}/cm{d:%d}{mon}{d.year}bhav.csv.zip")
        if b is not None:
            b.columns = [c.strip() for c in b.columns]
            b = b[b.SERIES.astype(str).str.strip() == "EQ"]
            return pd.DataFrame({"SYMBOL": b.SYMBOL, "OPEN": b.OPEN, "HIGH": b.HIGH, "LOW": b.LOW,
                                 "CLOSE": b.CLOSE, "PREVCLOSE": b.PREVCLOSE, "VOLUME": b.TOTTRDQTY})
    return None


start, end, out = sys.argv[1:4]
rows, miss = [], 0
for d in pd.bdate_range(start, end):
    syms = fo_symbols(d)
    if not syms:
        miss += 1
        continue
    c = cash(d)
    if c is None:
        miss += 1
        continue
    c = c[c.SYMBOL.isin(syms)].copy()
    c.insert(0, "Date", d.date())
    rows.append(c)
    time.sleep(0.05)
pd.concat(rows).to_csv(out, index=False)
print(out, "days", len(rows), "missing", miss, "rows", sum(len(r) for r in rows))
