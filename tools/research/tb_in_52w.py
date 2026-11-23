"""Top Bottom only inside 52-WEEK-HIGH cup breakouts (24 Nov 2026, Amritpal: "check this on 52-week high breakouts as well; take a
sample of a few stocks that made a cup breakout at the 52-week high").
Signal = the app's 'day cup close' (tools/cupclose.py via candle_takeout.dcup_days): close above the highest high of the last 250 days,
that rim >= 20 days old, cup >= 15% deep, room to the next older peak. Window = breakout close -> exit, two exit rules:
  W30: weekly close below the 30-week SMA (as Monthly ATH)      E921: daily EMA9 closes below EMA21 (as Trend 9/21)
one window at a time per stock. Hold = buy the next open, sell the next open after the exit (0.4% cost). Top Bottom = live engine,
buy-only, stock rules 1.5/3/3, 0.1% cost, entries inside the window. NSE (Yahoo + bhavcopy patch, survivors), 2016 -> today.
Also prints a sample of recent breakouts with every Top Bottom trade inside the window."""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import flag_volume as FV  # noqa: E402
import topbottom_backtest as tbb  # noqa: E402
from candle_takeout import dcup_days  # noqa: E402

PILOT = bool(os.environ.get("PILOT"))
P_TB = tbb.Params(buffer_pct=0.05, buffer_pts=0, event_exit=False, long_only=True, day_sl_pct=1.5, max_sl_pct=3.0, be_pct=3.0, gap_pct=1.5)


def windows(x, sig, rule):
    c, o = x.CLOSE.to_numpy(float), x.OPEN.to_numpy(float); D = x.index; n = len(c); out = []; busy = -1
    if rule == "W30":
        w = x.CLOSE.resample("W-FRI").last().dropna(); s30 = w.rolling(30).mean(); bad = (w < s30)
        badday = bad.reindex(D, method="ffill").fillna(False).to_numpy() & np.isin(D, w.index.map(lambda d: D[D <= d][-1] if (D <= d).any() else D[0]))
    else:
        e9 = x.CLOSE.ewm(span=9, adjust=False).mean().to_numpy(); e21 = x.CLOSE.ewm(span=21, adjust=False).mean().to_numpy(); badday = e9 < e21
    for t in np.where(sig)[0]:
        if t <= busy or t + 1 >= n or D[t] < pd.Timestamp("2016-01-01"):
            continue
        k = next((j for j in range(t + 1, n) if badday[j]), None)
        ex = k + 1 if k is not None and k + 1 < n else n - 1
        out.append((t, ex, o[t + 1], o[ex] if k is not None and k + 1 < n else c[n - 1], k is None or k + 1 >= n)); busy = ex
    return out


