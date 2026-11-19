"""Morning check before a 9/21 entry (19 Nov 2026, Amritpal: "check on the day if market, sector, industry and theme are up,
then only take the position").

Only daily closes exist for the sector / theme indices (NSE archive from Nov 2015), so "up that day" is tested two ways:
  P  on the SIGNAL day all of them closed up (known the next morning) -> buy at the next open
  D  on the ENTRY day all of them are up -> buy near that day's close instead of the open (what an intraday check
     during the day amounts to, bought late in the session); otherwise skip.  D0 = buy at the entry-day close with no check,
     to separate the effect of the later fill from the check itself.
"Up" = day change > 0. Market = Nifty 50; sector = the stock's sector index (sector_state.INDUSTRY_INDEX); industry = average
day change of the liquid stocks in the same NSE industry; theme = every thematic index the stock belongs to (missing -> ignored).
Mapping uses today's lists (sectors.json). NSE stocks from Yahoo 2016 -> today, survivors; 9/21 engine (5-day-low stop,
Supertrend exit, 1% risk, costs). Output: data/research/morning_check.json"""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from global_universe import MARKETS  # noqa: E402
from trend_bt_global import load, stats  # noqa: E402
from sector_state import INDUSTRY_INDEX  # noqa: E402

CFG = MARKETS["NSE"]


def run(d, maxpos, risk, rank, gate=None, at_close=False, skip=0.12, liq=0.05, start="2016-06-01", cap0=2_000_000):
    """concentrated_921.run with (a) an optional entry-day gate column and (b) an optional fill at the entry day's close."""
    cost, slip = CFG["cost"], CFG["slip"]; maxw = 1.0 / maxpos
    days = sorted(d.Date.unique()); by = {dt: x.set_index("SYMBOL") for dt, x in d.groupby("Date")}
    cash, pos, eq, trades, pending = cap0, {}, {}, [], []

    def sell(sym, px, dt):
        nonlocal cash
        p = pos.pop(sym); f = px * (1 - slip) * (1 - cost / 2); cash += p["q"] * f
        trades.append(dict(sym=sym, entry=p["dt"], exit=dt, ret=f / p["cin"] - 1, pnl=p["q"] * (f - p["cin"])))

    for k, dt in enumerate(days):
        if dt < pd.Timestamp(start):
            continue
        x = by[dt]; fresh = set()
        for sym, stop, v in pending:
            if sym not in x.index or sym in pos or len(pos) >= maxpos:
                continue
            if gate and not bool(x.at[sym, gate]):
                continue
            px = float(x.at[sym, "CLOSE"] if at_close else x.at[sym, "OPEN"])
            if at_close and float(x.at[sym, "LOW"]) <= stop:      # the stop traded before the late buy: skip
                continue
            if px <= stop or (px - stop) / px > skip:
                continue
            e = cash + sum(p["q"] * p["last"] for p in pos.values()); fill = px * (1 + slip) * (1 + cost / 2)
            q = min(risk * e / (px - stop), maxw * e / px, liq * v / px, cash / fill)
            if q * px < 0.005 * cap0:
                continue
            cash -= q * fill; pos[sym] = dict(q=q, cin=fill, stop=stop, dt=dt, last=px)
            if at_close:
                fresh.add(sym)
        pending = []
        for sym in list(pos):
            p = pos[sym]
            if sym not in x.index:
                p["gone"] = p.get("gone", 0) + 1
                if p["gone"] >= 20:
                    sell(sym, p["last"], dt)
                continue
            p["gone"] = 0; r = x.loc[sym]
            if sym not in fresh and r.LOW <= p["stop"]:
                sell(sym, min(float(r.OPEN), p["stop"]), dt); continue
            p["last"] = float(r.CLOSE)
            if r.st == -1:
                p["sell_next"] = True
        if len(pos) < maxpos:
            t = x[x.sig & ~x.index.isin(list(pos))]
            if len(t):
                t = t.sort_values(rank, ascending=False) if rank != "random" else t.iloc[np.random.default_rng(k).permutation(len(t))]
                pending = [(s, float(r.low5), float(r.val)) for s, r in t.head(maxpos - len(pos)).iterrows()]
        eq[dt] = cash + sum(p["q"] * p["last"] for p in pos.values())
        nxt = days[k + 1] if k + 1 < len(days) else None
        if nxt is not None:
            xn = by[nxt]
            for sym in [s for s, p in pos.items() if p.get("sell_next")]:
                if sym in xn.index:
                    sell(sym, float(xn.at[sym, "OPEN"]), nxt)
    return pd.Series(eq), pd.DataFrame(trades)


