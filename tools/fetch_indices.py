"""Daily OHLC of every NSE index (broad, sectoral, thematic, strategy) from NSE's daily ind_close_all file.
Usage: python fetch_indices.py START END OUT.csv"""
import io, sys, time
import pandas as pd, requests

s = requests.Session()
s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
                  "Referer": "https://www.nseindia.com/"})
URLS = ["https://nsearchives.nseindia.com/content/indices/ind_close_all_{d:%d%m%Y}.csv",
        "https://archives.nseindia.com/content/indices/ind_close_all_{d:%d%m%Y}.csv"]


def get(d):
    for u in URLS:
        for _ in range(2):
            try:
                r = s.get(u.format(d=d), timeout=30)
                if r.status_code == 200 and b"Index" in r.content[:200]:
                    x = pd.read_csv(io.BytesIO(r.content))
                    x.columns = [c.strip() for c in x.columns]
                    return x
                if r.status_code == 404:
                    break
            except Exception:
                time.sleep(2)
    return None


start, end, out = sys.argv[1:4]
rows, got = [], 0
for d in pd.bdate_range(start, end):
    x = get(d)
    if x is None:
        continue
    col = lambda k: next(c for c in x.columns if k.lower() in c.lower())  # noqa: E731
    rows.append(pd.DataFrame({"Date": d.date(), "INDEX": x[col("Index Name")].astype(str).str.strip(),
                              "OPEN": pd.to_numeric(x[col("Open")], errors="coerce"), "HIGH": pd.to_numeric(x[col("High")], errors="coerce"),
                              "LOW": pd.to_numeric(x[col("Low")], errors="coerce"), "CLOSE": pd.to_numeric(x[col("Clos")], errors="coerce")}))
    got += 1
    if got % 100 == 0:
        print(d.date(), got, flush=True)
    time.sleep(0.25)
pd.concat(rows).to_csv(out, index=False)
print("days", got, "rows", sum(len(r) for r in rows))
