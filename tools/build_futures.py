"""Build near-month continuous futures series per symbol from extracted bhavcopy rows.

Input : one or more CSVs with Date, SYMBOL, EXPIRY, OPEN, HIGH, LOW, CLOSE, LOT
Output: data/futures/<SYMBOL>.csv with Date, Open, High, Low, Close, Expiry, Lot

* Near month = earliest expiry on or after the trade date (rolls after expiry day).
* Renamed / merged symbols are stitched (old history first).
* Splits / bonuses / demergers: a one-day close ratio below 0.65 or above 1.5 is
  treated as a corporate action and all earlier prices are scaled by that ratio
  (back-adjusted series, so tops/bottoms and % returns stay continuous).
Usage: python build_futures.py OUT_DIR chunk1.csv chunk2.csv ...
"""
import os
import sys

import numpy as np
import pandas as pd

ALIASES = {"ETERNAL": ["ZOMATO"], "SHRIRAMFIN": ["SRTRANSFIN"], "TMPV": ["TATAMOTORS"]}
FILE_NAMES = {"M&M": "M_M"}  # characters that are awkward in file names


def file_name(sym: str) -> str:
    return FILE_NAMES.get(sym, sym) + ".csv"


def near_month(raw: pd.DataFrame) -> pd.DataFrame:
    r = raw[raw["EXPIRY"] >= raw["Date"]].sort_values(["Date", "EXPIRY"])
    g = r.groupby("Date").first()
    out = g.rename(columns={"OPEN": "Open", "HIGH": "High", "LOW": "Low", "CLOSE": "Close",
                            "EXPIRY": "Expiry", "LOT": "Lot"})[["Open", "High", "Low", "Close", "Expiry", "Lot"]]
    return out[(out["Close"] > 0) & (out["High"] >= out["Low"])]


def adjust_actions(d: pd.DataFrame, sym: str) -> pd.DataFrame:
    d = d.copy()
    ratio = d["Close"] / d["Close"].shift(1)
    for dt, r in ratio[(ratio < 0.65) | (ratio > 1.5)].items():
        prev = d.index < dt
        d.loc[prev, ["Open", "High", "Low", "Close"]] *= r
        print(f"  {sym}: corporate-action adjust on {dt.date()} x{r:.4f}")
    return d


def main(out_dir, files):
    raw = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    raw["Date"] = pd.to_datetime(raw["Date"])
    raw["EXPIRY"] = pd.to_datetime(raw["EXPIRY"])
    for c in ("OPEN", "HIGH", "LOW", "CLOSE"):
        raw[c] = pd.to_numeric(raw[c], errors="coerce")
    raw = raw.dropna(subset=["CLOSE"]).drop_duplicates(["Date", "SYMBOL", "EXPIRY"])
    os.makedirs(out_dir, exist_ok=True)
    alias_of = {a: k for k, v in ALIASES.items() for a in v}
    built = {}
    for sym, g in raw.groupby("SYMBOL"):
        built[sym] = near_month(g)
    summary = []
    for sym, d in built.items():
        if sym in alias_of:
            continue
        for old in ALIASES.get(sym, []):
            if old in built:
                o = built[old]
                o = o[o.index < (d.index.min() if len(d) else o.index.max() + pd.Timedelta(days=1))]
                d = pd.concat([o, d])
        d = adjust_actions(d.sort_index(), sym)
        d.index.name = "Date"
        d.round(2).to_csv(os.path.join(out_dir, file_name(sym)))
        summary.append((sym, len(d), d.index.min().date(), d.index.max().date()))
    for s in sorted(summary):
        print(f"{s[0]:12} {s[1]:5} bars {s[2]} -> {s[3]}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
