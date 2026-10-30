"""Monthly ATH system on mutual funds (AMFI NAVs, direct growth, equity + index funds), 2016 -> today.
Same rules as the stock system, adapted to NAV-only data and fund execution:
  trigger : highest NAV of the all-time-high CLOSING month (completed months); base = months since that month
  signal  : daily NAV closes above the trigger (first time this month), base >= BASE months, fund >= 36 months old,
            last completed week's NAV above its 30-week SMA and the SMA rising (vs 4 weeks earlier)
  entry   : next business day's NAV (NAV is only known in the evening)
  exit    : weekly (Friday) NAV below the 30-week SMA -> redeem at the next business day's NAV
  costs   : stamp duty 0.005% on purchase; exit load 1% if redeemed within 365 days (typical equity fund); no tax
  book    : 10 funds; equal weight (10%) or 1% risk to the 30-week SMA (cap 20%); optional max 2 per category
Benchmarks: a Nifty 50 index fund (direct, growth) and the median buy-and-hold of all funds alive in Jan 2016.
Caveat: AMFI lists only schemes alive today (merged/closed schemes are missing) -> results are flattered somewhat."""
import json
import os
import sys

import numpy as np
import pandas as pd

D = "data/mf"
START = "2016-01-01"


def build():
    nav = pd.read_parquet(f"{D}/nav.parquet")
    meta = pd.read_csv(f"{D}/meta.csv").set_index("code")
    P = nav.pivot_table(index="Date", columns="code", values="nav").sort_index()
    P = P[P.index >= "2012-12-01"]
    bd = pd.bdate_range(P.index.min(), P.index.max())
    P = P.reindex(bd).ffill(limit=5)              # holidays: carry NAV a few days
    first = nav.groupby("code").Date.min()
    return P, meta, first


def signals(P, first, base_min):
    dates = P.index
    mon = dates.to_period("M")
    mC = P.groupby(mon).last(); mH = P.groupby(mon).max()
    best = mC.cummax(); isb = (mC >= best) & mC.notna()
    k = pd.DataFrame(np.arange(len(mC))[:, None].repeat(mC.shape[1], 1), index=mC.index, columns=mC.columns)
    trig_m = mH.where(isb).ffill().shift(1)
    age_m = k - k.where(isb).ffill().shift(1)
    trig = trig_m.reindex(mon).set_axis(dates); age = age_m.reindex(mon).set_axis(dates)
    wk = dates.to_period("W-FRI")
    wC = P.groupby(wk).last(); sma = wC.rolling(30, min_periods=30).mean()
    ok_w = ((wC > sma) & (sma > sma.shift(4))).shift(1)                 # last COMPLETED week
    ok = ok_w.reindex(wk).set_axis(dates).fillna(False).astype(bool)
    sma_prev = sma.shift(1).reindex(wk).set_axis(dates)                  # SMA of last completed week (stop ref)
    exit_w = (wC < sma)                                                  # week closes below SMA -> exit after that Friday
    exit_d = pd.DataFrame(False, index=dates, columns=P.columns)
    last_day = pd.Series(dates, index=dates).groupby(wk).transform("max")
    is_last = (pd.Series(dates, index=dates) == last_day).values
    ew = exit_w.reindex(wk).set_axis(dates)
    exit_d[:] = (ew.values.astype(bool) & is_last[:, None])
    above = P > trig
    crossed_before = above.groupby(mon).cumsum().shift(1).fillna(0) > 0
    crossed_before = crossed_before & (pd.Series(mon, index=dates) == pd.Series(mon, index=dates).shift(1)).values[:, None]
    agefund = pd.DataFrame((dates.values[:, None] - first.reindex(P.columns).values[None, :]) / np.timedelta64(1, "D"), index=dates, columns=P.columns)
    sig = above & ~crossed_before & (age >= base_min) & ok & (agefund >= 3 * 365)
    mom = P / P.shift(126) - 1
    return sig.fillna(False), exit_d, sma_prev, mom


