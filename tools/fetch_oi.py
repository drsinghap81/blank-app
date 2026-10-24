"""Option-OI support / resistance for every NSE F&O underlying, from the latest F&O bhavcopy.

For each underlying, on its nearest expiry:
  support    = strike with the highest PUT open interest
  resistance = strike with the highest CALL open interest
Also the 2nd-highest strikes and the put/call OI ratio.
Writes data/oi/oi_levels.json keyed by the app's Yahoo ticker (e.g. RELIANCE.NS, ^NSEI, ^NSEBANK).
Runs nightly in GitHub Actions (paper-trade workflow) after NSE publishes the bhavcopy.
"""
import io
import json
import os
import sys
import time
import zipfile
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "oi", "oi_levels.json")
INDEX_TICKERS = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK", "FINNIFTY": "NIFTY_FIN_SERVICE.NS",
                 "MIDCPNIFTY": "NIFTY_MID_SELECT.NS", "NIFTYNXT50": "^NSMIDCP"}
s = requests.Session()
s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
                  "Referer": "https://www.nseindia.com/"})


def bhavcopy(d):
    url = f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"
    for _ in range(3):
        try:
            r = s.get(url, timeout=40)
            if r.status_code == 200 and r.content[:2] == b"PK":
                z = zipfile.ZipFile(io.BytesIO(r.content))
                return pd.read_csv(z.open(z.namelist()[0]))
            return None
        except Exception:  # noqa: BLE001
            time.sleep(3)
    return None


def levels(g, under=None):
    """support = biggest put OI at or below the price, resistance = biggest call OI at or above it
    (out-of-the-money writing). After a sharp fall the biggest put OI often sits ABOVE the price
    (puts written earlier, now in the money) — that is kept separately as *_any."""
    ce = g[g.OptnTp == "CE"].groupby("StrkPric").OpnIntrst.sum()
    pe = g[g.OptnTp == "PE"].groupby("StrkPric").OpnIntrst.sum()
    if ce.empty or pe.empty or ce.max() <= 0 or pe.max() <= 0:
        return None
    any_s, any_r = float(pe.idxmax()), float(ce.idxmax())
    pcr = round(float(pe.sum() / ce.sum()), 2)          # whole chain
    if under:
        pe_o, ce_o = pe[pe.index <= under], ce[ce.index >= under]
        pe = pe_o if len(pe_o) and pe_o.max() > 0 else pe
        ce = ce_o if len(ce_o) and ce_o.max() > 0 else ce
    c2, p2 = ce.nlargest(2), pe.nlargest(2)
    return dict(support_any=any_s, resistance_any=any_r,
        support=float(p2.index[0]), support_oi=int(p2.iloc[0]),
        support_2=float(p2.index[1]) if len(p2) > 1 else None,
        resistance=float(c2.index[0]), resistance_oi=int(c2.iloc[0]),
        resistance_2=float(c2.index[1]) if len(c2) > 1 else None,
        pcr=pcr,
    )


def main():
    ist = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    b, day = None, None
    for back in range(0, 8):
        d = (ist - timedelta(days=back)).date()
        if d.weekday() >= 5:
            continue
        b = bhavcopy(d)
        if b is not None:
            day = d
            break
    if b is None:
        sys.exit("no F&O bhavcopy found in the last week")
    b = b[b.FinInstrmTp.isin(["IDO", "STO"])].copy()
    b["XpryDt"] = pd.to_datetime(b.XpryDt)
    out = {}
    for sym, g in b.groupby("TckrSymb"):
        exps = sorted(e for e in g.XpryDt.unique() if e.date() >= day)
        if not exps:
            continue
        e = exps[0]
        under = float(g.UndrlygPric.dropna().iloc[0]) if "UndrlygPric" in g and g.UndrlygPric.notna().any() else None
        lv = levels(g[g.XpryDt == e], under)
        if lv is None:
            continue
        ticker = INDEX_TICKERS.get(sym, f"{sym}.NS")
        out[ticker] = dict(symbol=sym, date=str(day), expiry=str(e.date()), underlying=under, **lv)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(dict(date=str(day), levels=out), open(OUT, "w"), indent=1)
    print(f"OI levels for {len(out)} underlyings on {day}")


if __name__ == "__main__":
    main()
