"""Cash-and-carry arbitrage backtest (27 Nov 2026, Amritpal: "do you see any value in arbitrage" -> cash-and-carry -> "backtest it").
Each month, the day after a monthly expiry: BUY the stock (or NIFTYBEES for Nifty) and SELL the same value of its near-month future
(the one expiring next); hold both to that expiry's close, when the future has converged to the spot price; repeat.
Realised P&L per month = spot return - future return (one unit each, actual closes - includes any convergence error; dividends are
NOT added, so stock returns are slightly understated). Data: near-month futures closes from NSE bhavcopies (data/futures, with the
expiry date) + Yahoo cash closes (.NS, unadjusted for dividends).
Costs a round trip: stocks 0.35% (delivery STT 0.1% each side, future-sell STT 0.02%, charges, brokerage, ~0.03% slippage a leg);
NIFTYBEES + Nifty future 0.15% (ETF STT is tiny). Capital = the cash leg + 15% futures margin in cash (returns / 1.15); with the
shares pledged as margin it is closer to 1.0x (shown too).
Books: NIFTY only; ALL liquid stock futures equal weight; TOP-5 stocks by the premium at entry (only if the premium beats costs);
also "enter only when the annualised premium after costs >= 5%". Newest first, ex-Covid, yearly."""
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

COST_STK, COST_ETF, MARGIN = 0.0035, 0.0015, 0.15
SKIP = {"RELCAPITAL", "RELINFRA", "BANKNIFTY", "NIFTY"}
YMAP = {"M_M": "M&M", "BAJAJ-AUTO": "BAJAJ-AUTO"}


def fut(sym):
    x = pd.read_csv(f"data/futures/{sym}.csv", parse_dates=["Date", "Expiry"]).set_index("Date")[["Close", "Expiry"]].dropna()
    return x[x.index >= "2012-01-01"]


def cash(tk):
    d = yf.download(tk, start="2011-06-01", progress=False, auto_adjust=False)
    d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]; d.index = pd.to_datetime(d.index).tz_localize(None)
    return d["Close"].dropna()


def months(F, S, cost, ratio_hedge=False):
    """one row per expiry cycle: entry the first day after an expiry, exit on the next expiry day."""
    J = F.join(S.rename("S"), how="inner").dropna()
    if len(J) < 100:
        return pd.DataFrame()
    exp = J.Expiry
    starts = J.index[1:][exp.to_numpy()[1:] != exp.to_numpy()[:-1]]          # first day of each new near-month contract
    rows = []
    for d0 in starts:
        e = J.loc[d0, "Expiry"]
        seg = J[(J.index >= d0) & (J.index <= e)]
        if len(seg) < 5 or seg.index[-1] < e - pd.Timedelta(days=3):
            continue
        S0, F0, S1, F1 = seg.S.iloc[0], seg.Close.iloc[0], seg.S.iloc[-1], seg.Close.iloc[-1]
        basis = F0 / S0 - 1 if not ratio_hedge else np.nan
        if not ratio_hedge and abs(basis) > 0.03:              # data glitch (corporate action / bad print)
            continue
        if ratio_hedge:                                          # ETF vs index future: hedge equal value
            r = (S1 / S0 - 1) - (F1 / F0 - 1)
            basis = np.nan
        else:
            r = (S1 - S0) / S0 - (F1 - F0) / S0
        days = (seg.index[-1] - d0).days
        rows.append(dict(d0=d0, e=seg.index[-1], days=days, basis=basis, gross=r, net=r - cost,
                         ann_basis=(basis - cost) * 365 / max(days, 1) if not np.isnan(basis) else np.nan))
    return pd.DataFrame(rows)