def run(P, meta, sig, exit_d, sma_ref, mom, size="eq", N=10, risk=0.01, prio="random", seed=0, cat_cap=None, start=START):
    rng = np.random.default_rng(seed)
    dates = P.index; t0 = dates.searchsorted(pd.Timestamp(start))
    X = P.values; S_ = sig.values; E_ = exit_d.values; R_ = sma_ref.values; M_ = mom.values
    cats = meta.category.reindex(P.columns).fillna("?").values
    cash, pos, eq, trades, pend_buy, pend_sell = 1.0, {}, [], [], [], []
    for t in range(t0, len(dates)):
        x = X[t]
        # executions at today's NAV
        for j in pend_sell:
            if j in pos and np.isfinite(x[j]):
                p = pos.pop(j); held = (dates[t] - dates[p["t"]]).days
                load = 0.01 if held < 365 else 0.0
                cash += p["u"] * x[j] * (1 - load)
                trades.append(dict(code=int(P.columns[j]), entry=dates[p["t"]], exit=dates[t], ret=x[j] * (1 - load) / p["px"] - 1, days=held, load=load > 0))
        pend_sell = []
        equity = cash + sum(p["u"] * (X[t][j] if np.isfinite(X[t][j]) else p["px"]) for j, p in pos.items())
        for j in pend_buy:
            if j in pos or len(pos) >= N or not np.isfinite(x[j]):
                continue
            if cat_cap and sum(cats[k] == cats[j] for k in pos) >= cat_cap:
                continue
            if size == "eq":
                amt = equity / N
            else:
                ref = R_[t, j]
                dist = (x[j] - ref) / x[j] if np.isfinite(ref) and ref < x[j] else 0.05
                amt = min(risk * equity / max(dist, 0.01), 0.20 * equity)
            amt = min(amt, cash)
            if amt < equity * 0.01:
                continue
            cash -= amt; pos[j] = dict(u=amt * (1 - 0.00005) / x[j], px=x[j], t=t)
        pend_buy = []
        # signals at today's close -> act tomorrow
        for j in list(pos):
            if E_[t, j]:
                pend_sell.append(j)
        free = N - len(pos) + len(pend_sell)
        if free > 0:
            c = [j for j in np.where(S_[t])[0] if j not in pos]
            if c:
                if prio == "random":
                    rng.shuffle(c)
                else:
                    c = sorted(c, key=lambda j: -(M_[t, j] if np.isfinite(M_[t, j]) else -9))
                pend_buy = c[: free + 5]
        eq.append(cash + sum(p["u"] * (x[j] if np.isfinite(x[j]) else p["px"]) for j, p in pos.items()))
    return pd.Series(eq, index=dates[t0:]), pd.DataFrame(trades)


def stats(e, T=None):
    g = lambda s: ((s.iloc[-1] / s.iloc[0]) ** (365.25 / max((s.index[-1] - s.index[0]).days, 1)) - 1) * 100
    out = dict(cagr=round(g(e), 1), dd=round((e / e.cummax() - 1).min() * 100, 1),
               a=round(g(e[:"2020-12-31"]), 1), b=round(g(e["2021-01-01":]), 1))
    yr = e.resample("YE").last(); yr = pd.concat([pd.Series([e.iloc[0]], index=[e.index[0]]), yr]).pct_change().dropna() * 100
    out["years"] = " ".join(f"{v:+.0f}" for v in yr.values)
    if T is not None and len(T):
        out.update(trades=len(T), win=round((T.ret > 0).mean() * 100), avg=round(T.ret.mean() * 100, 1),
                   days=int(T.days.median()), loads=round(T.load.mean() * 100))
    return out


def main():
    os.makedirs("data/mfbt", exist_ok=True)
    P, meta, first = build()
    print("panel", P.shape, P.index.min().date(), P.index.max().date(), flush=True)
    # benchmarks
    nm = meta.name.str.lower()
    idx = meta[nm.str.contains("nifty 50 index") & ~nm.str.contains("next|equal|value|quality|momentum|alpha|low vol|smallcap|midcap|500")]
    rows = []
    for code in idx.index:
        if code in P and P[code][START:].notna().iloc[0]:
            s = P[code][START:].dropna(); rows.append(("Nifty 50 index fund: " + meta.name[code][:45], stats(s)))
            break
    alive = [c for c in P.columns if P[c][START:].notna().iloc[0] and meta.category.get(c, "") != "Index Funds"]
    bh = (P[alive][START:].ffill() / P[alive][START:].ffill().iloc[0]).median(axis=1)
    rows.append((f"Median equity fund, buy & hold ({len(alive)} funds alive in Jan 2016)", stats(bh)))
    for name, st in rows:
        print(f"{name:70s} {st}", flush=True)
    res = []
    for base in (24, 12, 0):
        sig, exit_d, sma_ref, mom = signals(P, first, base)
        nsig = int(sig[START:].values.sum())
        print(f"--- base >= {base} months: {nsig} signals", flush=True)
        for size in ("eq", "risk"):
            for prio in ("random", "momentum"):
                for cc in (None, 2):
                    seeds = range(5) if prio == "random" else [0]
                    sts = []
                    for sd in seeds:
                        e, T = run(P, meta, sig, exit_d, sma_ref, mom, size=size, prio=prio, seed=sd, cat_cap=cc)
                        sts.append(stats(e, T))
                    med = {k: (float(np.median([s[k] for s in sts])) if isinstance(sts[0][k], (int, float)) else sts[0][k]) for k in sts[0]}
                    label = f"base{base} {size} {prio} catcap={cc}"
                    med["cagr_range"] = f"{min(s['cagr'] for s in sts)}..{max(s['cagr'] for s in sts)}"
                    print(f"{label:40s} {med}", flush=True)
                    res.append(dict(label=label, **med))
        pd.DataFrame(res).to_csv("data/mfbt/results.csv", index=False)
    # current signals for the record
    sig, exit_d, sma_ref, mom = signals(P, first, 24)
    last = sig.index[-25:]
    recent = [(d.date(), int(c), meta.name.get(c, "")[:60]) for d in last for c in sig.columns[sig.loc[d].values]]
    print("recent signals (24m base):", recent[-30:])
    json.dump(dict(benchmarks=rows), open("data/mfbt/bench.json", "w"), default=str)


if __name__ == "__main__":
    main()
