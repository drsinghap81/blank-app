"""Daily OHLC + volume for the NSE indices used by the index alerts (20 Nov 2026). Source: NSE ind_close_all_DDMMYYYY.csv
(Open / High / Low / Closing Index Value, Volume = shares traded in the index's stocks). Cache data/scan/index_ohlcv.csv.gz;
each run downloads only the missing days (first run backfills from 2016, ~10 min)."""
import io
import os
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

CACHE = "data/scan/index_ohlcv.csv.gz"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36", "Referer": "https://www.nseindia.com/"}


def day_file(d, keep):
    for u in ("https://nsearchives.nseindia.com/content/indices/ind_close_all_{d:%d%m%Y}.csv",
              "https://archives.nseindia.com/content/indices/ind_close_all_{d:%d%m%Y}.csv"):
        for _ in range(2):
            try:
                r = requests.get(u.format(d=d), headers=UA, timeout=25)
                if r.status_code == 404:
                    break
                if r.status_code == 200 and b"Index" in r.content[:200]:
                    x = pd.read_csv(io.BytesIO(r.content)); x.columns = [c.strip() for c in x.columns]
                    col = lambda k: next(c for c in x.columns if k.lower() in c.lower())  # noqa: E731
                    o = pd.DataFrame({"Date": d.normalize(), "INDEX": x[col("Index Name")].astype(str).str.strip().str.upper(),
                                      "Open": pd.to_numeric(x[col("Open")], errors="coerce"), "High": pd.to_numeric(x[col("High")], errors="coerce"),
                                      "Low": pd.to_numeric(x[col("Low")], errors="coerce"), "Close": pd.to_numeric(x[col("Clos")], errors="coerce"),
                                      "Volume": pd.to_numeric(x[col("Volume")], errors="coerce")})
                    return o[o.INDEX.isin(keep)]
            except Exception:  # noqa: BLE001
                time.sleep(1)
    return None


def update(keep, start="2016-01-01"):
    keep = {k.upper() for k in keep}
    have = pd.read_csv(CACHE, parse_dates=["Date"]) if os.path.exists(CACHE) else pd.DataFrame(columns=["Date", "INDEX", "Open", "High", "Low", "Close", "Volume"])
    s0 = (have.Date.max() + pd.Timedelta(days=1)) if len(have) else pd.Timestamp(start)
    days = list(pd.bdate_range(s0, pd.Timestamp.today().normalize()))
    with ThreadPoolExecutor(6) as ex:
        new = [x for x in ex.map(lambda d: day_file(d, keep), days) if x is not None]
    H = pd.concat([have] + new) if new else have
    H["Date"] = pd.to_datetime(H.Date)
    H = H.drop_duplicates(["Date", "INDEX"], keep="last").sort_values(["INDEX", "Date"])
    H = H[H.INDEX.isin(keep)]
    if new:
        H.to_csv(CACHE, index=False)
    print("index_ohlcv rows", len(H), "new days", len(new), flush=True)
    return H
