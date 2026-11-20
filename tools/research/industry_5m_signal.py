"""Option-trader 5-minute rules on the STOCKS themselves, with industry filters (20 Nov 2026, Amritpal: "did you check on 5 minutes
with the same system we are doing with the option trader bot").

Bars: Yahoo 5-minute, last ~60 sessions, liquid NSE stocks in NSE basic industries (3+ liquid stocks).
Signal on a completed 5-minute candle (same as tools/live_server/opt_trader.py, applied to the stock):
  BUY : RSI(14) crosses above 60, close above the upper Bollinger band (20, 2), close above the session VWAP,
        Nifty AND Bank Nifty both up on the day.
  SELL: mirror - RSI crosses below 40, close below the lower band, below VWAP, both indices down.
  no entries 11:00-14:30, none after 15:00.
Entry: stop order beyond the signal candle's high (low for SELL), valid 3 candles, cancelled if the other side of the candle breaks
first. Stop: the signal candle's low (high), at least 0.3% away. Exit: a 5-minute close back below (above) the 5 EMA, or 15:15.
Cost 0.10% per round trip. Results in R (1 R = the stop distance) and in % of capital at 0.25% risk a trade (4 open = 1%).
Filters added on top: industry breadth agrees (>= 60% of its stocks green for a BUY, <= 40% for a SELL) and/or Pulse
(strong = top 25% of industries for a BUY, weak = bottom 25% for a SELL), Pulse as of the previous close."""
import os
import sys
import time

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, "tools/research")
import industry_basket_intraday as B  # noqa: E402
import industry_basket_pulse as P  # noqa: E402

IND, SYMS = B.IND, B.SYMS
COST = 0.001
IND_OF = {s: k for k, v in IND.items() for s in v}


def dl5():
    out = {k: {} for k in ("Open", "High", "Low", "Close", "Volume")}
    for a in range(0, len(SYMS), 80):
        ch = [s + ".NS" for s in SYMS[a:a + 80]]
        for _ in range(3):
            try:
                d = yf.download(ch, period="60d", interval="5m", progress=False, group_by="column", auto_adjust=False, threads=True); break
            except Exception as e:  # noqa: BLE001
                print("retry", e, flush=True); time.sleep(20)
        for t in ch:
            try:
                x = d[list(out)].xs(t, axis=1, level=1).dropna(subset=["Close"])
            except Exception:  # noqa: BLE001
                continue
            if len(x) > 300:
                for k in out:
                    out[k][t[:-3]] = x[k]
        time.sleep(2)
    return {k: pd.DataFrame(v).sort_index() for k, v in out.items()}


