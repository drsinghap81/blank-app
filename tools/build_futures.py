"""Build near-month continuous futures series per symbol from extracted bhavcopy rows.

Input : one or more CSVs with Date, SYMBOL, EXPIRY, OPEN, HIGH, LOW, CLOSE, LOT
Output: data/futures/<SYMBOL>.csv with Date, Open, High, Low, Close, Expiry, Lot

* Near month = earliest expiry on or after the trade date (rolls after expiry day).
* Renamed / merged symbols are stitched (old history first).
* Splits / bonuses / demergers: a one-day close ratio below 0.65 or above 1.5 is
  treated as a corporate action and all earlier prices are scaled by that ratio
  (back-adjusted series, so tops/bottoms and % returns stay continuous).
Usage: python build_futures.py [--yahoo=DIR] OUT_DIR chunk1.csv chunk2.csv ...
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


YAHOO_DIR = None  # folder with <SYM>.csv (Date, Close) of corporate-action-adjusted stock closes
START_AFTER = {"ASIANPAINT": "2009-06-01"}   # early futures data too illiquid / erratic
MANUAL_ACTIONS = {"TMPV": ["2025-10-14"], "ADANIENT": ["2015-06-03"]}     # demergers the reference series doesn't flag


def after_last_gap(d: pd.DataFrame, sym: str, days: int = 30) -> pd.DataFrame:
    """If the futures contract stopped trading for a long spell, keep only the latest run."""
    gaps = d.index.to_series().diff().dt.days
    big = gaps[gaps > days]
    if len(big):
        print(f"  {sym}: trading gap before {big.index[-1].date()} ({int(big.iloc[-1])} days) — earlier data dropped")
        d = d[d.index >= big.index[-1]]
    return d


def drop_spikes(d: pd.DataFrame, sym: str) -> pd.DataFrame:
    """Remove isolated bad bars: a > 20% jump that fully reverses the next day."""
    c = d["Close"]
    r1 = c / c.shift(1)
    r2 = c.shift(-1) / c
    bad = ((r1 - 1).abs() > 0.2) & ((r1 * r2 - 1).abs() < 0.08)
    for dt in d.index[bad]:
        print(f"  {sym}: dropped bad bar {dt.date()}")
    return d[~bad]


def adjust_actions(d: pd.DataFrame, sym: str) -> pd.DataFrame:
    """Back-adjust splits / bonuses / demergers.
    With an adjusted reference (Yahoo) series: any day whose futures move differs
    from the reference move by > 8% is a corporate action (factor = futures ratio /
    reference ratio). Real crashes move both series equally and are left alone.
    Without a reference: only one-day ratios < 0.65 or > 1.5 are adjusted."""
    d = d.copy()
    ratio = d["Close"] / d["Close"].shift(1)
    ref = None
    if YAHOO_DIR:
        p = os.path.join(YAHOO_DIR, sym.replace("&", "_") + ".csv")
        if os.path.exists(p):
            ref = pd.read_csv(p, index_col=0, parse_dates=True)["Close"]
    events = []
    cand = ratio[(ratio - 1).abs() > 0.12]
    for dt, r in cand.items():
        i = d.index.get_loc(dt)
        prev_dt = d.index[i - 1]
        f = None
        if ref is not None and dt in ref.index and prev_dt in ref.index and ref[prev_dt] > 0:
            rr = ref[dt] / ref[prev_dt]
            if abs(r / rr - 1) > 0.15:
                f = r / rr
        elif r < 0.65 or r > 1.5:
            f = r
        if dt.strftime("%Y-%m-%d") in MANUAL_ACTIONS.get(sym, []):
            f = r
        if f is not None:
            events.append((dt, f))
    for dt, f in events:
        d.loc[d.index < dt, ["Open", "High", "Low", "Close"]] *= f
        print(f"  {sym}: corporate-action adjust on {dt.date()} x{f:.4f}")
    return d


def main(out_dir, files, yahoo_dir=None):
    global YAHOO_DIR
    YAHOO_DIR = yahoo_dir
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
        if sym in alias_of or sym in ("HDFC", "MCDOWELL-N"):
            continue
        for old in ALIASES.get(sym, []):
            if old in built:
                o = built[old]
                o = o[o.index < (d.index.min() if len(d) else o.index.max() + pd.Timedelta(days=1))]
                d = pd.concat([o, d])
        d = d.sort_index()
        if sym in START_AFTER:
            d = d[d.index >= START_AFTER[sym]]
        d = adjust_actions(drop_spikes(after_last_gap(d, sym), sym), sym)
        d.index.name = "Date"
        d[["Open", "High", "Low", "Close"]] = d[["Open", "High", "Low", "Close"]].round(2)
        d.to_csv(os.path.join(out_dir, file_name(sym)))
        summary.append((sym, len(d), d.index.min().date(), d.index.max().date()))
    for s in sorted(summary):
        print(f"{s[0]:12} {s[1]:5} bars {s[2]} -> {s[3]}")


if __name__ == "__main__":
    args = sys.argv[1:]
    yd = None
    if args and args[0].startswith("--yahoo="):
        yd = args.pop(0).split("=", 1)[1]
    main(args[0], args[1:], yd)
