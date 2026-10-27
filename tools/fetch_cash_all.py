"""All NSE cash-market stocks, daily OHLC from the CM bhavcopy (incl. stocks later delisted -> no survivorship bias).
Series kept: EQ, BE, BZ (trade-to-trade) and SM, ST (SME). PREVCLOSE is NSE-adjusted on ex-dates, so
split/bonus factors = PREVCLOSE(t) / CLOSE(t-1).  Usage: python fetch_cash_all.py START END OUT.csv.gz"""
import io, sys, time, zipfile
import pandas as pd, requests

KEEP = {"EQ", "BE", "BZ", "SM", "ST"}
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
        except Exception:  # noqa: BLE001
            time.sleep(2)
    return None


def cash(d):
    if d >= pd.Timestamp("2024-07-01"):
        b = get(f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{d:%Y%m%d}_F_0000.csv.zip")
        if b is not None:
            b = b[b.SctySrs.isin(KEEP)]
            return pd.DataFrame({"SYMBOL": b.TckrSymb, "SERIES": b.SctySrs, "OPEN": b.OpnPric, "HIGH": b.HghPric,
                                 "LOW": b.LwPric, "CLOSE": b.ClsPric, "PREVCLOSE": b.PrvsClsgPric,
                                 "VALUE": b.TtlTrfVal, "ISIN": b.ISIN})
    if d < pd.Timestamp("2024-07-15"):
        mon = d.strftime("%b").upper()
        b = get(f"https://archives.nseindia.com/content/historical/EQUITIES/{d.year}/{mon}/cm{d:%d}{mon}{d.year}bhav.csv.zip")
        if b is not None:
            b.columns = [c.strip() for c in b.columns]
            b["SERIES"] = b.SERIES.astype(str).str.strip()
            b = b[b.SERIES.isin(KEEP)]
            return pd.DataFrame({"SYMBOL": b.SYMBOL.astype(str).str.strip(), "SERIES": b.SERIES, "OPEN": b.OPEN,
                                 "HIGH": b.HIGH, "LOW": b.LOW, "CLOSE": b.CLOSE, "PREVCLOSE": b.PREVCLOSE,
                                 "VALUE": b.TOTTRDVAL, "ISIN": b.get("ISIN")})
    return None


start, end, out = sys.argv[1:4]
rows, miss = [], 0
for d in pd.bdate_range(start, end):
    c = cash(d)
    if c is None or c.empty:
        miss += 1
        continue
    c.insert(0, "Date", d.date())
    rows.append(c)
    time.sleep(0.05)
pd.concat(rows).to_csv(out, index=False, compression="gzip")
print(out, "days", len(rows), "missing", miss, "rows", sum(len(r) for r in rows))
