"""Top Bottom only in Monthly-ATH cup-breakout stocks (24 Nov 2026, Amritpal: "what if I only do Top Bottom in ATH cup breakout stocks").
Universe: NSE stocks (Yahoo + bhavcopy patch, survivors, liquid). ATH events exactly as tools/research/late_entry.py (24-month base,
cross of the ATH-month high, above a rising 30-week SMA, >= Rs 2 cr/day). The 'ATH window' = breakout day -> the system's exit
(weekly close below the 30-week SMA). Top Bottom = live engine, BUY-ONLY, stock rules 1.5/3/3, buffer 0.05%, 0.1% cost.
Compare per trade and per window:
  TB inside ATH windows (entries inside the window)  vs  TB on the same stocks outside windows  vs  TB on all stocks/all days;
  per window: TB compounded return vs simply holding the ATH trade (the Monthly ATH system itself, 0.4% cost).
Newest first by entry year; bull/bear (Nifty vs 200-day); ex-Covid. PILOT = 150 stocks. Output R| lines."""
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import flag_volume as FV  # noqa: E402
import topbottom_backtest as tbb  # noqa: E402
from late_entry import events  # noqa: E402

PILOT = bool(os.environ.get("PILOT"))


def st(r):
    r = pd.Series(r).dropna()
    if not len(r):
        return "-"
    g, b = r[r > 0].sum(), -r[r < 0].sum()
    return f"n {len(r)} avg {r.mean() * 100:+.2f}% win {(r > 0).mean() * 100:.0f}% PF {g / b if b else 9:.2f}"


def main():
    P = FV.load()
    n = yf.download("^NSEI", start="2012-01-01", progress=False, auto_adjust=True)["Close"]; n = (n.iloc[:, 0] if isinstance(n, pd.DataFrame) else n).dropna()
    n.index = pd.to_datetime(n.index).tz_localize(None); bull = n > n.rolling(200).mean()
    T_in, T_out, W = [], [], []
    p = tbb.Params(buffer_pct=0.05, buffer_pts=0, event_exit=False, long_only=True, day_sl_pct=1.5, max_sl_pct=3.0, be_pct=3.0, gap_pct=1.5)
    for k, (sym, x) in enumerate(P.items()):
        try:
            y = x.rename(columns={"OPEN": "Open", "HIGH": "High", "LOW": "Low", "CLOSE": "Close"})[["Open", "High", "Low", "Close"]]
            y = y[y.index >= "2012-01-01"]
            if len(y) < 600:
                continue
            t = tbb.run_live(y, p)
            if t.empty:
                continue
            t["EntryDate"] = pd.to_datetime(t.EntryDate); t["ret"] = t.Pct / 100 - 0.001
            ev = events(sym, x)
            mask = np.zeros(len(t), bool)
            for e in ev:
                d0, d1 = e["d"], e["D"][e["ex"]]
                m = ((t.EntryDate >= d0) & (t.EntryDate <= d1)).values; mask |= m
                tr = t.ret[m]
                W.append(dict(sym=sym, d=d0, tb=float(np.prod(1 + tr) - 1) if len(tr) else 0.0, n=int(m.sum()),
                              hold=e["xp"] / e["e0"] - 1 - 0.004, days=(d1 - d0).days, bull=bool(bull.asof(d0)) if len(bull) else None))
            for (_, r), m in zip(t.iterrows(), mask):
                (T_in if m else T_out).append(dict(d=r.EntryDate, ret=r.ret, has_ath=len(ev) > 0))
        except Exception as ex_:  # noqa: BLE001
            print("skip", sym, str(ex_)[:80])
        if k % 300 == 0:
            print("R| progress", k, len(W), flush=True)
    A, B, Wd = pd.DataFrame(T_in), pd.DataFrame(T_out), pd.DataFrame(W)
    Wd = Wd[Wd.d >= "2016-01-01"]; A = A[A.d >= "2016-01-01"]; B = B[B.d >= "2016-01-01"]
    end = max(A.d.max(), B.d.max())
    print(f"R| TB trades INSIDE ATH windows | {st(A.ret)}", flush=True)
    print(f"R| TB trades same stocks OUTSIDE windows | {st(B[B.has_ath].ret)}", flush=True)
    print(f"R| TB trades, stocks that never had an ATH event | {st(B[~B.has_ath].ret)}", flush=True)
    print(f"R| TB trades ALL | {st(pd.concat([A.ret, B.ret]))}", flush=True)
    for y in (1, 2, 3, 5):
        c = end - pd.DateOffset(years=y)
        print(f"R| last {y}y | inside {st(A[A.d > c].ret)} | outside {st(B[(B.d > c) & B.has_ath].ret)} | all {st(pd.concat([A[A.d > c].ret, B[B.d > c].ret]))}", flush=True)
    for yy in sorted(A.d.dt.year.unique(), reverse=True):
        print(f"R| year {yy} | inside {st(A[A.d.dt.year == yy].ret)} | all {st(pd.concat([A[A.d.dt.year == yy].ret, B[B.d.dt.year == yy].ret]))}", flush=True)
    print(f"R| PER ATH WINDOW ({len(Wd)}) | TB compounded avg {Wd.tb.mean() * 100:+.1f}% median {Wd.tb.median() * 100:+.1f}% win {(Wd.tb > 0).mean() * 100:.0f}% | "
          f"ATH hold avg {Wd.hold.mean() * 100:+.1f}% median {Wd.hold.median() * 100:+.1f}% win {(Wd.hold > 0).mean() * 100:.0f}% | TB beat hold {(Wd.tb > Wd.hold).mean() * 100:.0f}% | "
          f"avg TB trades per window {Wd.n.mean():.1f} | median days {Wd.days.median():.0f}", flush=True)
    for lab, M in (("bull", Wd.bull == True), ("bear", Wd.bull == False), ("ex-Covid", ~((Wd.d >= "2020-02-15") & (Wd.d < "2021-01-01")))):  # noqa: E712
        w = Wd[M]; print(f"R| windows {lab} ({len(w)}) | TB avg {w.tb.mean() * 100:+.1f}% vs hold {w.hold.mean() * 100:+.1f}%", flush=True)
    for y in (1, 2, 3, 5):
        w = Wd[Wd.d > Wd.d.max() - pd.DateOffset(years=y)]; print(f"R| windows started last {y}y ({len(w)}) | TB avg {w.tb.mean() * 100:+.1f}% vs hold {w.hold.mean() * 100:+.1f}%", flush=True)
    q = Wd.hold.quantile([0.2, 0.8]).values
    for lab, M in (("big winners (hold top 20%)", Wd.hold >= q[1]), ("middle", (Wd.hold > q[0]) & (Wd.hold < q[1])), ("losers (hold bottom 20%)", Wd.hold <= q[0])):
        w = Wd[M]; print(f"R| windows {lab} | TB avg {w.tb.mean() * 100:+.1f}% vs hold {w.hold.mean() * 100:+.1f}%", flush=True)


if __name__ == "__main__":
    main()
