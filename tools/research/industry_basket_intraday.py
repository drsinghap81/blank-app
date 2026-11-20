"""Industry basket intraday test (20 Nov 2026, Amritpal: "trade stocks intraday by basket by industry - if an industry starts well buy,
if bad sell; a mixed basket with 1% risk").

Universe: liquid NSE stocks in NSE's official basic industries (data/scan/group_pulse.json 'nse' rows, industries with 3+ liquid stocks).
Hourly bars (Yahoo, ~3 years). Each day:
  first hour = 09:15-10:15 bar. Stock start = first-hour close vs yesterday's close (gap + first hour).
  industry start = average of its stocks; breadth = share of its stocks up.
  BUY the K strongest industries' stocks, SELL the K weakest, at the 10:15 close.
  stop: first-hour low (buy) / high (sell); exit 15:15 (close of the 14:15 bar) if not stopped. Stop fills at the stop, or at the bar's
  open if it gapped through. Cost 0.10% per stock round trip.
Each stock risks the same; the whole basket risks 1% of capital -> day P&L (% of capital) = 1% x average R of the basket's stocks.
Also: 5-minute bars (60 days) with a 09:45 start.
LIMIT env var = pilot on that many stocks."""
import os
import time

import numpy as np
import pandas as pd
import yfinance as yf

LIMIT = int(os.environ.get("LIMIT", "0"))
COST = 0.001
G = pd.read_json("data/scan/group_pulse.json", typ="series")["nse"]["rows"]
IND = {}
for r in G:
    liq = [m["symbol"] for m in r["members"] if m.get("liquid")]
    if len(liq) >= 3:
        IND[r["basic"]] = liq
