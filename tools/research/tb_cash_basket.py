"""Top Bottom in SHARES / BeES instead of futures (26 Nov 2026, Amritpal: "can shares or bees replace top bottom futures with proper
risk management" -> "Yes").
Signals: the live engine (topbottom_backtest.run_live, buffer 0.05%) on the near-month futures from NSE bhavcopies (data/futures) -
the same levels the bots trade; the cash leg (BANKBEES / NIFTYBEES / the shares) moves with them. Index rules 1/2/2, stock rules 1.5/3/3.
Sleeves, BUY ONLY (cash can't be short overnight): Bank Nifty -> BANKBEES, Nifty -> NIFTYBEES, BEL, LT, TMPV, TCS -> the shares.
Costs per round trip: futures 0.05% (index) / 0.1% (stock); cash ETF 0.1%, delivery shares 0.25% (STT 0.1% a side + charges).
Books, Rs 20 L, no leverage (cash) unless said:
  A  Bank Nifty FUTURES both sides, 1 lot (~1x the account) - the live bot today
  B  BANKBEES buy only, the whole account on each trade
  C  6 cash sleeves, equal weight (1/6 each while in a trade, cash otherwise)
  D  6 cash sleeves, 1% risk per trade: weight = 1% / the engine's max stop (index 2%, stock 3%), capped at 20% a sleeve; if the open
     sleeves want more than 100%, all are scaled down (no borrowing)
  E  D + Bank Nifty's SHORT trades kept on 1 BN futures lot (cash for the longs, futures only for the shorts)
Daily marked to the close. Newest windows first; 2020 Covid year shown separately."""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import topbottom_backtest as tbb  # noqa: E402

IDX = dict(day_sl_pct=1.0, max_sl_pct=2.0, be_pct=2.0, gap_pct=1.0); STK = dict(day_sl_pct=1.5, max_sl_pct=3.0, be_pct=3.0, gap_pct=1.5)


def fut(sym):
    x = pd.read_csv(f"data/futures/{sym}.csv", parse_dates=["Date"]).set_index("Date")[["Open", "High", "Low", "Close"]].dropna()
    return x[(x.High >= x.Low) & (x.index >= "2010-01-01")]


def sleeve(x, p, cost, side=None):
    """daily return of one unit held per the engine's trades (side BUY / SELL / None = both), and an in-trade flag"""
    t = tbb.run_live(x, p); c = x.Close; r = pd.Series(0.0, index=x.index); on = pd.Series(False, index=x.index); n = 0
    for _, tr in t.iterrows():
        if side and tr.Side != side:
            continue
        e = pd.Timestamp(tr.EntryDate); xd = pd.Timestamp(tr.ExitDate) if pd.notna(tr.get("ExitDate")) else c.index[-1]
        sgn = 1 if tr.Side == "BUY" else -1; days = c.loc[e:xd].index
        if not len(days):
            continue
        n += 1; prev = tr.Entry; op = pd.isna(tr.get("ExitDate"))
        for d in days:
            px = tr.Exit if (d == xd and not op) else c.loc[d]
            r.loc[d] += sgn * (px / prev - 1); prev = px
        on.loc[days[:-1] if not op else days] = True
        if not op:
            r.loc[xd] -= cost
    return r, on, n


def stats(eq):
    eq = eq.dropna()
    if len(eq) < 30:
        return None
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25; cg = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1 if yrs > 0 else np.nan
    dd = (eq / eq.cummax() - 1).min(); m = eq.resample("ME").last().pct_change().dropna()
    return f"{cg * 100:+6.1f}%/yr  worst fall {dd * 100:6.1f}%  up months {(m > 0).mean() * 100:3.0f}%  worst month {m.min() * 100:+5.1f}%"


def main():
    S = {}
    S["BN"] = (fut("BANKNIFTY"), IDX, 0.001); S["NIFTY"] = (fut("NIFTY"), IDX, 0.001)
    for s in ("BEL", "LT", "TMPV", "TCS"):
        if os.path.exists(f"data/futures/{s}.csv"):
            S[s] = (fut(s), STK, 0.0025)
    R, ON = {}, {}
    for k, (x, rules, cost) in S.items():
        p = tbb.Params(buffer_pct=0.05, buffer_pts=0, event_exit=False, long_only=True, **rules)
        R[k], ON[k], n = sleeve(x, p, cost)
        print(f"R| sleeve {k:6s} buy only (cash costs) trades {n}", flush=True)
    bnx = S["BN"][0]
    pb = tbb.Params(buffer_pct=0.05, buffer_pts=0, event_exit=False, **IDX)
    A, _, na = sleeve(bnx, pb, 0.0005)
    SH, ONS, ns = sleeve(bnx, pb, 0.0005, side="SELL")
    print(f"R| BN futures both sides trades {na}, of them shorts {ns}", flush=True)
    ix = sorted(set().union(*[r.index for r in R.values()])); ix = pd.DatetimeIndex(ix); ix = ix[ix >= "2011-01-01"]
    Rd = pd.DataFrame(R).reindex(ix).fillna(0); On = pd.DataFrame(ON).reindex(ix).fillna(False).astype(bool)
    # weights set from yesterday's open-trade flags (the day a trade is entered it already earns: use today's flag)
    On2 = On | (Rd != 0)
    C = (Rd / len(S)).sum(axis=1)
    want = pd.DataFrame({k: np.minimum(0.01 / (S[k][1]["max_sl_pct"] / 100), 0.20) for k in S}, index=ix) * On2
    tot = want.sum(axis=1); scale = np.where(tot > 1, 1 / tot.replace(0, 1), 1.0)
    D = (want.mul(scale, axis=0) * Rd).sum(axis=1)
    lots = 0.95                                                   # 1 BN lot ~ Rs 19 L on Rs 20 L
    E = D + lots * SH.reindex(ix).fillna(0)
    books = {"A  BN futures both sides, 1 lot (live)": lots * A.reindex(ix).fillna(0), "B  BANKBEES buy only, all-in": Rd["BN"],
             "C  6 cash sleeves, equal 1/6": C, "D  6 cash sleeves, 1% risk, 20% cap": D, "E  D + BN shorts on 1 futures lot": E}
    print(f"R| average invested: C {(On2.sum(axis=1) / len(S)).mean() * 100:.0f}% · D {want.mul(scale, axis=0).sum(axis=1).mean() * 100:.0f}% of capital", flush=True)
    end = ix[-1]
    for nm, r in books.items():
        eq = (1 + r).cumprod()
        print(f"R| ===== {nm}", flush=True)
        for lab, st in (("last 1y", end - pd.DateOffset(years=1)), ("last 2y", end - pd.DateOffset(years=2)), ("last 3y", end - pd.DateOffset(years=3)),
                        ("last 5y", end - pd.DateOffset(years=5)), ("since 2021 (ex-Covid)", pd.Timestamp("2021-01-01")), ("since 2011", ix[0])):
            print(f"R|   {lab:22s} {stats(eq[eq.index >= st] / eq[eq.index >= st].iloc[0])}", flush=True)
        y20 = eq[(eq.index >= "2020-01-01") & (eq.index < "2021-01-01")]
        print(f"R|   2020 (Covid)           {y20.iloc[-1] / y20.iloc[0] * 100 - 100:+.1f}%", flush=True)
        yrs = eq.resample("YE").last().pct_change().dropna()
        print("R|   years " + " ".join(f"{d.year}:{v * 100:+.0f}" for d, v in yrs.iloc[::-1].items()), flush=True)


if __name__ == "__main__":
    main()