def main():
    d, _ = load("NSE")
    d = d.sort_values(["SYMBOL", "Date"]).reset_index(drop=True)
    g = d.groupby("SYMBOL").CLOSE
    d["r63"] = g.transform(lambda s: s / s.shift(63) - 1)
    d["near_high"] = d.CLOSE / g.transform(lambda s: s.rolling(250, min_periods=60).max())
    d["chg"] = g.pct_change()
    sec = json.load(open("data/scan/sectors.json"))
    base = d.SYMBOL.str.replace(".NS", "", regex=False)
    ind = base.map(sec["symbols"]); d["sector_ix"] = ind.map(lambda i: INDUSTRY_INDEX.get(i) if isinstance(i, str) else None)
    th = sec.get("themes", {})
    H = pd.read_csv("data/scan/sector_hist.csv.gz"); H["Date"] = pd.to_datetime(H.Date)
    P = H.pivot_table(index="Date", columns="INDEX", values="CLOSE").sort_index(); U = P.pct_change() > 0
    U = U.where(P.pct_change().notna())                      # NaN where the index had no change that day
    def up(ixname, dates):
        if ixname not in U:
            return pd.Series(np.nan, index=dates.index)
        return dates.map(U[ixname])
    d["mkt_up"] = up("NIFTY 50", d.Date)
    su = pd.Series(np.nan, index=d.index)
    for ix, idx in d.groupby("sector_ix").groups.items():
        su.loc[idx] = up(ix, d.Date.loc[idx]).values
    d["sec_up"] = su
    # industry = mean day change of the panel's stocks in the same industry (excluding none)
    d["industry"] = ind
    im = d.dropna(subset=["industry"]).groupby(["industry", "Date"]).chg.mean()
    d["ind_up"] = [np.nan if not isinstance(i, str) else (im.get((i, dt), np.nan) > 0 if np.isfinite(im.get((i, dt), np.nan)) else np.nan)
                   for i, dt in zip(d.industry, d.Date)]
    # theme: all of the stock's themes up (ignore themes without data that day)
    tu = []
    for s, dt in zip(base, d.Date):
        L = [U.at[dt, t] for t in th.get(s, []) if t in U.columns and dt in U.index and pd.notna(U.at[dt, t])]
        tu.append(np.nan if not L else bool(all(L)))
    d["thm_up"] = tu
    ok = lambda c: d[c].isna() | (d[c] == True)                # noqa: E712,E731  missing data = no veto
    d["g_mkt"] = ok("mkt_up")
    d["g_ms"] = ok("mkt_up") & ok("sec_up")
    d["g_all"] = ok("mkt_up") & ok("sec_up") & ok("ind_up") & ok("thm_up")
    cov = {c: round(float(d[c].notna().mean() * 100), 1) for c in ("mkt_up", "sec_up", "ind_up", "thm_up")}
    res = dict(method=__doc__, coverage_pct=cov)
    print("coverage", cov, flush=True)
    sig0 = d.sig.copy()
    # P: signal-day gate (shift the gate to the signal day = same row)
    V = {"baseline: buy next open": dict(), "P all four up on the signal day -> next open": dict(sig=sig0 & d.g_all),
         "P market + sector up on the signal day -> next open": dict(sig=sig0 & d.g_ms),
         "D0 buy at the entry-day close, no check": dict(at_close=True),
         "D market up on the entry day -> buy at its close": dict(at_close=True, gate="g_mkt"),
         "D market + sector up on the entry day -> buy at its close": dict(at_close=True, gate="g_ms"),
         "D all four up on the entry day -> buy at its close": dict(at_close=True, gate="g_all")}
    for bk, (mp, rank) in (("10 positions, 3-month strength", (10, "r63")), ("5 positions, 3-month strength", (5, "r63")), ("10 positions, random", (10, "random"))):
        for name, kw in V.items():
            z = d.copy()
            if "sig" in kw:
                z["sig"] = kw["sig"].values
            eq, T = run(z, mp, 0.01, rank, gate=kw.get("gate"), at_close=kw.get("at_close", False))
            a, c = stats(eq, "2017-01-01", "2030-01-01"), stats(eq, "2022-01-01", "2030-01-01")
            k = f"{bk} | {name}"
            res[k] = dict(cagr=a["cagr"], maxdd=a["maxdd"], cagr_22_26=c["cagr"], dd_22_26=c["maxdd"], trades=len(T),
                          win=round(float((T.ret > 0).mean() * 100)) if len(T) else None, avg=round(float(T.ret.mean() * 100), 2) if len(T) else None)
            print("R|", k, res[k], flush=True)
    os.makedirs("data/research", exist_ok=True)
    json.dump(res, open("data/research/morning_check.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
