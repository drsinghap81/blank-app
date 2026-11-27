"""Option trader's 5-minute signal on Bitcoin and Ether (27 Nov 2026, Amritpal: "check option trader also on these" -> test on BTC / ETH).
The live option trader (tools/live_server/opt_trader.py, backtest opt_bt.py) reads RSI(14) crossing 60 on the OPTION's own 5-minute
bars, the option above its session VWAP and the other side below it. Crypto option history isn't available, so the same signal is
read on the coin itself (as on a futures contract):
  LONG  : RSI(14) crosses above 60 on a 5-min close, close above the UTC-day VWAP  (+ variant: also above the upper Bollinger band 20/2)
  SHORT : RSI crosses below 40, close below VWAP (+ below the lower band)          (a call buy / a put buy)
  entry : stop order beyond the signal candle (high for long, low for short) on the next 3 candles, cancelled if the other end breaks
  stop  : the signal candle's other end;  exit (the live rule since 27 Nov): half off at +1R, rest's stop to entry, rest out on a
          5-min close back through the 5 EMA; anything open is closed at the end of the UTC day (the trader is intraday).
Results in R (risk = entry-to-stop). Cost: 0.1% of price a round trip (futures taker fees + slippage), shown as R lost.
Data: Binance public 5-minute klines (data.binance.vision monthly / daily files), BTCUSDT / ETHUSDT, last 24 months. Newest first."""
import io
import os
import urllib.request
import zipfile
from datetime import date, timedelta

import numpy as np
import pandas as pd

COST = 0.001
MONTHS = 24


