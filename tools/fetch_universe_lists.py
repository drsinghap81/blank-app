"""Download index constituent lists (Nifty 500 etc.) and the current F&O stock list."""
import io, os, zipfile
from datetime import date, timedelta
import pandas as pd, requests
os.makedirs("data/universe", exist_ok=True)
s = requests.Session()
s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
                  "Referer": "https://www.nseindia.com/"})
lists = {"nifty500": "ind_nifty500list.csv", "nifty50": "ind_nifty50list.csv",
         "niftynext50": "ind_niftynext50list.csv", "niftymidcap150": "ind_niftymidcap150list.csv",
         "niftysmallcap250": "ind_niftysmallcap250list.csv"}
for name, fn in lists.items():
    for url in (f"https://nsearchives.nseindia.com/content/indices/{fn}",
                f"https://archives.nseindia.com/content/indices/{fn}",
                f"https://www.niftyindices.com/IndexConstituent/{fn}"):
        try:
            r = s.get(url, timeout=30)
            if r.status_code == 200 and b"Symbol" in r.content[:300]:
                df = pd.read_csv(io.BytesIO(r.content))
                df.to_csv(f"data/universe/{name}.csv", index=False)
                print(name, len(df), url); break
        except Exception as e:
            print(name, "err", url, e)
    else:
        print(name, "FAILED")
# current F&O stocks from the latest bhavcopy
d = date.today()
for k in range(10):
    day = d - timedelta(days=k)
    r = s.get(f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{day:%Y%m%d}_F_0000.csv.zip", timeout=30)
    if r.status_code == 200 and r.content[:2] == b"PK":
        z = zipfile.ZipFile(io.BytesIO(r.content)); b = pd.read_csv(z.open(z.namelist()[0]))
        f = b[b.FinInstrmTp == "STF"].groupby("TckrSymb").agg(Lot=("NewBrdLotQty", "first"), FutTurnover=("TtlTrfVal", "sum")).reset_index()
        f.rename(columns={"TckrSymb": "Symbol"}).sort_values("FutTurnover", ascending=False).to_csv("data/universe/fno_stocks.csv", index=False)
        print("fno", len(f), day); break