def rsi(c, n=14):
    d = c.diff(); up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean(); dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def main():
    pct = P.pulse_table()
    D = dl5(); O, H, L, C, V = D["Open"], D["High"], D["Low"], D["Close"], D["Volume"].fillna(0)
    print("R| 5m bars", C.shape, C.index[0], C.index[-1], flush=True)
    ix = yf.download(["^NSEI", "^NSEBANK"], period="60d", interval="5m", progress=False, group_by="column", auto_adjust=False)["Close"].reindex(C.index).ffill()
    day = pd.Series([t.date() for t in C.index], index=C.index)
    # previous session close for every bar
    dclose = C.groupby(day.values).last(); prevc = dclose.shift(1); pc = prevc.reindex(day.values); pc.index = C.index
    ixd = ix.groupby(day.values).last().shift(1); ipc = ixd.reindex(day.values); ipc.index = C.index
    up_both = (ix > ipc).all(axis=1); dn_both = (ix < ipc).all(axis=1)
    green = (C > pc).astype(float).where(C.notna() & pc.notna())
    breadth = pd.DataFrame({k: green[[s for s in v if s in green.columns]].mean(axis=1) for k, v in IND.items()})
    R = rsi(C); m20 = C.rolling(20).mean(); sd = C.rolling(20).std(); ub, lb = m20 + 2 * sd, m20 - 2 * sd
    tp = (H + L + C) / 3; cv = (tp * V).groupby(day.values).cumsum(); vv = V.groupby(day.values).cumsum()
    cv.index = vv.index = C.index; vwap = cv / vv.replace(0, np.nan)
    e5 = C.ewm(span=5, adjust=False).mean()
    hm = pd.Series([t.hour * 100 + t.minute for t in C.index], index=C.index)
    ok_time = ((hm < 1100) | (hm >= 1430)) & (hm <= 1500) & (hm >= 920)
    bsig = (R > 60) & (R.shift(1) <= 60) & (C > ub) & (C > vwap)
    ssig = (R < 40) & (R.shift(1) >= 40) & (C < lb) & (C < vwap)
    bsig = bsig.mul(up_both & ok_time, axis=0); ssig = ssig.mul(dn_both & ok_time, axis=0)
    pdays = sorted(pct.index)
    trades = []
    idx = C.index
    for s in C.columns:
        ind = IND_OF.get(s)
        for side, sig in ((1, bsig[s]), (-1, ssig[s])):
            for t in sig.index[sig.values.astype(bool)]:
                i = idx.get_loc(t); d0 = t.date()
                trig = H.at[t, s] if side > 0 else L.at[t, s]; stop0 = L.at[t, s] if side > 0 else H.at[t, s]
                fill = None
                for j in range(i + 1, min(i + 4, len(idx))):
                    tj = idx[j]
                    if tj.date() != d0:
                        break
                    hj, lj, oj = H.at[tj, s], L.at[tj, s], O.at[tj, s]
                    if pd.isna(hj):
                        continue
                    if (side > 0 and lj < stop0) or (side < 0 and hj > stop0):
                        if not ((side > 0 and hj >= trig) or (side < 0 and lj <= trig)):
                            break
                    if (side > 0 and hj >= trig) or (side < 0 and lj <= trig):
                        fill = (j, max(trig, oj) if side > 0 else min(trig, oj)); break
                if not fill:
                    continue
                j, e = fill
                stop = min(stop0, e * 0.997) if side > 0 else max(stop0, e * 1.003)
                risk = abs(e - stop) / e
                px = None
                for k in range(j, len(idx)):
                    tk = idx[k]
                    if tk.date() != d0:
                        break
                    hk, lk, ok_, ck = H.at[tk, s], L.at[tk, s], O.at[tk, s], C.at[tk, s]
                    if pd.isna(ck):
                        continue
                    if (side > 0 and lk <= stop) or (side < 0 and hk >= stop):
                        px = (min(stop, ok_) if side > 0 else max(stop, ok_)) if k > j else stop; break
                    if hm.iloc[k] >= 1515 or (k > j and ((side > 0 and ck < e5.at[tk, s]) or (side < 0 and ck > e5.at[tk, s]))):
                        px = ck; break
                if px is None:
                    continue
                r_ = ((px / e - 1) * side - COST) / risk
                prev = [x for x in pdays if x < d0]
                pr = float(pct.loc[prev[-1]].get(ind, np.nan)) if prev and ind else np.nan
                br = float(breadth.at[t, ind]) if ind else np.nan
                trades.append(dict(day=d0, sym=s, side=side, R=r_, risk=risk, br=br, pulse=pr, hm=int(hm.iloc[i])))
    T = pd.DataFrame(trades)
    print("R| trades", len(T), flush=True)
    if T.empty:
        return

    def rep(name, x):
        if not len(x):
            print("R|", name, "n 0"); return
        cap = x.groupby("day").R.sum() * 0.25
        eq = cap.cumsum(); dd = (eq - eq.cummax()).min()
        print(f"R| {name}: trades {len(x)}, avg R {x.R.mean():+.3f}, win {np.mean(x.R > 0) * 100:.0f}%, total {x.R.sum():+.1f} R, "
              f"= {cap.sum():+.1f}% of capital at 0.25% a trade, max drawdown {dd:.1f}%, median stop {x.risk.median() * 100:.2f}%", flush=True)
    for nm, side in (("BUY + SELL", None), ("BUY", 1), ("SELL", -1)):
        X = T if side is None else T[T.side == side]
        agree_b = ((X.side > 0) & (X.br >= 0.6)) | ((X.side < 0) & (X.br <= 0.4))
        agree_p = ((X.side > 0) & (X.pulse >= 0.75)) | ((X.side < 0) & (X.pulse <= 0.25))
        against_p = ((X.side > 0) & (X.pulse <= 0.25)) | ((X.side < 0) & (X.pulse >= 0.75))
        rep(f"{nm} | option-bot rules on the stock", X)
        rep(f"{nm} | + industry breadth agrees", X[agree_b])
        rep(f"{nm} | + Pulse agrees (strong for buy, weak for sell)", X[agree_p])
        rep(f"{nm} | + breadth AND Pulse agree", X[agree_b & agree_p])
        rep(f"{nm} | Pulse AGAINST (control)", X[against_p])
        rep(f"{nm} | before 11:00 only", X[X.hm < 1100])
    half = sorted(T.day.unique()); mid = half[len(half) // 2]
    agree = (((T.side > 0) & (T.br >= 0.6)) | ((T.side < 0) & (T.br <= 0.4))) & (((T.side > 0) & (T.pulse >= 0.75)) | ((T.side < 0) & (T.pulse <= 0.25)))
    rep("first 30 days, breadth AND Pulse agree", T[agree & (T.day < mid)]); rep("last 30 days, breadth AND Pulse agree", T[agree & (T.day >= mid)])
    rep("first 30 days, all", T[T.day < mid]); rep("last 30 days, all", T[T.day >= mid])


if __name__ == "__main__":
    main()
