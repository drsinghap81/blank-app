"""Stock options (calls) + stock futures from NSE F&O bhavcopies, only for (symbol, date) windows around backtest trades.
Windows: data/optwin.csv (sym, start, end). Keeps the nearest 3 expiries, call strikes 0.85-1.40 x the near future,
and the near futures (price + lot size; old-format lot size = traded value / contracts / price).
Usage: python fetch_optstk.py START END OUT.csv"""
import io, sys, time, zipfile
import pandas as pd, requests

s = requests.Session()
s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
                  "Referer": "https://www.nseindia.com/"})
COLS = ["Date", "SYMBOL", "INST", "EXPIRY", "STRIKE", "TYPE", "OPEN", "HIGH", "LOW", "CLOSE", "SETTLE", "OI", "VOL", "LOT", "UNDER"]
W = pd.read_csv("data/optwin.csv", parse_dates=["start", "end"])
WIN = {k: list(zip(g.start, g.end)) for k, g in W.groupby("sym")}


def get(url):
    for _ in range(3):
        try:
            r = s.get(url, timeout=40)
            if r.status_code == 200 and r.content[:2] == b"PK":
                z = zipfile.ZipFile(io.BytesIO(r.content)); return pd.read_csv(z.open(z.namelist()[0]))
            return None
        except Exception:  # noqa: BLE001
            time.sleep(2)
    return None


def active(d):
    return {k for k, w in WIN.items() if any(a <= d <= b for a, b in w)}


def day(d):
    want = active(d)
    if not want:
        return None
    b = x = None
    if d >= pd.Timestamp("2024-07-01"):
        b = get(f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000.csv.zip")
        if b is not None:
            b = b[b.TckrSymb.isin(want) & b.FinInstrmTp.isin(["STO", "STF"])]
            x = pd.DataFrame({"SYMBOL": b.TckrSymb, "INST": b.FinInstrmTp.map({"STO": "OPT", "STF": "FUT"}),
                              "EXPIRY": pd.to_datetime(b.XpryDt), "STRIKE": b.StrkPric, "TYPE": b.OptnTp,
                              "OPEN": b.OpnPric, "HIGH": b.HghPric, "LOW": b.LwPric, "CLOSE": b.ClsPric,
                              "SETTLE": b.SttlmPric, "OI": b.OpnIntrst, "VOL": b.TtlTradgVol,
                              "LOT": b.get("NewBrdLotQty"), "UNDER": b.get("UndrlygPric")})
    if x is None and d < pd.Timestamp("2024-07-15"):
        mon = d.strftime("%b").upper()
        b = get(f"https://archives.nseindia.com/content/historical/DERIVATIVES/{d.year}/{mon}/fo{d:%d}{mon}{d.year}bhav.csv.zip")
        if b is None:
            return None
        b.columns = [c.strip() for c in b.columns]
        b["SYMBOL"] = b.SYMBOL.astype(str).str.strip()
        b = b[b.SYMBOL.isin(want) & b.INSTRUMENT.isin(["OPTSTK", "FUTSTK"])]
        lot = (b.VAL_INLAKH * 1e5 / (b.CONTRACTS * b.SETTLE_PR.where(b.INSTRUMENT == "FUTSTK"))).where(b.CONTRACTS > 0)
        x = pd.DataFrame({"SYMBOL": b.SYMBOL, "INST": b.INSTRUMENT.map({"OPTSTK": "OPT", "FUTSTK": "FUT"}),
                          "EXPIRY": pd.to_datetime(b.EXPIRY_DT, format="mixed", dayfirst=True), "STRIKE": b.STRIKE_PR,
                          "TYPE": b.OPTION_TYP.astype(str).str.strip(), "OPEN": b.OPEN, "HIGH": b.HIGH, "LOW": b.LOW,
                          "CLOSE": b.CLOSE, "SETTLE": b.SETTLE_PR, "OI": b.OPEN_INT, "VOL": b.CONTRACTS, "LOT": lot, "UNDER": None})
    if x is None or x.empty:
        return None
    out = []
    for u, g in x.groupby("SYMBOL"):
        f = g[g.INST == "FUT"].sort_values("EXPIRY")
        if f.empty:
            continue
        ref = float(f.CLOSE.iloc[0])
        o = g[(g.INST == "OPT") & (g.TYPE == "CE")]
        ex = sorted(o.EXPIRY.unique())[:3]
        o = o[o.EXPIRY.isin(ex) & o.STRIKE.between(ref * 0.85, ref * 1.40)]
        out += [f.head(3), o]
    r = pd.concat(out)
    r.insert(0, "Date", d.date())
    r["EXPIRY"] = r.EXPIRY.dt.date
    return r[COLS]


start, end, out = sys.argv[1:4]
rows, miss = [], 0
for d in pd.bdate_range(start, end):
    r = day(d)
    if r is None or r.empty:
        miss += 1; continue
    rows.append(r); time.sleep(0.05)
pd.concat(rows).to_csv(out, index=False)
print(out, "days", len(rows), "missing/no-window", miss, "rows", sum(len(r) for r in rows))
