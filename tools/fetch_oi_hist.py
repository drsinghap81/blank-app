"""Daily option-OI features for a few liquid underlyings, from NSE F&O bhavcopies (for backtesting the
trapped-writer signal). One row per day per symbol, using the nearest expiry with >= 3 days left:
  fut        near-month future close (same-day reference price)
  put_max_k  strike with the most put OI (whole chain),  put_max_oi
  call_max_k strike with the most call OI (whole chain), call_max_oi
  put_otm_k  most put OI at/below fut, call_otm_k most call OI at/above fut, pcr
Usage: python fetch_oi_hist.py START END OUT.csv
"""
import io
import sys
import time
import zipfile

import pandas as pd
import requests

SYMS = {"NIFTY", "BANKNIFTY", "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "SBIN", "AXISBANK",
        "ITC", "LT", "KOTAKBANK", "BHARTIARTL", "HINDUNILVR", "MARUTI", "TATASTEEL"}
s = requests.Session()
s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
                  "Referer": "https://www.nseindia.com/"})


def get(url):
    for _ in range(3):
        try:
            r = s.get(url, timeout=40)
            if r.status_code == 200 and r.content[:2] == b"PK":
                z = zipfile.ZipFile(io.BytesIO(r.content))
                return pd.read_csv(z.open(z.namelist()[0]))
            return None
        except Exception:  # noqa: BLE001
            time.sleep(2)
    return None


def load(d):
    if d >= pd.Timestamp("2024-07-01"):
        b = get(f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000.csv.zip")
        if b is not None:
            b = b[b.TckrSymb.isin(SYMS)]
            return pd.DataFrame({"sym": b.TckrSymb, "kind": b.FinInstrmTp.map({"IDO": "OPT", "STO": "OPT", "IDF": "FUT", "STF": "FUT"}),
                                 "exp": pd.to_datetime(b.XpryDt), "k": b.StrkPric, "typ": b.OptnTp, "oi": b.OpnIntrst,
                                 "close": b.ClsPric})
    if d < pd.Timestamp("2024-07-15"):
        mon = d.strftime("%b").upper()
        b = get(f"https://archives.nseindia.com/content/historical/DERIVATIVES/{d.year}/{mon}/fo{d:%d}{mon}{d.year}bhav.csv.zip")
        if b is None:
            return None
        b.columns = [c.strip() for c in b.columns]
        b["SYMBOL"] = b.SYMBOL.astype(str).str.strip()
        b = b[b.SYMBOL.isin(SYMS)]
        inst = b.INSTRUMENT.astype(str).str.strip()
        return pd.DataFrame({"sym": b.SYMBOL, "kind": inst.map({"OPTIDX": "OPT", "OPTSTK": "OPT", "FUTIDX": "FUT", "FUTSTK": "FUT"}),
                             "exp": pd.to_datetime(b.EXPIRY_DT, format="mixed", dayfirst=True), "k": b.STRIKE_PR,
                             "typ": b.OPTION_TYP.astype(str).str.strip(), "oi": b.OPEN_INT, "close": b.CLOSE})
    return None


def features(d, x):
    out = []
    for sym, g in x.groupby("sym"):
        f = g[g.kind == "FUT"].sort_values("exp")
        o = g[g.kind == "OPT"]
        if f.empty or o.empty:
            continue
        fut = float(f.close.iloc[0])
        exps = sorted(e for e in o.exp.unique() if (e - d).days >= 3)
        if not exps:
            continue
        e = exps[0]
        oe = o[o.exp == e]
        pe = oe[oe.typ == "PE"].groupby("k").oi.sum()
        ce = oe[oe.typ == "CE"].groupby("k").oi.sum()
        if pe.empty or ce.empty or pe.max() <= 0 or ce.max() <= 0:
            continue
        po, co = pe[pe.index <= fut], ce[ce.index >= fut]
        out.append(dict(date=d.date(), sym=sym, expiry=e.date(), fut=fut,
                        put_max_k=float(pe.idxmax()), put_max_oi=int(pe.max()),
                        call_max_k=float(ce.idxmax()), call_max_oi=int(ce.max()),
                        put_otm_k=float(po.idxmax()) if len(po) and po.max() > 0 else None,
                        call_otm_k=float(co.idxmax()) if len(co) and co.max() > 0 else None,
                        pcr=round(float(pe.sum() / ce.sum()), 3)))
    return out


if __name__ == "__main__":
    start, end, outp = sys.argv[1:4]
    rows, miss = [], 0
    for d in pd.bdate_range(start, end):
        x = load(d)
        if x is None or x.empty:
            miss += 1
            continue
        rows += features(d, x)
        time.sleep(0.05)
    pd.DataFrame(rows).to_csv(outp, index=False)
    print(outp, "rows", len(rows), "missing days", miss)
