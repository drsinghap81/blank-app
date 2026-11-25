"""Monthly-ATH / Cup 9/21 entry: current intraday trigger vs waiting for a daily CLOSE above the wick highs (25 Nov 2026, Amritpal on
AGARWALEYE: "its not a twelve month cup close either" -> "yes, test it; remember the buy triggers 0.1-0.2% above the closing candle
the next day").

Setup (same as tools/ath_scan.py): ATH month = the completed month with the highest monthly CLOSE; base = months since it
(Cup 9/21 = 12-23 months, Momentum = 24+); stock above a RISING 30-week SMA (vs 4 weeks earlier) at the last completed week;
>= Rs 2 cr/day traded (20-day average). The setup lasts until a month closes above the old ATH close (that month becomes the new
ATH month, base 0).
Entries:
  A   current : the day's high crosses the HIGH of the ATH month -> buy at that level (or the open if it gaps above)
  C   close   : a daily CLOSE above the ATH-month high, then buy next day above that candle's high + 0.15% (only next day)
  B   wick    : a daily CLOSE above the highest INTRADAY high before it (all wicks since listing / data start, incl. the ATH month),
                then buy next day above that candle's high + 0.15% (only next day)
  B5  wick-5d : as B, the buy-stop stays for 5 sessions
Exits: Cup 9/21 = daily close with EMA9 < EMA21 -> next open; Momentum = weekly close below the 30-week SMA -> next open.
0.4% round trip. Per-trade stats, newest-first years, 2021-26, bull/bear (Nifty above its 200-DMA), ex-Covid, and a 10-slot
equal-weight portfolio per system. Data: Yahoo daily from 2000 (full NSE list). PILOT env = 150 stocks."""
import os
import sys
import time

import numpy as np
import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, ".."))
from global_universe import symbols  # noqa: E402

KEEP_OPEN = False
COST = 0.004; BUF = 0.0015; COVID = (pd.Timestamp("2020-02-15"), pd.Timestamp("2020-12-31"))


MKT = (os.environ.get("UNIV") or "NSE").upper()
MINV = {"NSE": 2e7, "US": 5e6, "ASX": 1e6, "UK": 1e8}[MKT]
COST = {"NSE": 0.004, "US": 0.001, "ASX": 0.002, "UK": 0.006}[MKT]
BENCH = {"NSE": "^NSEI", "US": "^GSPC", "ASX": "^AXJO", "UK": "^FTSE"}[MKT]


def load():
    tick = list(symbols(MKT).ticker)
    if os.environ.get("PILOT"):
        tick = sorted(tick)[:150]
    out = {}
    for i in range(0, len(tick), 150):
        ch = tick[i:i + 150]; d = None
        for _ in range(3):
            try:
                d = yf.download(ch, start="2000-01-01", auto_adjust=True, progress=False, group_by="column", threads=True); break
            except Exception as e:  # noqa: BLE001
                print("retry", e); time.sleep(20)
        if d is None or d.empty:
            continue
        for t in ch:
            try:
                x = pd.DataFrame({"O": d["Open"][t], "H": d["High"][t], "L": d["Low"][t], "C": d["Close"][t], "V": d["Volume"][t]}).dropna()
            except Exception:  # noqa: BLE001
                continue
            x = x[(x.C > 0) & (x.O > 0)]
            if len(x) < 400:
                continue
            x.index = pd.to_datetime(x.index).tz_localize(None); out[t.replace(".NS", "")] = x
        print("R| loaded", i + len(ch), len(out), flush=True)
    return out


