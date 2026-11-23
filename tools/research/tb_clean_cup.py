"""Does a stock's PAST cup-breakout behaviour pick where Top Bottom works? (24 Nov 2026, Amritpal: "keep stocks for Top Bottom that in
history gave a clean uptrend after a long-term cup breakout").
Windows = 52-week/ATH day cup close -> weekly close < 30-wk SMA (tb_in_52w.windows). A window is CLEAN if the hold made > +10% and
log-price R^2 over the window >= 0.7 (a steady climb). Walk-forward: for each breakout only windows that had already ENDED before it count
as history. Groups: last finished window clean / not clean / no history; also '2+ clean in history'. Top Bottom buy-only 1.5/3/3, 0.1% cost.
Ends with today's list: stocks with clean history whose newest breakout window is still open."""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import flag_volume as FV  # noqa: E402
import topbottom_backtest as tbb  # noqa: E402
from candle_takeout import dcup_days  # noqa: E402
from tb_in_52w import P_TB, windows  # noqa: E402

FUT = {f[:-4].upper() for f in os.listdir(os.path.join(HERE, "..", "..", "data", "futures")) if f.endswith(".csv")}


def r2(lc):
    if len(lc) < 10:
        return 0.0
    t = np.arange(len(lc)); return float(np.corrcoef(t, lc)[0, 1] ** 2) if np.std(lc) > 0 else 0.0


def main():
    P = FV.load(); rows = []; trades = []
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
            t["EntryDate"] = pd.to_datetime(t.EntryDate); t["ret"] = t.Pct / 100 - 0.001
            lc = np.log(x.CLOSE.to_numpy(float)); hist = []
            for (a, b, p0, p1, op) in windows(x, sig, "W30"):
                hold = p1 / p0 - 1 - 0.004
                if abs(hold) > 3:   # bad data (splits)
                    continue
                prior = [h for h in hist if h["end"] < x.index[a]]
                g = "none" if not prior else ("clean" if prior[-1]["clean"] else "messy")
                nclean = sum(h["clean"] for h in prior); ptb = np.mean([h["tb"] for h in prior]) if prior else np.nan
                tr = t[(t.EntryDate > x.index[a]) & (t.EntryDate <= x.index[b])]
                tb = float(np.prod(1 + tr.ret) - 1) if len(tr) else 0.0
                rr = r2(lc[a:b + 1]); cl = (hold > 0.10) and rr >= 0.7
                rows.append(dict(sym=sym, d=x.index[a], end=x.index[b], g=g, nclean=nclean, ptb=ptb, tb=tb, hold=hold, clean=cl, open=op, r2=rr,
                                 fut=sym.upper() in FUT, px=float(x.CLOSE.iloc[-1]), since=float(x.CLOSE.iloc[-1] / x.CLOSE.iloc[a] - 1)))
                trades += [(g, nclean, r) for r in tr.ret]
                hist.append(dict(end=x.index[b], clean=cl, tb=tb))
        except Exception as ex_:  # noqa: BLE001
            print("skip", sym, str(ex_)[:80])
        if k_ % 400 == 0:
            print("R| progress", k_, flush=True)
    D = pd.DataFrame(rows); T = pd.DataFrame(trades, columns=["g", "nclean", "r"]); end = D.d.max()
    print(f"R| windows {len(D)} | clean share {D.clean.mean() * 100:.0f}%", flush=True)
    def pf(r):
        g, b = r[r > 0].sum(), -r[r < 0].sum(); return g / b if b else 9
    def line(lab, w, tr):
        return f"{lab} ({len(w)}) | TB/window {w.tb.mean() * 100:+.1f}% (win {(w.tb > 0).mean() * 100:.0f}%) | hold {w.hold.mean() * 100:+.1f}% | this window clean {w.clean.mean() * 100:.0f}% | TB trade PF {pf(tr.r):.2f}"
    groups = [("last finished breakout CLEAN", D.g == "clean", T.g == "clean"), ("last finished breakout MESSY", D.g == "messy", T.g == "messy"),
              ("no earlier breakout", D.g == "none", T.g == "none"), ("2+ clean breakouts in history", D.nclean >= 2, T.nclean >= 2)]
    for lab, m, mt in groups:
        print("R| ALL " + line(lab, D[m], T[mt]), flush=True)
    for y in (1, 2, 3, 5):
        w = D[D.d > end - pd.DateOffset(years=y)]
        for lab, gg in (("clean", "clean"), ("messy", "messy"), ("none", "none")):
            ww = w[w.g == gg]; print(f"R| LAST{y}y {lab} ({len(ww)}) | TB {ww.tb.mean() * 100:+.1f}% hold {ww.hold.mean() * 100:+.1f}% clean-again {ww.clean.mean() * 100:.0f}%", flush=True)
    w = D[~((D.d >= "2020-02-15") & (D.d < "2021-01-01"))]
    for gg in ("clean", "messy", "none"):
        ww = w[w.g == gg]; print(f"R| EXCOVID {gg} ({len(ww)}) | TB {ww.tb.mean() * 100:+.1f}% hold {ww.hold.mean() * 100:+.1f}%", flush=True)
    for lab, m in (("past TB in breakouts > +10%", D.ptb > 0.10), ("past TB in breakouts <= 0", D.ptb <= 0)):
        ww = D[m]; print(f"R| PASTTB {lab} ({len(ww)}) | TB {ww.tb.mean() * 100:+.1f}% hold {ww.hold.mean() * 100:+.1f}%", flush=True)
    for lab, m in (("F&O only, clean", (D.g == "clean") & D.fut), ("F&O only, messy/none", (D.g != "clean") & D.fut)):
        ww = D[m]; print(f"R| FNO {lab} ({len(ww)}) | TB {ww.tb.mean() * 100:+.1f}% hold {ww.hold.mean() * 100:+.1f}%", flush=True)
    # today's list: newest window per stock still open, stock has clean history
    last = D.sort_values("d").groupby("sym").tail(1)
    now = last[last.open & (last.nclean >= 1)].sort_values(["nclean", "d"], ascending=[False, False])
    for r in now.itertuples():
        print(f"R| NOW {r.sym}{' F&O' if r.fut else ''} | breakout {r.d.date()} | clean past breakouts {r.nclean} | since breakout {r.since * 100:+.1f}% | price {r.px:.2f}", flush=True)
    # stock list by history (for futures universe)
    H = D[~D.open].groupby("sym").agg(n=("clean", "size"), nclean=("clean", "sum"), tb=("tb", "mean"), fut=("fut", "first"))
    H = H[(H.nclean >= 2) & H.fut].sort_values("nclean", ascending=False)
    for s, r in H.iterrows():
        print(f"R| FNOLIST {s} | breakouts {r.n} clean {int(r.nclean)} | avg TB/window {r.tb * 100:+.1f}%", flush=True)


if __name__ == "__main__":
    main()
