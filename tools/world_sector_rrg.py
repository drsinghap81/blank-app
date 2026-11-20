"""Relative rotation of the official sector benchmarks for the US and Australia (20 Nov 2026, Amritpal: "Yes" to matching India).
  US  : the 11 SPDR Select Sector ETFs vs the S&P 500
  ASX : the S&P/ASX 200 sector indices vs the ASX 200
Same formulas and output shape as tools/sector_rrg.py (weekly 8 weeks / daily 10 sessions). Yahoo daily closes.
Usage: python tools/world_sector_rrg.py US|ASX [--dry]  -> data/scan/us|asx/sector_rrg.json"""
import json
import sys

import pandas as pd
import yfinance as yf

sys.path.insert(0, "tools")
from sector_rrg import view, write_hist  # noqa: E402

CFG = {
    "US": dict(bench=("^GSPC", "S&P 500"), out="data/scan/us/sector_rrg.json", names={
        "XLK": "Technology", "XLF": "Financials", "XLV": "Health Care", "XLE": "Energy", "XLI": "Industrials", "XLY": "Cons Discretionary",
        "XLP": "Cons Staples", "XLU": "Utilities", "XLB": "Materials", "XLRE": "Real Estate", "XLC": "Communication"}),
    "ASX": dict(bench=("^AXJO", "ASX 200"), out="data/scan/asx/sector_rrg.json", names={
        "^AXEJ": "Energy", "^AXMJ": "Materials", "^AXNJ": "Industrials", "^AXDJ": "Cons Discretionary", "^AXSJ": "Cons Staples",
        "^AXHJ": "Health Care", "^AXFJ": "Financials", "^AXIJ": "Info Tech", "^AXTJ": "Communication", "^AXUJ": "Utilities", "^AXPJ": "A-REITs"}),
}


def main(mk, dry=False):
    cf = CFG[mk]; b, bname = cf["bench"]
    d = yf.download(list(cf["names"]) + [b], period="2y", interval="1d", progress=False, auto_adjust=True, group_by="column", threads=True)["Close"]
    d = d.dropna(how="all").ffill()
    bench = d.pop(b); C = d[[k for k in cf["names"] if k in d.columns and d[k].notna().sum() > 120]]
    print(mk, "got", list(C.columns), "last", C.index[-1].date(), flush=True)
    W = C.resample("W-FRI").last(); BW = bench.resample("W-FRI").last()
    if W.index[-1] > C.index[-1]:
        W.index = list(W.index[:-1]) + [C.index[-1]]; BW.index = W.index
    out = dict(asof=str(C.index[-1].date()), bench=bname, weekly=view(W, BW, 10, 1, 3, 8, cf["names"]), daily=view(C, bench, 50, 10, 5, 10, cf["names"]),
               method=__doc__)
    for v in ("weekly", "daily"):
        print(mk, v, {q: [k for k, r in out[v].items() if r["now"] == q] for q in ("Leading", "Improving", "Weakening", "Lagging")}, flush=True)
    if not dry:
        json.dump(out, open(cf["out"], "w"), separators=(",", ":"))
        write_hist(cf["out"].replace(".json", "_hist.json"), C, bench, W, BW, cf["names"])


if __name__ == "__main__":
    for m in [a for a in sys.argv[1:] if not a.startswith("--")] or ["US", "ASX"]:
        try:
            main(m, "--dry" in sys.argv)
        except Exception as e:  # noqa: BLE001
            print("FAILED", m, e)
