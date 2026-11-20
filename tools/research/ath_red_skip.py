"""ATH monthly system: skip new entries on RED traffic-light days? (21 Nov 2026, Amritpal: "Yes do it" after the light-distribution
test showed ATH entries on RED averaged +2.9% vs +21-28% on GREEN / AMBER).

Signals and exits exactly as the live scanner (tools/ath_scan.analyse on full Yahoo history): base >= 24 months, above a rising
30-week SMA, Rs 2 cr/day, buy at the trigger (or the open on a gap); month-close breakouts buy the next month's first open; exit
next open after a weekly close below the 30-week SMA. Light as tools/research/red_light.py (known at the previous close).
Portfolio from 2016-06, Rs 20 L, 0.2% cost a round trip, positions marked at the daily close:
  live sizing : risk 2% of equity to the 30-week SMA, max 20% of equity per stock, cash-limited (as ath_scan's notes)
  equal 10    : 10% of equity each, max 10 positions
Same-day signals in random order (3 seeds). Gates: no filter | skip RED | skip RED or AMBER (control).
Reporting newest first (last 1/2/3/5 years, each year), bull vs bear (Nifty vs its 200-day), ex-Covid.
PILOT env = 150 stocks, 1 seed. Output data/research/ath_red_skip.json"""
import json
import os
import sys
import time
from datetime import date

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trend_bt_global import load  # noqa: E402
import light_distribution as LD  # noqa: E402

PILOT = bool(os.environ.get("PILOT"))
COST = 0.002
CAP0 = 2_000_000


def report(eq, bull):
    eq = eq.sort_index(); end = eq.index[-1]; out = {}
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    out["CAGR"] = round(float(eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) * 100 - 100, 1)
    out["max drawdown"] = round(float((eq / eq.cummax() - 1).min()) * 100, 1)
    for y in (1, 2, 3, 5):
        e = eq[eq.index >= end - pd.DateOffset(years=y)]
        out[f"last {y}y"] = round(float((e.iloc[-1] / e.iloc[0]) ** (1 / y) - 1) * 100, 1) if len(e) > 50 else None
        out[f"last {y}y dd"] = round(float((e / e.cummax() - 1).min()) * 100, 1) if len(e) > 50 else None
    yr = eq.resample("YE").last(); yr = pd.concat([eq.iloc[:1], yr]).pct_change().dropna()
    out["years"] = {str(k.year): round(v * 100, 1) for k, v in sorted(yr.items(), reverse=True)}
    r = eq.pct_change().dropna(); b = bull.reindex(r.index).fillna(False).astype(bool).values
    ann = lambda x: round(float((1 + x).prod() ** (252 / max(1, len(x))) - 1) * 100, 1)  # noqa: E731
    out["bull a year"] = ann(r[b]); out["bear a year"] = ann(r[~b])
    cov = np.asarray((r.index >= "2020-02-15") & (r.index <= "2020-12-31")); rx = r[~cov]; ex = (1 + rx).cumprod()
    out["ex-Covid a year"] = ann(rx); out["ex-Covid dd"] = round(float((ex / ex.cummax() - 1).min()) * 100, 1)
    return out


def sim(E, C, days, sizing, block, seed):
    rng = np.random.default_rng(seed)
    E = E[~E.d.isin(block)] if block is not None else E
    ent = {d: g.iloc[rng.permutation(len(g))] for d, g in E.groupby("d")}
    exits = {}
    cash, pos, eq, trades = CAP0, {}, {}, []
    for dt in days:
        for k in list(pos):                                        # exits at the next open after the weekly close
            p = pos[k]
            if p["xd"] is not None and dt >= p["xd"]:
                f = p["xp"] * (1 - COST / 2); cash += p["q"] * f; trades.append(f / p["cin"] - 1); pos.pop(k)
        for k, p in pos.items():
            px = C[p["sym"]].get(dt)
            if px is not None and np.isfinite(px):
                p["last"] = px
        if dt in ent:
            for _, r in ent[dt].iterrows():
                if r.sym in [p["sym"] for p in pos.values()]:
                    continue
                e = cash + sum(p["q"] * p["last"] for p in pos.values()); fill = r.entry * (1 + COST / 2)
                if sizing == "live":
                    gap = r.entry - r.sma if (r.sma is not None and np.isfinite(r.sma) and r.sma < r.entry) else r.entry * 0.1
                    q = min(0.02 * e / gap, 0.20 * e / r.entry, cash / fill)
                else:
                    if len(pos) >= 10:
                        continue
                    q = min(0.10 * e / r.entry, cash / fill)
                if q * r.entry < 0.01 * e:
                    continue
                cash -= q * fill
                pos[f"{r.sym}|{dt}"] = dict(sym=r.sym, q=q, cin=fill, last=r.entry, xd=r.xd, xp=r.xp if np.isfinite(r.xp) else r.entry)
        eq[dt] = cash + sum(p["q"] * p["last"] for p in pos.values())
    return pd.Series(eq), trades, exits


