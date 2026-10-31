"""Daily NIFTY / BANKNIFTY index options + futures from NSE F&O bhavcopies (end-of-day).
Keeps the nearest 3 expiries and strikes within +-12% of the near-month future.
Usage: python fetch_opt.py START END OUT.csv"""
import io, sys, time, zipfile
import pandas as pd, requests

s = requests.Session()
s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
                  "Referer": "https://www.nseindia.com/"})
UND = ("NIFTY", "BANKNIFTY")
MONTHLY = False
COLS = ["Date", "SYMBOL", "INST", "EXPIRY", "STRIKE", "TYPE", "OPEN", "HIGH", "LOW", "CLOSE", "SETTLE", "OI", "VOL"]


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


def day(d):
    b = None
    if d >= pd.Timestamp("2024-07-01"):
        b = get(f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000.csv.zip")
        if b is not None:
            b = b[b.TckrSymb.isin(UND) & b.FinInstrmTp.isin(["IDO", "IDF"])]
            x = pd.DataFrame({"SYMBOL": b.TckrSymb, "INST": b.FinInstrmTp.map({"IDO": "OPT", "IDF": "FUT"}),
                              "EXPIRY": pd.to_datetime(b.XpryDt), "STRIKE": b.StrkPric, "TYPE": b.OptnTp,
                              "OPEN": b.OpnPric, "HIGH": b.HghPric, "LOW": b.LwPric, "CLOSE": b.ClsPric,
                              "SETTLE": b.SttlmPric, "OI": b.OpnIntrst, "VOL": b.TtlTradgVol})
    if b is None and d < pd.Timestamp("2024-07-15"):
        mon = d.strftime("%b").upper()
        b = get(f"https://archives.nseindia.com/content/historical/DERIVATIVES/{d.year}/{mon}/fo{d:%d}{mon}{d.year}bhav.csv.zip")
        if b is None:
            return None
        b.columns = [c.strip() for c in b.columns]
        b["SYMBOL"] = b.SYMBOL.astype(str).str.strip()
        b = b[b.SYMBOL.isin(UND) & b.INSTRUMENT.isin(["OPTIDX", "FUTIDX"])]
        x = pd.DataFrame({"SYMBOL": b.SYMBOL, "INST": b.INSTRUMENT.map({"OPTIDX": "OPT", "FUTIDX": "FUT"}),
                          "EXPIRY": pd.to_datetime(b.EXPIRY_DT, format="mixed", dayfirst=True), "STRIKE": b.STRIKE_PR,
                          "TYPE": b.OPTION_TYP.astype(str).str.strip(), "OPEN": b.OPEN, "HIGH": b.HIGH, "LOW": b.LOW,
                          "CLOSE": b.CLOSE, "SETTLE": b.SETTLE_PR, "OI": b.OPEN_INT, "VOL": b.CONTRACTS})
    if b is None:
        return None
    out = []
    for u, g in x.groupby("SYMBOL"):
        f = g[g.INST == "FUT"].sort_values("EXPIRY")
        if f.empty:
            continue
        ref = float(f.CLOSE.iloc[0])
        o = g[g.INST == "OPT"]
        ex = sorted(o.EXPIRY.unique())
        if LONG:         # NIFTY only: every expiry 50-200 days out (quarterly / half-yearly), strikes +-25%
            if u != "NIFTY":
                continue
            ex = [e for e in ex if 50 <= (e - d).days <= 200]
            o = o[o.EXPIRY.isin(ex) & (o.STRIKE.between(ref * 0.75, ref * 1.25))]
            out += [f.head(3), o]
            continue
        if MONTHLY:      # last expiry of each calendar month, up to ~80 days out
            m = pd.Series(ex); m = m.groupby(m.dt.to_period("M")).max()
            ex = [e for e in m if (e - d).days <= 80]
        else:
            ex = ex[:3]
        o = o[o.EXPIRY.isin(ex) & (o.STRIKE.between(ref * 0.88, ref * 1.12))]
        out += [f.head(2), o]
    if not out:
        return None
    r = pd.concat(out)
    r.insert(0, "Date", d.date())
    r["EXPIRY"] = r.EXPIRY.dt.date
    return r[COLS]


start, end, out = sys.argv[1:4]
MONTHLY = len(sys.argv) > 4 and sys.argv[4] == "monthly"
LONG = len(sys.argv) > 4 and sys.argv[4] == "long"
rows, miss = [], 0
for d in pd.bdate_range(start, end):
    r = day(d)
    if r is None or r.empty:
        miss += 1
        continue
    rows.append(r)
    time.sleep(0.05)
pd.concat(rows).to_csv(out, index=False)
print(out, "days", len(rows), "missing", miss, "rows", sum(len(r) for r in rows))