def load(sym):
    frames = []
    today = date.today(); m0 = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    months = []
    d = m0
    for _ in range(MONTHS):
        months.append(d); d = (d - timedelta(days=1)).replace(day=1)
    urls = [f"https://data.binance.vision/data/spot/monthly/klines/{sym}/5m/{sym}-5m-{m:%Y-%m}.zip" for m in months[::-1]]
    d = today.replace(day=1)
    while d < today:
        urls.append(f"https://data.binance.vision/data/spot/daily/klines/{sym}/5m/{sym}-5m-{d:%Y-%m-%d}.zip"); d += timedelta(days=1)
    for u in urls:
        try:
            raw = urllib.request.urlopen(u, timeout=60).read()
            z = zipfile.ZipFile(io.BytesIO(raw)); f = z.open(z.namelist()[0])
            x = pd.read_csv(f, header=None, usecols=[0, 1, 2, 3, 4, 5])
            frames.append(x)
        except Exception as ex:  # noqa: BLE001
            print(f"R| skip {u.rsplit('/', 1)[-1]} ({str(ex)[:40]})", flush=True)
    x = pd.concat(frames); x.columns = ["t", "o", "h", "l", "c", "v"]
    t = x.t.astype("int64"); t = np.where(t > 1e14, t // 1000, t)            # Binance switched to microseconds in 2025
    x.index = pd.to_datetime(t, unit="ms"); x = x.drop(columns="t").astype(float)
    return x[~x.index.duplicated()].sort_index()


def rsi(c, n=14):
    d = np.diff(c, prepend=c[0]); up = np.where(d > 0, d, 0.0); dn = np.where(d < 0, -d, 0.0)
    au = pd.Series(up).ewm(alpha=1 / n, adjust=False).mean().to_numpy(); ad = pd.Series(dn).ewm(alpha=1 / n, adjust=False).mean().to_numpy()
    return 100 - 100 / (1 + au / np.maximum(ad, 1e-12))


def trades(x):
    o, h, l, c, v = (x[k].to_numpy() for k in ("o", "h", "l", "c", "v"))
    day = x.index.normalize(); n = len(c)
    tp = (h + l + c) / 3; g = pd.Series(tp * v).groupby(day).cumsum().to_numpy(); gv = pd.Series(v).groupby(day).cumsum().to_numpy()
    vw = g / np.maximum(gv, 1e-12)
    m = pd.Series(c).rolling(20).mean().to_numpy(); sd = pd.Series(c).rolling(20).std(ddof=0).to_numpy()
    bu, bl = m + 2 * sd, m - 2 * sd
    em5 = pd.Series(c).ewm(span=5, adjust=False).mean().to_numpy(); r = rsi(c)
    dayi = day.to_numpy(); last_of_day = np.r_[dayi[1:] != dayi[:-1], True]
    end_idx = np.zeros(n, dtype=int); j = n - 1
    for i in range(n - 1, -1, -1):
        if last_of_day[i]:
            j = i
        end_idx[i] = j
    out = []
    busy_until = -1
    for i in range(30, n - 1):
        if i <= busy_until:
            continue
        for side in (1, -1):
            if side > 0:
                sig = r[i - 1] <= 60 < r[i] and c[i] > vw[i]
            else:
                sig = r[i - 1] >= 40 > r[i] and c[i] < vw[i]
            if not sig:
                continue
            bb = bool(c[i] > bu[i]) if side > 0 else bool(c[i] < bl[i])
            last = end_idx[i]
            trig, opp = (h[i], l[i]) if side > 0 else (l[i], h[i])
            e = f = None
            for k in range(i + 1, min(last, i + 3) + 1):
                hit = (side > 0 and h[k] > trig) or (side < 0 and l[k] < trig)
                brk = (side > 0 and l[k] < opp) or (side < 0 and h[k] > opp)
                if brk and not hit:
                    break
                if hit:          # a candle touching BOTH: counted as filled and then stopped (the order may fill first) - conservative
                    e = max(trig, o[k]) if side > 0 else min(trig, o[k]); f = k; break
            if e is None:
                continue
            risk = abs(e - opp)
            if risk <= e * 0.0005:
                continue
            sl = opp; half = None; px = None; how = "close"
            adv = (lambda k: l[k] <= sl) if side > 0 else (lambda k: h[k] >= sl)
            if adv(f):
                px, how = sl, "SL"; xk = f
            else:
                xk = last
                for k in range(f + 1, last + 1):
                    st = e if half is not None else sl
                    if (side > 0 and l[k] <= st) or (side < 0 and h[k] >= st):
                        px = (min(o[k], st) if side > 0 else max(o[k], st)); how = "stop"; xk = k; break
                    if half is None and ((side > 0 and h[k] >= e + risk) or (side < 0 and l[k] <= e - risk)):
                        half = max(o[k], e + risk) if side > 0 else min(o[k], e - risk)
                    if (side > 0 and c[k] < em5[k]) or (side < 0 and c[k] > em5[k]):
                        px = c[k]; how = "5ema"; xk = k; break
                if px is None:
                    px = c[last]
            blend = (half + px) / 2 if half is not None else px
            R = side * (blend - e) / risk
            out.append(dict(t=x.index[i], side=side, e=e, f=f, risk=risk, last=last, bb=bb, R=R, Rnet=R - COST * e / risk, risk_pct=risk / e * 100, how=how))
            busy_until = xk
            break
    return pd.DataFrame(out)


def row(T, lab):
    if not len(T):
        return f"{lab:34s} n 0"
    g, b = T.Rnet[T.Rnet > 0].sum(), -T.Rnet[T.Rnet < 0].sum()
    days = max(1, (T.t.max() - T.t.min()).days)
    return (f"{lab:34s} n {len(T):5d} ({len(T) / days:4.1f}/day) win {(T.R > 0).mean() * 100:3.0f}% | gross {T.R.mean():+.3f}R | "
            f"net {T.Rnet.mean():+.3f}R PF {g / b if b else 9:.2f} | risk {T.risk_pct.median():.2f}% of price")


def main():
    for sym in ("BTCUSDT", "ETHUSDT"):
        x = load(sym)
        print(f"R| == {sym} 5-min {x.index[0]} -> {x.index[-1]} ({len(x):,} bars)", flush=True)
        T = trades(x)
        if not len(T):
            print("R| no trades", flush=True); continue
        end = T.t.max()
        for lab, mo in (("last 1 month", 1), ("last 3 months", 3), ("last 6 months", 6), ("last 12 months", 12), ("last 24 months", 24)):
            Z = T[T.t >= end - pd.DateOffset(months=mo)]
            print(f"R| {sym} {lab:15s} all   | " + row(Z, ""), flush=True)
            print(f"R| {sym} {lab:15s} +BB   | " + row(Z[Z.bb], ""), flush=True)
        Z = T[T.t >= end - pd.DateOffset(months=12)]
        for s, nm in ((1, "long (call)"), (-1, "short (put)")):
            print(f"R| {sym} 12m {nm:12s}       | " + row(Z[Z.side == s], ""), flush=True)
        for a, b_, nm in ((0, 8, "00-08 UTC Asia"), (8, 13, "08-13 UTC Europe"), (13, 21, "13-21 UTC US"), (21, 24, "21-24 UTC late")):
            Zh = Z[(Z.t.dt.hour >= a) & (Z.t.dt.hour < b_)]
            print(f"R| {sym} 12m {nm:16s}   | " + row(Zh, ""), flush=True)
        for lo_, hi_ in ((0, 0.2), (0.2, 0.4), (0.4, 99)):
            Zr = Z[(Z.risk_pct >= lo_) & (Z.risk_pct < hi_)]
            print(f"R| {sym} 12m risk {lo_:.1f}-{hi_:.1f}% of price | " + row(Zr, ""), flush=True)


if __name__ == "__main__":
    main()
