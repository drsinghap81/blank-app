"""Industry basket intraday, breadth + Pulse (20 Nov 2026, Amritpal: "see in which industries more stocks are turning green or red ...
keep strong-Pulse ones as buys as they are the ones which will bounce, and vice versa").

At 10:15 (end of the first hourly bar), for every NSE basic industry (3+ liquid stocks):
  breadth  = share of its stocks above yesterday's close (green)
  gap      = average opening move vs yesterday's close (opened red if < 0)
  Pulse    = share of its stocks 'trending' over the last 21 sessions as of YESTERDAY's close (same rule as the app's Pulse:
             relative strength > 100, 9 EMA > 21 EMA, above a rising 150-day average, within 25% of the 52-week high), ranked
             against the other industries that day (top 25% = strong, bottom 25% = weak).
Rules (K = up to 2 industries a side, most extreme breadth first; whole basket risks 1% of capital, equal risk per stock):
  BREADTH ONLY      buy breadth >= 70%, sell breadth <= 30%
  WITH PULSE        buy strong-Pulse industries with breadth >= 60%, sell weak-Pulse with breadth <= 40%
  BOUNCE            buy strong-Pulse that OPENED RED and now breadth >= 60%; sell weak-Pulse that OPENED GREEN and now <= 40%
  AGAINST PULSE     (control) buy weak-Pulse with breadth >= 60%, sell strong-Pulse with breadth <= 40%
Entry 10:15 close, stop first-hour low / high (or 1% fixed), exit 15:15, 0.10% cost per stock."""
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, "tools/research")
import industry_basket_intraday as B  # noqa: E402
import datetime as dt  # noqa: E402

IND, SYMS = B.IND, B.SYMS


def pulse_table():
    d = yf.download([s + ".NS" for s in SYMS] + ["^NSEI"], period="5y", interval="1d", progress=False, group_by="column", auto_adjust=True, threads=True)
    C = d["Close"].copy(); C.columns = [c[:-3] if c.endswith(".NS") else c for c in C.columns]
    bench = C.pop("^NSEI") if "^NSEI" in C.columns else C.mean(axis=1)
    rpi = lambda k: 100 * (C / C.shift(k)).div(bench / bench.shift(k), axis=0)  # noqa: E731
    w = (rpi(10) + rpi(63) + rpi(126)) / 3
    e9 = C.ewm(span=9, adjust=False).mean(); e21 = C.ewm(span=21, adjust=False).mean(); s150 = C.rolling(150).mean()
    hi52 = C.rolling(250, min_periods=120).max()
    tr = ((w > 100) & (e9 > e21) & (C > s150) & (s150 > s150.shift(20)) & (C >= 0.75 * hi52)).astype(float).where(C.notna())
    share = tr.rolling(21, min_periods=15).mean()
    P = pd.DataFrame({k: share[[s for s in v if s in share.columns]].mean(axis=1) for k, v in IND.items()})
    pct = P.rank(axis=1, pct=True)
    pct.index = [x.date() for x in pct.index]
    print("R| Pulse table", P.shape, "first valid", P.dropna(how="all").index[0], flush=True)
    return pct


def run_rules(rows, O, H, L, C, pct, tag):
    days_pulse = sorted(pct.index)
    for stop in ("first-hour", "1% fixed"):
        for rule in ("BREADTH ONLY", "WITH PULSE", "BOUNCE", "AGAINST PULSE (control)"):
            for side in ("mixed", "buy only", "sell only"):
                daily = {}
                for row in rows:
                    prev = [d for d in days_pulse if d < row["day"]]
                    if not prev:
                        continue
                    pr = pct.loc[prev[-1]]
                    cand_b, cand_s = [], []
                    for ind, ss in IND.items():
                        r1 = row["r1"].reindex(ss).dropna()
                        if len(r1) < 3 or pd.isna(pr.get(ind)):
                            continue
                        br = float((r1 > 0).mean()); gap = float(row["gap"].reindex(ss).dropna().mean()); p = float(pr[ind])
                        strong, weak = p >= 0.75, p <= 0.25
                        if rule == "BREADTH ONLY":
                            b, s_ = br >= 0.7, br <= 0.3
                        elif rule == "WITH PULSE":
                            b, s_ = strong and br >= 0.6, weak and br <= 0.4
                        elif rule == "BOUNCE":
                            b, s_ = strong and gap < 0 and br >= 0.6, weak and gap > 0 and br <= 0.4
                        else:
                            b, s_ = weak and br >= 0.6, strong and br <= 0.4
                        if b:
                            cand_b.append((br, ind))
                        if s_:
                            cand_s.append((br, ind))
                    buys = [k for _, k in sorted(cand_b, reverse=True)[:2]] if side != "sell only" else []
                    sells = [k for _, k in sorted(cand_s)[:2]] if side != "buy only" else []
                    Rs = [B.trade(row, s, 1, O, H, L, C, stop) for k in buys for s in IND[k]] + [B.trade(row, s, -1, O, H, L, C, stop) for k in sells for s in IND[k]]
                    Rs = [x for x in Rs if x is not None]
                    if Rs:
                        daily[row["day"]] = float(np.mean(Rs))
                B.stats(f"{tag} stop {stop} | {rule} | {side}", daily)


if __name__ == "__main__":
    pct = pulse_table()
    O, H, L, C = B.dl("1h", "730d")
    rows = B.run(O, H, L, C, dt.time(10, 15), dt.time(15, 15), "hourly")
    run_rules(rows, O, H, L, C, pct, "1h 10:15")
    if not os.environ.get("LIMIT"):
        O5, H5, L5, C5 = B.dl("5m", "60d")
        rows5 = B.run(O5, H5, L5, C5, dt.time(9, 45), dt.time(15, 15), "5m")
        run_rules(rows5, O5, H5, L5, C5, pct, "5m 09:45")