def main():
    d, u = load("NSE")
    if PILOT:
        keep = sorted(d.SYMBOL.unique())[:150]; d = d[d.SYMBOL.isin(keep)]
    L = LD.light_series(d)
    days = list(L.index)
    nif = yf.download("^NSEI", start="2015-01-01", auto_adjust=True, progress=False)["Close"].squeeze().dropna()
    nif.index = pd.to_datetime(nif.index).tz_localize(None); bull = nif > nif.rolling(200).mean()
    import ath_scan as A
    tick = list(u.ticker)[:150] if PILOT else list(u.ticker)
    today = date.today(); evs = []; C = {}
    for a in range(0, len(tick), 80):
        chunk = tick[a:a + 80]; dd = None
        for _ in range(3):
            try:
                dd = yf.download(chunk, period="max", interval="1d", auto_adjust=False, progress=False, group_by="column", threads=True); break
            except Exception as e:  # noqa: BLE001
                print("retry", a, e, flush=True); time.sleep(20)
        if dd is None or dd.empty:
            continue
        for t in chunk:
            try:
                x = pd.DataFrame({k: dd[k][t] for k in ("Open", "High", "Low", "Close", "Volume")}).dropna(subset=["Close"])
                x.index = pd.to_datetime(x.index).tz_localize(None)
                if len(x) < 300 or float(x.Close.iloc[-1]) < A.MIN_CLOSE:
                    continue
                e_, _, _ = A.analyse(t, x, today, lookback_days=0)
                got = False
                for r in e_:
                    if r["main"] and pd.Timestamp(r["date"]) >= pd.Timestamp("2016-06-01"):
                        evs.append(dict(sym=t, d=pd.Timestamp(r["date"]).normalize(), entry=float(r["entry"]), sma=r.get("sma_entry"),
                                        xd=pd.Timestamp(r["exit_date"]).normalize() if r["exit_date"] is not None else None,
                                        xp=float(r["exit_price"]) if r["exit_price"] is not None else np.nan)); got = True
                if got:
                    C[t] = x.Close.loc["2016-01-01":].to_dict()
            except Exception as ex:  # noqa: BLE001
                print("ath skip", t, str(ex)[:80], flush=True)
        print("ath", a + len(chunk), "events", len(evs), flush=True)
        time.sleep(2)
    E = pd.DataFrame(evs)
    E["sma"] = pd.to_numeric(E.sma, errors="coerce")
    E["light"] = [LD.before(L, x) for x in E.d]
    # entries on non-trading days of the light series -> next light day
    E["d"] = [days[min(len(days) - 1, L.index.searchsorted(x))] for x in E.d]
    print("R| ATH events", len(E), "by light", E.light.value_counts().to_dict(), flush=True)
    gates = {"no filter": None, "skip RED": set(E.index[E.light == "RED"]), "skip RED or AMBER": set(E.index[E.light.isin(["RED", "AMBER"])])}
    res = dict(method=__doc__, events=len(E), by_light=E.light.value_counts().to_dict(), runs={})
    seeds = (0,) if PILOT else (0, 1, 2)
    for sizing in ("live", "equal 10"):
        for gname, gidx in gates.items():
            reps = []
            for sd in seeds:
                EE = E.drop(index=list(gidx)) if gidx else E
                eq, T, _ = sim(EE, C, days, "live" if sizing == "live" else "eq", None, sd)
                rp = report(eq, bull); rp["trades"] = len(T); rp["avg trade"] = round(float(np.mean(T)) * 100, 2) if T else None
                reps.append(rp)
            k = f"{sizing} | {gname}"
            m = {kk: round(float(np.mean([r_[kk] for r_ in reps if r_.get(kk) is not None])), 1) for kk in reps[0] if not isinstance(reps[0][kk], dict) and reps[0][kk] is not None}
            m["years"] = reps[0]["years"]; m["seeds CAGR"] = [r_["CAGR"] for r_ in reps]
            res["runs"][k] = m
            print(f"R| {k}: {m}", flush=True)
    if not PILOT:
        os.makedirs("data/research", exist_ok=True)
        json.dump(res, open("data/research/ath_red_skip.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
