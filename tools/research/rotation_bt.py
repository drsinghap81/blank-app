"""Industry rotation backtest (20 Nov 2026, Amritpal: "ride the rally in the short term with sector or industry rotation").
NSE official basic industries (3+ liquid stocks; today's members - survivorship bias in their favour), equal-weight daily index each.
Weekly (Friday close): relative rotation vs Nifty 50, same formula as the app (tools/group_pulse.py rrg):
  RS = industry / Nifty; RS-ratio = 100 x RS / 10-week average of RS; RS-momentum = 3-week average of 100 x ratio / last week's ratio.
Portfolios (equal weight across the industries held, rebalanced weekly at the Friday close, 0.20% cost on what changes):
  LEADING          hold every industry in Leading
  NEW LEADING      hold industries that entered Leading in the last 2 weeks (fresh moves only)
  IMPROVING        hold Improving (early)
  IMPROVING+LEADING hold both; exit when they drop to Weakening / Lagging
  TOP 5 RS-MOM     the 5 industries with the highest RS-momentum among Improving + Leading
Benchmarks: Nifty 50, and all industries equal weight. LIMIT env = pilot."""
import os
import sys
import time

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, "tools/research")
import industry_basket_intraday as B  # noqa: E402

IND, SYMS = B.IND, B.SYMS
COST = 0.002


def daily():
    out = {}
    for a in range(0, len(SYMS), 100):
        ch = [s + ".NS" for s in SYMS[a:a + 100]]
        for k in range(4):
            d = yf.download(ch, period="6y", interval="1d", progress=False, group_by="column", auto_adjust=True, threads=False)
            c = d["Close"] if len(d) else pd.DataFrame()
            got = [t for t in ch if t in c.columns and c[t].notna().sum() > 200]
            for t in got:
                out[t[:-3]] = c[t]
            if len(got) >= 0.9 * len(ch):
                break
            print("chunk", a, "got", len(got), "of", len(ch), "retry", k + 1, flush=True); time.sleep(30 * (k + 1))
        time.sleep(3)
    b = yf.download("^NSEI", period="6y", interval="1d", progress=False, auto_adjust=True)["Close"]
    return pd.DataFrame(out).sort_index(), (b.iloc[:, 0] if isinstance(b, pd.DataFrame) else b)


C, nifty = daily()
nifty = nifty.reindex(C.index).ffill()
ret = C.pct_change(fill_method=None).clip(-0.3, 0.3)
idx = pd.DataFrame({k: (1 + ret[[s for s in v if s in ret.columns]].mean(axis=1).fillna(0)).cumprod() for k, v in IND.items()})
W = idx.resample("W-FRI").last(); NW = nifty.resample("W-FRI").last()
RS = 100 * W.div(NW, axis=0)
ratio = 100 * RS / RS.rolling(10).mean()
mom = (100 * ratio / ratio.shift(1)).rolling(3).mean()
Q = pd.DataFrame(np.where(ratio >= 100, np.where(mom >= 100, "L", "W"), np.where(mom >= 100, "I", "G")), index=W.index, columns=W.columns)
Q = Q.where(ratio.notna() & mom.notna())
wret = W.pct_change(fill_method=None).shift(-1)          # next week's return of each industry (held from this Friday's close)
nret = NW.pct_change(fill_method=None).shift(-1)
start = Q.dropna(how="all").index[0]
print("R| industries", len(IND), "stocks", C.shape[1], "weeks", len(W.loc[start:]), "from", start.date(), flush=True)


def run(name, pick):
    held = set(); rows = []
    dates = [d for d in W.index if d >= start][:-1]
    for i, d in enumerate(dates):
        new = set(pick(d, i))
        turn = len(new ^ held) / max(1, len(new | held)) if (new or held) else 0
        r = float(wret.loc[d, list(new)].mean()) if new else 0.0
        rows.append((d, (0 if np.isnan(r) else r) - COST * turn * (1 if held or new else 0), len(new)))
        held = new
    s = pd.Series([x[1] for x in rows], index=[x[0] for x in rows]); n = pd.Series([x[2] for x in rows], index=s.index)
    eq = (1 + s).cumprod(); yrs = (s.index[-1] - s.index[0]).days / 365.25
    cagr = eq.iloc[-1] ** (1 / yrs) - 1; dd = (eq / eq.cummax() - 1).min()
    by = s.groupby(s.index.year).apply(lambda x: round(((1 + x).prod() - 1) * 100, 1)).to_dict()
    print(f"R| {name}: CAGR {cagr * 100:+.1f}%, max drawdown {dd * 100:.1f}%, weeks invested {np.mean(n > 0) * 100:.0f}%, avg industries held {n[n > 0].mean():.1f}, by year {by}", flush=True)


qs = lambda d, keys: [k for k in Q.columns if Q.at[d, k] in keys]  # noqa: E731
run("LEADING", lambda d, i: qs(d, ("L",)))
run("NEW LEADING (entered in last 2 weeks)", lambda d, i: [k for k in qs(d, ("L",)) if (Q[k].loc[:d].iloc[-3:-1] != "L").any()])
run("IMPROVING", lambda d, i: qs(d, ("I",)))
run("IMPROVING + LEADING", lambda d, i: qs(d, ("I", "L")))
run("TOP 5 RS-MOMENTUM within Improving + Leading", lambda d, i: sorted(qs(d, ("I", "L")), key=lambda k: -mom.at[d, k])[:5])
run("CONTROL: LAGGING", lambda d, i: qs(d, ("G",)))
run("CONTROL: WEAKENING", lambda d, i: qs(d, ("W",)))
run("BENCHMARK: all industries equal weight", lambda d, i: [k for k in Q.columns if pd.notna(Q.at[d, k])])
s = nret.loc[start:].dropna(); eq = (1 + s).cumprod(); yrs = (s.index[-1] - s.index[0]).days / 365.25
print(f"R| BENCHMARK Nifty 50: CAGR {(eq.iloc[-1] ** (1 / yrs) - 1) * 100:+.1f}%, max drawdown {(eq / eq.cummax() - 1).min() * 100:.1f}%, by year "
      f"{s.groupby(s.index.year).apply(lambda x: round(((1 + x).prod() - 1) * 100, 1)).to_dict()}", flush=True)
