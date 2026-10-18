"""Build Bank Nifty futures daily OHLC (all expiries) from NSE F&O bhavcopies."""
import io, os, zipfile, time
import pandas as pd, requests

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
     "Accept": "*/*", "Referer": "https://www.nseindia.com/"}
s = requests.Session(); s.headers.update(H)
try:
    s.get("https://www.nseindia.com", timeout=20)
except Exception as e:
    print("home", e)
rows, miss = [], []
for d in pd.bdate_range("2016-11-01", "2018-01-31"):
    mon = d.strftime("%b").upper()
    fn = f"fo{d.strftime('%d')}{mon}{d.year}bhav.csv.zip"
    url = f"https://archives.nseindia.com/content/historical/DERIVATIVES/{d.year}/{mon}/{fn}"
    for attempt in range(3):
        try:
            r = s.get(url, timeout=30)
            break
        except Exception as e:
            r = None; time.sleep(2)
    if r is None or r.status_code != 200 or r.content[:2] != b"PK":
        miss.append((str(d.date()), None if r is None else r.status_code)); continue
    z = zipfile.ZipFile(io.BytesIO(r.content))
    df = pd.read_csv(z.open(z.namelist()[0]))
    df.columns = [c.strip() for c in df.columns]
    df = df[(df.INSTRUMENT == "FUTIDX") & (df.SYMBOL == "BANKNIFTY")]
    df = df.assign(Date=d.date())[["Date", "EXPIRY_DT", "OPEN", "HIGH", "LOW", "CLOSE", "SETTLE_PR", "CONTRACTS", "OPEN_INT"]]
    rows.append(df)
    time.sleep(0.3)
os.makedirs("data", exist_ok=True)
out = pd.concat(rows) if rows else pd.DataFrame()
out.to_csv("data/banknifty_fut_2017.csv", index=False)
print("rows", len(out), "missing days", len(miss), miss[:15])
