"""Month-close ATH 'Investment' system on ETFs and indices: skip new buys on a RED traffic-light day? (21 Nov 2026, Amritpal: "Yes"
after ATH stock breakouts adopted the RED skip).

System (as the app's Invest -> Month close, IHF type): a completed month CLOSES above the highest earlier monthly close (all-time) after a
base of >= 12 months since that high, and the last completed week is above a rising 30-week SMA -> buy at the next session's open;
exit when a weekly close is below the 30-week SMA -> next open. Book: 10 positions, 10% each, market costs (cost + slippage).
Universe per market: the app's ETF list (data/scan/funds.json, kind 'etf', leveraged / inverse names dropped), plus for India the NSE
sector / broad indices (data/scan/index_ohlcv.csv.gz) as a separate run (indices are not directly tradeable - a guide to index ETFs).
Traffic light per market exactly as tools/research/red_light.py: RED = 10-session 9/21 breadth negative (that market's stocks,
tools/trend_bt_global.load) AND the benchmark's last weekly close below its 30-week SMA.
Variants: no filter | skip entries on RED | wait for the first non-RED day (within 20 sessions) then buy next open.
Reporting newest first, bull / bear (benchmark vs its 200-day), ex-Covid. PILOT env = India ETFs + indices only.
Output data/research/etf_red_skip.json"""
import json
import os
import re
import sys
import time

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trend_bt_global import load  # noqa: E402
from global_universe import MARKETS  # noqa: E402
from signal_breadth import breadth  # noqa: E402
from holy_grail import portfolio, report  # noqa: E402

PILOT = bool(os.environ.get("PILOT"))
BENCH = {"NSE": "^NSEI", "US": "^GSPC", "ASX": "^AXJO", "UK": "^FTSE"}
FMK = {"NSE": "IN", "US": "US", "ASX": "AU", "UK": "UK"}
LEV = re.compile(r"ultra|short|bear|inverse|2x|3x|-1x|leverag|daily|vix|volatil", re.I)


def light(mk):
    d, _ = load(mk)
    B = breadth(d)
    b = yf.download(BENCH[mk], start="2015-01-01", auto_adjust=True, progress=False)["Close"].squeeze().dropna()
    b.index = pd.to_datetime(b.index).tz_localize(None)
    w = b.groupby(pd.Grouper(freq="W-FRI")).last().dropna(); below = (w < w.rolling(30).mean())
    idx_bad = below.reindex(B.index, method="ffill").shift(1).fillna(False).astype(bool)
    br_bad = B.W1.fillna(False).astype(bool)
    L = pd.Series(np.where(br_bad & idx_bad, "RED", np.where(br_bad | idx_bad, "AMBER", "GREEN")), index=B.index)
    return L[L.index >= "2016-06-01"], b


def ohlc(tickers):
    out = {}
    for a in range(0, len(tickers), 80):
        ch = tickers[a:a + 80]
        for k in range(3):
            try:
                d = yf.download(ch, period="max", interval="1d", progress=False, group_by="column", auto_adjust=True, threads=True); break
            except Exception as e:  # noqa: BLE001
                print("retry", e, flush=True); time.sleep(20); d = None
        if d is None or d.empty:
            continue
        for t in ch:
            try:
                x = pd.DataFrame({c: (d[c][t] if isinstance(d.columns, pd.MultiIndex) else d[c]) for c in ("Open", "Close")}).dropna()
            except Exception:  # noqa: BLE001
                continue
            if len(x) > 400:
                x.index = pd.to_datetime(x.index).tz_localize(None); out[t] = x
        time.sleep(2)
    return out


def signals(sym, x, cost):
    c, o = x.Close, x.Open
    m = c.groupby(x.index.to_period("M")).last()
    w = c.groupby(x.index.to_period("W-FRI")).last(); sma = w.rolling(30).mean()
    up = ((w > sma) & (sma > sma.shift(4)))
    rows = []
    prev_best = m.cummax().shift(1)
    best_month = pd.Series(np.arange(len(m)), index=m.index).where(m >= m.cummax()).ffill().shift(1)
    busy = None
    for k in range(13, len(m) - 1):
        mm = m.index[k]
        if not (m.iloc[k] > prev_best.iloc[k] and k - best_month.iloc[k] >= 12):
            continue
        sig_day = x.index[x.index.to_period("M") == mm][-1]
        wk = sig_day.to_period("W-FRI")
        last_w = wk if sig_day.weekday() == 4 else wk - 1
        if last_w not in up.index or not bool(up.loc[last_w]):
            continue
        rest = x.index[x.index > sig_day]
        if not len(rest) or (busy is not None and rest[0] <= busy):
            continue
        rows.append(dict(sym=sym, sig=sig_day))
    return rows


