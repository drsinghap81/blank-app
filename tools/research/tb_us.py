"""Top Bottom on liquid US stocks and index ETFs (24 Nov 2026, Amritpal: "any US stocks we can test"). Yahoo daily (split/dividend
adjusted), 2010 -> today; stock rules 1.5/3/3 (ETFs 1/2/2), buffer 0.05%, 0.05% cost a round trip; both sides and buy-only.
Same anti-cherry-pick split as the India screen: 2010-17 vs 2018-26, plus last 5 / 2 years. Survivors only (today's large caps)."""
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, ".."))
import topbottom_backtest as tbb  # noqa: E402

ETF = ["SPY", "QQQ", "IWM", "DIA", "XLF", "XLK", "XLE", "SMH", "GLD", "SLV", "TLT"]
STK = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "JPM", "V", "MA", "UNH", "XOM", "LLY", "COST", "HD", "PG", "JNJ", "WMT",
       "BAC", "NFLX", "AMD", "ORCL", "CRM", "ADBE", "KO", "PEP", "MRK", "ABBV", "CVX", "CAT", "GE", "BA", "DIS", "INTC", "MU", "QCOM", "TXN",
       "IBM", "GS", "MS", "NKE", "SBUX", "MCD", "UBER", "PLTR", "CNC", "ACGL", "ELF", "MSCI", "SIGI", "CL", "BDX", "GMAB"]
SPLIT = pd.Timestamp("2018-01-01")


def perf(t):
    if t is None or len(t) == 0:
        return None
    r = t.Pct / 100 - 0.0005; yrs = max((t.ExitDate.max() - t.EntryDate.min()).days / 365.25, 0.5)
    eq = (1 + r).cumprod(); g, b = r[r > 0].sum(), -r[r < 0].sum()
    return dict(n=len(t), pf=round(g / b, 2) if b else 9.0, cagr=round((eq.iloc[-1] ** (1 / yrs) - 1) * 100, 1), dd=round(((eq / eq.cummax()) - 1).min() * 100))


d = yf.download(ETF + STK, start="2009-06-01", progress=False, auto_adjust=True, group_by="ticker", threads=True)
rows = []
for s in ETF + STK:
    try:
        x = d[s][["Open", "High", "Low", "Close"]].dropna()
    except Exception:  # noqa: BLE001
        continue
    x = x[(x.High >= x.Low) & (x.index >= "2010-01-01")]; x.index = pd.to_datetime(x.index).tz_localize(None)
    if len(x) < 500:
        continue
    kw = dict(day_sl_pct=1.0, max_sl_pct=2.0, be_pct=2.0, gap_pct=1.0) if s in ETF else dict(day_sl_pct=1.5, max_sl_pct=3.0, be_pct=3.0, gap_pct=1.5)
    bh = (x.Close.iloc[-1] / x.Close[x.index >= SPLIT].iloc[0]) ** (365.25 / (x.index[-1] - SPLIT).days) - 1 if x.index[0] < SPLIT else np.nan
    r = dict(sym=s, kind="ETF" if s in ETF else "stock", bh18=round(bh * 100, 1) if bh == bh else None)
    for lab, lo in (("both", False), ("buy", True)):
        t = tbb.run_live(x, tbb.Params(buffer_pct=0.05, buffer_pts=0, event_exit=False, long_only=lo, **kw))
        t["EntryDate"] = pd.to_datetime(t.EntryDate); t["ExitDate"] = pd.to_datetime(t.ExitDate); end = t.ExitDate.max()
        for k, m in (("in", t.EntryDate < SPLIT), ("out", t.EntryDate >= SPLIT), ("l5", t.ExitDate > end - pd.DateOffset(years=5)), ("l2", t.ExitDate > end - pd.DateOffset(years=2))):
            p = perf(t[m])
            for kk, vv in (p or {}).items():
                r[f"{lab}_{k}_{kk}"] = vv
    rows.append(r)
D = pd.DataFrame(rows)
ok = D.dropna(subset=["buy_in_pf", "buy_out_pf"])
print(f"R| instruments {len(D)} | buy-only: rank corr PF 2010-17 vs 2018-26 {ok.buy_in_pf.corr(ok.buy_out_pf, method='spearman'):+.2f}; both sides {ok.both_in_pf.corr(ok.both_out_pf, method='spearman'):+.2f}", flush=True)
q = pd.qcut(ok.buy_in_pf.rank(method="first"), 3, labels=["low", "mid", "high"])
for i, g in ok.groupby(q):
    print(f"R| buy-only 2018-26 by 2010-17 PF tercile {i}: n{len(g)} median PF {g.buy_out_pf.median():.2f} CAGR {g.buy_out_cagr.median():+.1f}% DD {g.buy_out_dd.median():.0f}% PF>1 {(g.buy_out_pf > 1).mean() * 100:.0f}% | buy&hold {g.bh18.median():+.1f}%", flush=True)
print(f"R| share PF>1 2018-26: buy-only {(D.buy_out_pf > 1).mean() * 100:.0f}%, both {(D.both_out_pf > 1).mean() * 100:.0f}% | median CAGR buy-only {D.buy_out_cagr.median():+.1f}% vs both {D.both_out_cagr.median():+.1f}% vs buy&hold {D.bh18.median():+.1f}%", flush=True)
for _, r in D.sort_values("buy_out_pf", ascending=False).iterrows():
    print(f"R| {r.sym:5s} {r.kind:5s} | BUY 2010-17 PF {r.get('buy_in_pf')} | 2018-26 PF {r.get('buy_out_pf')} {r.get('buy_out_cagr')}%/yr DD {r.get('buy_out_dd')}% | 5y PF {r.get('buy_l5_pf')} {r.get('buy_l5_cagr')}% | 2y PF {r.get('buy_l2_pf')} | BOTH 2018-26 PF {r.get('both_out_pf')} {r.get('both_out_cagr')}% DD {r.get('both_out_dd')}% | B&H 2018-26 {r.bh18}%/yr", flush=True)
