"""Extract index + stock futures rows from NSE F&O bhavcopies for a date range.
Handles the old format (to early Jul 2024) and the UDiFF format (after).
Usage: python fetch_fo_range.py START END OUT.csv"""
import io, sys, time, zipfile
import pandas as pd, requests

SYMS = set("""RELIANCE HDFCBANK ICICIBANK BHARTIARTL TCS SBIN BAJFINANCE LT INFY KOTAKBANK HINDUNILVR SUNPHARMA ADANIPORTS AXISBANK TITAN HCLTECH ADANIENT M&M MARUTI ITC ULTRACEMCO ETERNAL NTPC JSWSTEEL BAJAJ-AUTO APOLLOHOSP ASIANPAINT BAJAJFINSV BEL CIPLA COALINDIA DRREDDY EICHERMOT GRASIM HDFCLIFE HINDALCO INDIGO JIOFIN MAXHEALTH NESTLEIND ONGC POWERGRID SBILIFE SHRIRAMFIN TATACONSUM TMPV TATASTEEL TECHM TRENT WIPRO BANKNIFTY NIFTY FINNIFTY RELCAPITAL RELINFRA SRTRANSFIN MANAPPURAM TATAMOTORS ZOMATO
HDFC MCDOWELL-N""".split())
s = requests.Session()
s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
                  "Referer": "https://www.nseindia.com/"})

def get(url):
    for _ in range(3):
        try:
            r = s.get(url, timeout=30)
            if r.status_code == 200 and r.content[:2] == b"PK":
                z = zipfile.ZipFile(io.BytesIO(r.content)); return pd.read_csv(z.open(z.namelist()[0]))
            return None
        except Exception:
            time.sleep(2)
    return None

start, end, out = sys.argv[1:4]
rows, miss = [], 0
for d in pd.bdate_range(start, end):
    new = None
    if d >= pd.Timestamp("2024-07-01"):
        b = get(f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000.csv.zip")
        if b is not None:
            b = b[b.FinInstrmTp.isin(["IDF", "STF"]) & b.TckrSymb.isin(SYMS)]
            new = pd.DataFrame({"Date": d.date(), "SYMBOL": b.TckrSymb, "EXPIRY": pd.to_datetime(b.XpryDt).dt.date,
                                "OPEN": b.OpnPric, "HIGH": b.HghPric, "LOW": b.LwPric, "CLOSE": b.ClsPric,
                                "LOT": b.get("NewBrdLotQty")})
    if new is None and d < pd.Timestamp("2024-07-15"):
        mon = d.strftime("%b").upper()
        b = get(f"https://archives.nseindia.com/content/historical/DERIVATIVES/{d.year}/{mon}/fo{d:%d}{mon}{d.year}bhav.csv.zip")
        if b is not None:
            b.columns = [c.strip() for c in b.columns]
            b = b[b.INSTRUMENT.isin(["FUTIDX", "FUTSTK"]) & b.SYMBOL.isin(SYMS)]
            new = pd.DataFrame({"Date": d.date(), "SYMBOL": b.SYMBOL,
                                "EXPIRY": pd.to_datetime(b.EXPIRY_DT, format="mixed", dayfirst=True).dt.date,
                                "OPEN": b.OPEN, "HIGH": b.HIGH, "LOW": b.LOW, "CLOSE": b.CLOSE, "LOT": None})
    if new is None:
        miss += 1; continue
    rows.append(new); time.sleep(0.1)
pd.concat(rows).to_csv(out, index=False)
print(out, "days", len(rows), "missing", miss)