def exit_for(x, entry_day):
    c = x.Close; w = c.groupby(x.index.to_period("W-FRI")).last(); sma = w.rolling(30).mean()
    after = w[(w.index >= entry_day.to_period("W-FRI")) & (w < sma)]
    if not len(after):
        return x.index[-1], float(c.iloc[-1]), True
    nxt = x.index[x.index.to_period("W-FRI") > after.index[0]]
    return (nxt[0], float(x.Open.loc[nxt[0]]), False) if len(nxt) else (x.index[-1], float(c.iloc[-1]), True)


def run(name, D, L, bench, mk, res):
    cost = MARKETS[mk]["cost"] + MARKETS[mk]["slip"]
    sig = [s for t, x in D.items() for s in signals(t, x, cost)]
    S = pd.DataFrame(sig)
    if not len(S):
        print(f"R| {name}: no signals", flush=True); return
    S = S[S.sig >= "2016-06-01"]
    S["light"] = [L.iloc[max(0, L.index.searchsorted(t, side="right") - 1)] if len(L) else None for t in S.sig]
    bull = bench > bench.rolling(200).mean()
    out = {"signals": len(S), "by light": S.light.value_counts().to_dict()}
    for var in ("no filter", "skip RED", "wait for non-RED"):
        T = []; last_exit = {}
        for r in S.sort_values("sig").itertuples():
            x = D[r.sym]; d0 = r.sig
            if var != "no filter" and r.light == "RED":
                if var == "skip RED":
                    continue
                nxt = L[(L.index > d0) & (L != "RED")].index[:1]
                if not len(nxt) or (nxt[0] - d0).days > 30:
                    continue
                d0 = nxt[0]
            rest = x.index[x.index > d0]
            if not len(rest) or (r.sym in last_exit and rest[0] <= last_exit[r.sym]):
                continue
            e_day = rest[0]; e = float(x.Open.loc[e_day])
            xd, xp, op = exit_for(x, e_day)
            last_exit[r.sym] = xd
            T.append(dict(sym=r.sym, side=1, entry=e_day, exit=xd, e=e, risk=0.1, ret=xp / e - 1 - cost, r_mult=0, half=False, days=(xd - e_day).days,
                          adx=0.0, open=op, light=r.light))
        T = pd.DataFrame(T)
        C = {s: D[s].Close.to_dict() for s in T.sym.unique()}
        days = sorted(set().union(*[set(D[s].index[D[s].index >= "2016-06-01"]) for s in T.sym.unique()]))
        eq = portfolio(T, C, days, maxpos=10, risk=0.01); rp = report(eq, bull)
        st = dict(trades=len(T), avg=round(T.ret.mean() * 100, 2), win=round((T.ret > 0).mean() * 100), hold_days=float(T.days.median()))
        if var == "no filter":
            st["avg by light"] = {k: (int((T.light == k).sum()), round(float(T.ret[T.light == k].mean() * 100), 2) if (T.light == k).any() else None) for k in ("GREEN", "AMBER", "RED")}
        out[var] = dict(trades=st, port=rp)
        print(f"R| {name} | {var}: {st} | CAGR {rp['CAGR']} DD {rp['max DD']} 1y {rp['1y']} 2y {rp['2y']} 3y {rp['3y']} 5y {rp['5y']} bull/bear {rp['bull/bear a year']} ex-Covid {rp['ex-Covid']}", flush=True)
    res[name] = out


def main():
    F = json.load(open("data/scan/funds.json"))["rows"]
    res = dict(method=__doc__)
    for mk in (["NSE"] if PILOT else ["NSE", "US", "ASX", "UK"]):
        try:
            L, bench = light(mk)
        except Exception as e:  # noqa: BLE001
            print("R|", mk, "light failed", e, flush=True); continue
        print(f"R| {mk} light days {len(L)}: {L.value_counts(normalize=True).round(3).to_dict()}", flush=True)
        keys = [r for r in F if r.get("market") == FMK[mk] and r.get("kind") == "etf" and not LEV.search(r.get("name", ""))]
        tick = []
        for r in keys:
            k = r["key"].split(":", 1)[-1]
            tick.append(k + ".NS" if mk == "NSE" else k + ".AX" if mk == "ASX" else k)
        D = ohlc(sorted(set(tick)))
        run(f"{mk} ETFs ({len(D)})", D, L, bench, mk, res)
        if mk == "NSE":
            ix = pd.read_csv("data/scan/index_ohlcv.csv.gz", parse_dates=["Date"])
            DI = {k: g.set_index("Date").sort_index()[["Close"]].assign(Open=lambda z: z.Close.shift(1).fillna(z.Close)) for k, g in ix.groupby("INDEX")}
            run(f"NSE indices ({len(DI)})", DI, L, bench, mk, res)
    if not PILOT:
        os.makedirs("data/research", exist_ok=True)
        json.dump(res, open("data/research/etf_red_skip.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