def report(name, m):
    """m: monthly series of returns on the cash leg (index = exit date)."""
    if not len(m):
        print(f"R| {name}: no data", flush=True); return
    m = m.sort_index()
    for lab, lev in (("cash + 15% margin", 1 + MARGIN), ("shares pledged", 1.0)):
        x = m / lev
        out = []
        for wl, st in (("last 1y", m.index[-1] - pd.DateOffset(years=1)), ("last 3y", m.index[-1] - pd.DateOffset(years=3)),
                       ("2021+ ex-Covid", pd.Timestamp("2021-01-01")), ("2012+", pd.Timestamp("2012-01-01"))):
            z = x[x.index >= st]
            if len(z) < 6:
                continue
            yrs = max((z.index[-1] - z.index[0]).days / 365.25, 0.5)
            out.append(f"{wl} {((1 + z).prod() ** (1 / yrs) - 1) * 100:+5.1f}%/yr")
        z = x[x.index >= "2021-01-01"]
        print(f"R| {name:34s} [{lab:17s}] " + " | ".join(out) + f" | 2021+ months up {(z > 0).mean() * 100:3.0f}% worst {z.min() * 100:+.2f}%", flush=True)
    yy = (m / (1 + MARGIN)).groupby(m.index.year).apply(lambda v: ((1 + v).prod() - 1) * 100)
    print(f"R|   years {name[:20]}: " + " ".join(f"{y}:{v:+.1f}" for y, v in yy.iloc[::-1].items()), flush=True)


def main():
    # ---- NIFTY via NIFTYBEES
    F = fut("NIFTY"); S = cash("NIFTYBEES.NS")
    mN = months(F, S, COST_ETF, ratio_hedge=True)
    Fi = fut("NIFTY"); Si = cash("^NSEI"); bN = months(Fi, Si, 0.0)
    if len(bN):
        z = bN[bN.d0 >= "2021-01-01"]
        print(f"R| NIFTY future premium at entry 2021+: median {z.basis.median() * 100:.2f}% for {z.days.median():.0f} days = "
              f"{(z.basis / z.days * 365).median() * 100:.1f}%/yr gross | last 6: " +
              " ".join(f"{r.d0:%b%y} {r.basis * 100:+.2f}%" for r in bN.tail(6).itertuples()), flush=True)
    if len(mN):
        report("NIFTY: NIFTYBEES + sell Nifty fut", mN.set_index("e").net)
    # ---- stocks
    syms = [f[:-4] for f in sorted(os.listdir("data/futures")) if f.endswith(".csv") and f[:-4] not in SKIP]
    per = {}
    for s in syms:
        try:
            S = cash(YMAP.get(s, s) + ".NS")
            m = months(fut(s), S, COST_STK)
        except Exception as ex:  # noqa: BLE001
            print(f"R| {s} skip {str(ex)[:60]}", flush=True); continue
        if len(m) >= 12:
            per[s] = m
    print(f"R| stocks with data: {len(per)}", flush=True)
    A = pd.concat([m.assign(sym=s) for s, m in per.items()])
    A["cycle"] = A.e.dt.to_period("M")
    z = A[A.d0 >= "2021-01-01"]
    print(f"R| stock premium at entry 2021+: median {z.basis.median() * 100:.2f}% ({(z.basis / z.days * 365).median() * 100:.1f}%/yr gross), "
          f"after 0.35% cost {(z.ann_basis).median() * 100:.1f}%/yr; share of entries where the premium beats costs: {(z.basis > COST_STK).mean() * 100:.0f}%", flush=True)
    books = {
        "ALL stocks equal weight": A.groupby("cycle").net.mean(),
        "TOP-5 premium (beats costs)": A[A.basis > COST_STK].sort_values("basis", ascending=False).groupby("cycle").head(5).groupby("cycle").net.mean(),
        "TOP-5, only if >= 5%/yr after costs": A[A.ann_basis >= 0.05].sort_values("basis", ascending=False).groupby("cycle").head(5).groupby("cycle").net.mean(),
    }
    allc = sorted(A.cycle.unique())
    for nm, s in books.items():
        s = s.reindex(allc).fillna(0.0); s.index = s.index.to_timestamp("M")
        report(nm, s)
    # what it pays right now: the latest entries
    last = A[A.d0 == A.d0.max()].sort_values("basis", ascending=False)
    print(f"R| LATEST cycle (entered {A.d0.max().date()}): top premiums " +
          " ".join(f"{r.sym} {r.basis * 100:+.2f}% ({r.ann_basis * 100:+.1f}%/yr net)" for r in last.head(8).itertuples()), flush=True)
    print(f"R| net of costs and per trade: stocks avg {A[A.d0 >= '2021-01-01'].net.mean() * 100:+.3f}% a month, "
          f"loss months {(A[A.d0 >= '2021-01-01'].net < 0).mean() * 100:.0f}%", flush=True)


if __name__ == "__main__":
    main()