SYMS = sorted({s for v in IND.values() for s in v})
if LIMIT:
    keep = list(IND)[:max(3, LIMIT // 4)]
    IND = {k: IND[k] for k in keep}; SYMS = sorted({s for v in IND.values() for s in v})
print("R| industries", len(IND), "stocks", len(SYMS), flush=True)


def dl(interval, period):
    O, H, L, C = {}, {}, {}, {}
    for a in range(0, len(SYMS), 80):
        ch = [s + ".NS" for s in SYMS[a:a + 80]]
        for tr in range(3):
            try:
                d = yf.download(ch, period=period, interval=interval, progress=False, group_by="column", auto_adjust=False, threads=True)
                break
            except Exception as e:  # noqa: BLE001
                print("retry", e, flush=True); time.sleep(20)
        for t in ch:
            try:
                x = d[["Open", "High", "Low", "Close"]].xs(t, axis=1, level=1).dropna()
            except Exception:  # noqa: BLE001
                continue
            if len(x) > 50:
                s = t[:-3]; O[s], H[s], L[s], C[s] = x.Open, x.High, x.Low, x.Close
        time.sleep(2)
    df = lambda z: pd.DataFrame(z).sort_index()  # noqa: E731
    return df(O), df(H), df(L), df(C)


def run(O, H, L, C, first_end, exit_at, label):
    """first_end: time the 'first period' ends (the bar whose close we enter at); exit_at: time of the bar whose close is the exit"""
    days = sorted({t.date() for t in C.index})
    tt = C.index.time
    rows = []
    prev_close = None
    for d in days:
        idx = C.index[[t.date() == d for t in C.index]]
        if prev_close is None or len(idx) < 3:
            prev_close = C.loc[idx].iloc[-1] if len(idx) else prev_close; continue
        f = [t for t in idx if t.time() < first_end]
        later = [t for t in idx if first_end <= t.time() < exit_at]
        xb = [t for t in idx if t.time() < exit_at]
        if not f or not later:
            prev_close = C.loc[idx].iloc[-1]; continue
        c1 = C.loc[f[-1]]; h1 = H.loc[f].max(); l1 = L.loc[f].min()
        r1 = c1 / prev_close - 1
        rows.append(dict(day=d, r1=r1, c1=c1, h1=h1, l1=l1, later=later))
        prev_close = C.loc[idx].iloc[-1]
    print("R|", label, "days", len(rows), flush=True)
    return rows


def trade(row, sym, side, O, H, L, C):
    e = row["c1"].get(sym); s = (row["l1"] if side > 0 else row["h1"]).get(sym)
    if not (np.isfinite(e) and np.isfinite(s)):
        return None
    risk = (e - s) / e * side
    if risk < 0.002:            # stop closer than 0.2%: skip (no room)
        return None
    px = None
    for t in row["later"]:
        o, h, lo = O.at[t, sym], H.at[t, sym], L.at[t, sym]
        if not np.isfinite(lo):
            continue
        if side > 0 and lo <= s:
            px = min(s, o) if np.isfinite(o) else s; break
        if side < 0 and h >= s:
            px = max(s, o) if np.isfinite(o) else s; break
    if px is None:
        last = [t for t in row["later"] if np.isfinite(C.at[t, sym])]
        if not last:
            return None
        px = C.at[last[-1], sym]
    pnl = (px / e - 1) * side - COST
    return pnl / risk


def stats(name, daily):
    daily = pd.Series(daily, dtype=float).dropna()
    if not len(daily):
        print("R|", name, "n 0"); return
    cap = daily * 1.0                      # % of capital per day (1% risk x average R)
    eq = cap.cumsum(); dd = (eq - eq.cummax()).min()
    yrs = cap.groupby([pd.Timestamp(d).year for d in cap.index]).sum().round(1).to_dict()
    print(f"R| {name}: days {len(cap)}, avg R {daily.mean():+.3f}, win {np.mean(daily > 0) * 100:.0f}%, total {cap.sum():+.1f}% of capital, "
          f"max drawdown {dd:.1f}%, by year {yrs}", flush=True)


def test(rows, O, H, L, C, tag):
    res = {}
    rng = np.random.default_rng(7)
    for K in (1, 2, 3):
        for thr in (0.0, 0.005):
            for mode in ("mixed", "buy only", "sell only", "mixed + Nifty agrees"):
                daily = {}
                for row in rows:
                    sc = {}
                    for ind, ss in IND.items():
                        v = row["r1"].reindex(ss).dropna()
                        if len(v) >= 3:
                            sc[ind] = (v.mean(), (v > 0).mean())
                    if len(sc) < 2 * K + 2:
                        continue
                    mkt = row["r1"].dropna().mean()
                    order = sorted(sc, key=lambda k: sc[k][0])
                    buys = [k for k in order[::-1][:K] if sc[k][0] > thr]
                    sells = [k for k in order[:K] if sc[k][0] < -thr]
                    if mode == "buy only":
                        sells = []
                    if mode == "sell only":
                        buys = []
                    if mode == "mixed + Nifty agrees":
                        buys = buys if mkt > 0 else []; sells = sells if mkt < 0 else []
                    Rs = [trade(row, s, 1, O, H, L, C) for k in buys for s in IND[k]] + [trade(row, s, -1, O, H, L, C) for k in sells for s in IND[k]]
                    Rs = [x for x in Rs if x is not None]
                    if Rs:
                        daily[row["day"]] = float(np.mean(Rs))
                res[(K, thr, mode)] = daily
                stats(f"{tag} top/bottom {K}, move > {thr * 100:.1f}%, {mode}", daily)
    # baselines: every liquid stock bought at the same time with the same stop; and random industries
    daily_all, daily_rand = {}, {}
    for row in rows:
        Rs = [trade(row, s, 1, O, H, L, C) for s in SYMS if s in C.columns]
        Rs = [x for x in Rs if x is not None]
        if Rs:
            daily_all[row["day"]] = float(np.mean(Rs))
        ks = list(IND); rng.shuffle(ks)
        Rs = [trade(row, s, 1, O, H, L, C) for s in IND[ks[0]] + IND[ks[1]]] + [trade(row, s, -1, O, H, L, C) for s in IND[ks[2]] + IND[ks[3]]]
        Rs = [x for x in Rs if x is not None]
        if Rs:
            daily_rand[row["day"]] = float(np.mean(Rs))
    stats(f"{tag} BASELINE buy every liquid stock", daily_all)
    stats(f"{tag} BASELINE random 2 industries buy + 2 sell", daily_rand)
    return res


O, H, L, C = dl("1h", "730d")
print("R| hourly", C.shape, C.index[0], C.index[-1], flush=True)
import datetime as dt  # noqa: E402
rows = run(O, H, L, C, dt.time(10, 15), dt.time(15, 15), "hourly")
res = test(rows, O, H, L, C, "1h 10:15 entry")
O5, H5, L5, C5 = dl("5m", "60d")
print("R| 5-minute", C5.shape, C5.index[0], C5.index[-1], flush=True)
rows5 = run(O5, H5, L5, C5, dt.time(9, 45), dt.time(15, 15), "5m")
test(rows5, O5, H5, L5, C5, "5m 09:45 entry")
# same 60 days on hourly for a like-for-like comparison
last60 = {r["day"] for r in rows5}
for k in ((2, 0.0, "mixed"), (2, 0.005, "mixed"), (2, 0.0, "mixed + Nifty agrees")):
    stats(f"1h 10:15 entry, SAME 60 days, top/bottom {k[0]}, move > {k[1] * 100:.1f}%, {k[2]}", {d: v for d, v in res[k].items() if d in last60})