def trades_for(sym, x, reg):
    o, h, l, c = (x[k].to_numpy(float) for k in "OHLC"); D = x.index; n = len(c)
    val = (x.C * x.V).rolling(20).mean().to_numpy(float)
    e9 = x.C.ewm(span=9, adjust=False).mean().to_numpy(float); e21 = x.C.ewm(span=21, adjust=False).mean().to_numpy(float)
    wk = x.C.resample("W-FRI").last().dropna(); s30 = wk.rolling(30).mean()
    wk_ok = (wk > s30) & (s30 > s30.shift(4))
    wk_below = wk < s30
    # map each day to the last COMPLETED week (strictly before this day's week)
    wk_idx = np.searchsorted(wk.index.values, D.values, side="left") - 1
    mon = x.resample("ME").agg({"H": "max", "C": "last"}).dropna()
    m_of_day = np.searchsorted(mon.index.values, D.values, side="left")        # index of this day's month in mon
    cumh = np.maximum.accumulate(h)
    out = []
    # monthly state: for month k (current, incomplete), ATH month = argmax close over months < k
    mc = mon.C.to_numpy(float); mh = mon.H.to_numpy(float)
    best = np.full(len(mon), -1)
    bi = -1
    for k in range(len(mon)):
        best[k] = bi
        if bi < 0 or mc[k] > mc[bi]:
            bi = k

    def exit_after(j, sysk):
        """index of the exit fill (next open) and price"""
        if sysk == "tf":
            for k in range(j + 1, n - 1):
                if e9[k] < e21[k]:
                    return k + 1, o[k + 1]
        else:
            for k in range(j + 1, n):
                w = wk_idx[k]
                if w > wk_idx[k - 1] and w >= 0 and wk.index[w] > D[j] and bool(wk_below.iloc[w]):   # a week just completed below SMA30
                    return k, o[k]
        return None

    done = {}                      # (variant, ath month) -> traded
    pend = {}                      # variant -> (buy level, last day index allowed, ath month, sys)
    for j in range(260, n - 2):
        mk = m_of_day[j]
        if mk >= len(mon):
            continue
        am = best[mk]
        if am < 0:
            continue
        base = mk - am
        w = wk_idx[j]
        if w < 30 or not bool(wk_ok.iloc[w]) or not (val[j] >= MINV) or base < 12:
            pend.clear(); continue
        sysk = "tf" if base < 24 else "mom"
        trig = mh[am]
        wick = cumh[j - 1]          # every intraday high before today
        fills = []
        # A: intraday cross of the ATH-month high
        if ("A", am) not in done and h[j] > trig:
            fills.append(("A", j, max(o[j], trig)))
        # pending next-day buy-stops (C, B, B5)
        for v in list(pend):
            lvl, last, am0, s0 = pend[v]
            if am0 != am or j > last:
                del pend[v]; continue
            if h[j] > lvl:
                fills.append((v, j, max(o[j], lvl))); del pend[v]
        for v, jj, px in fills:
            done[(v, am)] = True
            ex = exit_after(jj, sysk)
            if ex is None:
                if not KEEP_OPEN:
                    continue
                ex = (n - 1, c[n - 1])            # 26 Nov 2026 (combo_compare): still open -> marked at the last close
            k, xp = ex
            out.append(dict(sym=sym, v=v, sys=sysk, d=D[jj], dx=D[k], ret=xp / px - 1 - COST, hold=k - jj, bull=bool(reg.get(D[jj], True)), base=base,
                            e=float(px), x=float(xp), open=ex[0] == n - 1 and KEEP_OPEN))
        # set up next-day orders from today's close
        if ("C", am) not in done and "C" not in pend and c[j] > trig:
            pend["C"] = (h[j] * (1 + BUF), j + 1, am, sysk)
        if c[j] > max(wick, trig):
            if ("B", am) not in done and "B" not in pend:
                pend["B"] = (h[j] * (1 + BUF), j + 1, am, sysk)
            if ("B5", am) not in done and "B5" not in pend:
                pend["B5"] = (h[j] * (1 + BUF), j + 5, am, sysk)
    return out