def main():
    P = FV.load(); W = {"W30": [], "E921": []}; T_in = {"W30": [], "E921": []}; sample = []
    for k_, (sym, x) in enumerate(P.items()):
        try:
            if len(x) < 600:
                continue
            sig = dcup_days(x)
            if not sig.any():
                continue
            y = x.rename(columns={"OPEN": "Open", "HIGH": "High", "LOW": "Low", "CLOSE": "Close"})[["Open", "High", "Low", "Close"]]
            t = tbb.run_live(y, P_TB)
            if t.empty:
                continue
            t["EntryDate"] = pd.to_datetime(t.EntryDate); t["ExitDate"] = pd.to_datetime(t.ExitDate); t["ret"] = t.Pct / 100 - 0.001
            for rule in ("W30", "E921"):
                for (a, b, p0, p1, op) in windows(x, sig, rule):
                    m = (t.EntryDate > x.index[a]) & (t.EntryDate <= x.index[b]); tr = t[m]
                    T_in[rule] += list(tr.ret)
                    W[rule].append(dict(sym=sym, d=x.index[a], tb=float(np.prod(1 + tr.ret) - 1) if len(tr) else 0.0, n=len(tr), hold=p1 / p0 - 1 - 0.004, days=(x.index[b] - x.index[a]).days, open=op))
                    if rule == "W30" and x.index[a] >= pd.Timestamp("2025-06-01"):
                        sample.append(dict(sym=sym, d=x.index[a].date(), brk=round(float(x.CLOSE.iloc[a]), 2), hold=round((p1 / p0 - 1) * 100, 1), open=op,
                                           exit=x.index[b].date(), trades=[(r.EntryDate.date(), round(r.Entry, 2), r.ExitDate.date(), round(r.Exit, 2), round(r.Points, 2), r.Reason) for r in tr.itertuples()],
                                           tb=round((np.prod(1 + tr.ret) - 1) * 100, 1) if len(tr) else 0.0))
        except Exception as ex_:  # noqa: BLE001
            print("skip", sym, str(ex_)[:80])
        if k_ % 400 == 0:
            print("R| progress", k_, flush=True)
    def st(r):
        r = pd.Series(r).dropna(); g, b = r[r > 0].sum(), -r[r < 0].sum()
        return f"n {len(r)} avg {r.mean() * 100:+.2f}% win {(r > 0).mean() * 100:.0f}% PF {g / b if b else 9:.2f}"
    for rule, lab in (("W30", "exit weekly close < 30-wk SMA"), ("E921", "exit EMA9 < EMA21")):
        Wd = pd.DataFrame(W[rule]); end = Wd.d.max()
        print(f"R| [{lab}] TB trades inside 52w cup windows | {st(T_in[rule])}", flush=True)
        print(f"R| [{lab}] PER WINDOW ({len(Wd)}) | TB avg {Wd.tb.mean() * 100:+.1f}% median {Wd.tb.median() * 100:+.1f}% win {(Wd.tb > 0).mean() * 100:.0f}% | HOLD avg {Wd.hold.mean() * 100:+.1f}% median {Wd.hold.median() * 100:+.1f}% win {(Wd.hold > 0).mean() * 100:.0f}% | TB beat hold {(Wd.tb > Wd.hold).mean() * 100:.0f}% | TB trades/window {Wd.n.mean():.1f} | median days {Wd.days.median():.0f}", flush=True)
        for y in (1, 2, 3, 5):
            w = Wd[Wd.d > end - pd.DateOffset(years=y)]; print(f"R| [{lab}] started last {y}y ({len(w)}) | TB {w.tb.mean() * 100:+.1f}% vs hold {w.hold.mean() * 100:+.1f}%", flush=True)
        q = Wd.hold.quantile([0.2, 0.8]).values
        for nm, M in (("winners top 20%", Wd.hold >= q[1]), ("middle", (Wd.hold > q[0]) & (Wd.hold < q[1])), ("losers bottom 20%", Wd.hold <= q[0])):
            w = Wd[M]; print(f"R| [{lab}] {nm} | TB {w.tb.mean() * 100:+.1f}% vs hold {w.hold.mean() * 100:+.1f}%", flush=True)
        w = Wd[~((Wd.d >= "2020-02-15") & (Wd.d < "2021-01-01"))]; print(f"R| [{lab}] ex-Covid | TB {w.tb.mean() * 100:+.1f}% vs hold {w.hold.mean() * 100:+.1f}%", flush=True)
    S = sorted(sample, key=lambda s: s["d"], reverse=True)
    pick = [s for s in S if s["trades"]]
    rng = np.random.default_rng(7); pick = [pick[i] for i in sorted(rng.choice(len(pick), size=min(6, len(pick)), replace=False))] if pick else []
    for s in pick:
        print(f"R| SAMPLE {s['sym']} breakout {s['d']} close {s['brk']} | hold to {s['exit']}{' (still open)' if s['open'] else ''}: {s['hold']:+.1f}% | Top Bottom {len(s['trades'])} trades: {s['tb']:+.1f}%", flush=True)
        for tr in s["trades"]:
            print(f"R| SAMPLE   {s['sym']} buy {tr[0]} @ {tr[1]} -> {tr[2]} @ {tr[3]} | {tr[4]:+.2f} pts | {tr[5]}", flush=True)


if __name__ == "__main__":
    main()