def port(X):
    X = X.sort_values(["d", "sym"]); eq = 1.0; op = []; peak = 1.0; mdd = 0.0; curve = []
    for r in X.itertuples():
        for p in sorted([p for p in op if p[0] <= r.d]):
            eq += p[1]; peak = max(peak, eq); mdd = min(mdd, eq / peak - 1)
        op = [p for p in op if p[0] > r.d]
        if len(op) < 10:
            op.append((r.dx, 0.1 * eq * r.ret))
    for p in sorted(op):
        eq += p[1]; peak = max(peak, eq); mdd = min(mdd, eq / peak - 1)
    yrs = max((X.dx.max() - X.d.min()).days / 365.25, 1)
    return (max(eq, 1e-9) ** (1 / yrs) - 1) * 100, mdd * 100


def main():
    print(f"R| market {MKT}, cost {COST * 100:.1f}%, min traded {MINV:,.0f}/day", flush=True)
    nif = yf.download(BENCH, start="2005-01-01", auto_adjust=True, progress=False)["Close"].squeeze()
    reg = (nif > nif.rolling(200).mean()).to_dict()
    P = load(); T = []
    for s, x in P.items():
        try:
            T += trades_for(s, x, reg)
        except Exception as e:  # noqa: BLE001
            print("err", s, e)
    T = pd.DataFrame(T); T = T[T.d >= "2007-01-01"]
    names = {"A": "A  current: trade above ATH-month high", "C": "C  close above it, buy next day +0.15%",
             "B": "B  close above all wicks, next day +0.15%", "B5": "B5 close above wicks, buy-stop 5 days"}
    for sysk, lab in (("tf", "CUP 9/21 (12-23 month base)"), ("mom", "MOMENTUM (24+ month base)")):
        print(f"R| ===== {lab} =====", flush=True)
        for v in ("A", "C", "B", "B5"):
            X = T[(T.sys == sysk) & (T.v == v)]
            if len(X) < 20:
                print(f"R| {names[v]} n {len(X)}", flush=True); continue
            xb = X[X.d >= "2021-07-01"]; xc = X[~X.d.between(*COVID)]; cg, dd = port(X)
            print(f"R| {names[v]:42s} n {len(X):5d} | win {(X.ret > 0).mean() * 100:3.0f}% | avg {X.ret.mean() * 100:+6.2f}% | median {X.ret.median() * 100:+5.1f}% | "
                  f"hold {X.hold.median():.0f}d | 2021-26 {xb.ret.mean() * 100:+.2f}% (n {len(xb)}) | bull {X[X.bull].ret.mean() * 100:+.2f}% bear {X[~X.bull].ret.mean() * 100:+.2f}% | "
                  f"ex-Covid {xc.ret.mean() * 100:+.2f}% | 10-slot CAGR {cg:+.1f}% maxDD {dd:.1f}%", flush=True)
            y = X.groupby(X.d.dt.year).ret.agg(["size", "mean"]).sort_index(ascending=False)
            print(f"R| {v} by year: " + " | ".join(f"{k}: {int(r['size'])} {r['mean'] * 100:+.1f}%" for k, r in y.head(10).iterrows()), flush=True)
        # what B skips: A trades whose setup never got a close above the wicks
        A = T[(T.sys == sysk) & (T.v == "A")]; Bk = set(zip(T[(T.sys == sysk) & (T.v == "B")].sym, T[(T.sys == sysk) & (T.v == "B")].d.dt.to_period("M")))
        Bsyms = T[(T.sys == sysk) & (T.v == "B")].groupby("sym").d.apply(list).to_dict()
        miss = A[[not any(abs((b - a).days) < 120 for b in Bsyms.get(s, [])) for s, a in zip(A.sym, A.d)]]
        got = A[[any(abs((b - a).days) < 120 for b in Bsyms.get(s, [])) for s, a in zip(A.sym, A.d)]]
        print(f"R| A trades B never confirmed (no close above the wicks within ~4 months): n {len(miss)} avg {miss.ret.mean() * 100:+.2f}% win {(miss.ret > 0).mean() * 100:.0f}% | "
              f"A trades B also took: n {len(got)} avg {got.ret.mean() * 100:+.2f}%", flush=True)


if __name__ == "__main__":
    main()
