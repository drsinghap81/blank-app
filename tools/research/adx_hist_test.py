"""ADX (14,14) with the DI histogram - pilot on Nifty daily (25 Nov 2026, Amritpal: "check ADX with a histogram, default 14,14" ->
"do a pilot on daily chart on Nifty first").
Indicator (Wilder, as TradingView 'ADX and DI'): +DM/-DM, TR smoothed with RMA(14) -> +DI, -DI; DX = 100|+DI - -DI|/(+DI + -DI);
ADX = RMA(DX, 14). Histogram = +DI - -DI (green above 0).
Rules (signal at the daily close, fill at the next open, 0.05% round trip):
  L0  long when the histogram turns green; exit when it turns red                        (no ADX condition)
  L1  long when it turns green AND ADX > 20 and rising (vs 1 day ago); exit when red        (trend start)
  L2  as L1 but ADX > 25
  S1  short when it turns red AND ADX > 20 and rising; cover when it turns green            (mirror)
  F   9/21 on the index (EMA9 > EMA21 cross, exit cross down) all vs only when ADX > 20 and histogram green at the entry
Data: NIFTY 50 spot OHLC 2016-26 (data/scan/index_ohlcv.csv.gz) and Nifty near-month futures 2007-26 (data/futures/NIFTY.csv).
Newest-first years, bull/bear (index above/below its 200-day average at entry), ex-Covid, time in market, vs buy and hold."""
import numpy as np
import pandas as pd

COST = 0.0005


def adx(x, n=14, m=14):
    h, l, c = x.High, x.Low, x.Close
    up, dn = h.diff(), -l.diff()
    pdm = np.where((up > dn) & (up > 0), up, 0.0); mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    rma = lambda s, k: pd.Series(s, index=x.index).ewm(alpha=1 / k, adjust=False).mean()  # noqa: E731
    atr = rma(tr, n); pdi = 100 * rma(pdm, n) / atr; mdi = 100 * rma(mdm, n) / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return pdi, mdi, rma(dx.fillna(0), m)


def trades(x, enter, leave, side=1):
    o = x.Open.to_numpy(); D = x.index; n = len(o); out = []; j = 0
    en, lv = enter.to_numpy(), leave.to_numpy(); s200 = (x.Close > x.Close.rolling(200).mean()).to_numpy()
    while j < n - 1:
        if en[j]:
            e = j + 1; k = next((q + 1 for q in range(e, n - 1) if lv[q]), None)
            px = o[k] if k else x.Close.iloc[-1]
            out.append(dict(d=D[e], dx=D[k] if k else D[-1], r=side * (px / o[e] - 1) - COST, days=(k or n - 1) - e, bull=bool(s200[j]), open=k is None))
            j = k if k else n
        else:
            j += 1
    return pd.DataFrame(out)


def show(nm, T, x):
    if T.empty:
        print(f"R| {nm:52s} n 0", flush=True); return
    yrs = (x.index[-1] - x.index[0]).days / 365.25; eq = np.prod(1 + T.r); inm = T.days.sum() / len(x) * 100
    xc = T[~T.d.between("2020-02-15", "2020-12-31")]
    y = T.groupby(T.d.dt.year).r.agg(lambda s: (np.prod(1 + s) - 1) * 100)
    print(f"R| {nm:52s} n {len(T):3d} | win {(T.r > 0).mean() * 100:3.0f}% | avg {T.r.mean() * 100:+5.2f}% | hold {T.days.median():3.0f}d | "
          f"CAGR {(eq ** (1 / yrs) - 1) * 100:5.1f}% | in mkt {inm:3.0f}% | bull {T[T.bull].r.mean() * 100:+.2f}% bear {T[~T.bull].r.mean() * 100:+.2f}% | ex-Covid {xc.r.mean() * 100:+.2f}%", flush=True)
    print("R|    by year: " + " | ".join(f"{k}: {v:+.1f}%" for k, v in sorted(y.items(), reverse=True)[:11]), flush=True)


def run(lab, x):
    x = x.dropna(subset=["Open", "High", "Low", "Close"]); pdi, mdi, a = adx(x); hist = pdi - mdi
    g, r = (hist > 0) & (hist.shift() <= 0), (hist < 0) & (hist.shift() >= 0)
    rise = a > a.shift()
    e9, e21 = x.Close.ewm(span=9, adjust=False).mean(), x.Close.ewm(span=21, adjust=False).mean()
    up, dn = (e9 > e21) & (e9.shift() <= e21.shift()), (e9 < e21)
    yrs = (x.index[-1] - x.index[0]).days / 365.25
    print(f"R| ===== {lab} {x.index[0].date()} -> {x.index[-1].date()} | buy & hold CAGR {((x.Close.iloc[-1] / x.Close.iloc[0]) ** (1 / yrs) - 1) * 100:.1f}% | "
          f"now: +DI {pdi.iloc[-1]:.1f} -DI {mdi.iloc[-1]:.1f} hist {hist.iloc[-1]:+.1f} ADX {a.iloc[-1]:.1f} ({'rising' if rise.iloc[-1] else 'falling'}) =====", flush=True)
    show("L0 long: histogram turns green, exit red", trades(x, g, r), x)
    show("L1 long: green + ADX > 20 rising, exit red", trades(x, g & (a > 20) & rise, r), x)
    show("L2 long: green + ADX > 25 rising, exit red", trades(x, g & (a > 25) & rise, r), x)
    show("S1 short: red + ADX > 20 rising, cover green", trades(x, r & (a > 20) & rise, g, side=-1), x)
    # at a DI cross ADX is usually low and falling (it lags), so L1/L2 hardly fire; the common reading instead:
    c20, c25 = (a > 20) & (a.shift() <= 20), (a > 25) & (a.shift() <= 25)
    show("L3 long: ADX crosses above 20 while green, exit red", trades(x, c20 & (hist > 0), r), x)
    show("L4 long: ADX crosses above 25 while green, exit red", trades(x, c25 & (hist > 0), r), x)
    show("L5 long: ADX turns up (> 20) while green, exit red", trades(x, rise & ~rise.shift(fill_value=False) & (a > 20) & (hist > 0), r), x)
    show("S3 short: ADX crosses above 20 while red, cover green", trades(x, c20 & (hist < 0), g, side=-1), x)
    # 25 Nov 2026, Amritpal: "first histogram green and ADX rising" (no ADX level)
    both = (hist > 0) & rise
    show("G1 long: first green bar AND ADX rising that day", trades(x, g & rise, r), x)
    show("G2 long: first day green AND ADX rising together", trades(x, both & ~both.shift(fill_value=False), r), x)
    show("G3 G2, exit when ADX turns down", trades(x, both & ~both.shift(fill_value=False), (~rise) | (hist < 0)), x)
    show("G4 short: first red bar AND ADX rising (mirror)", trades(x, r & rise, g, side=-1), x)
    show("F  9/21 long, all", trades(x, up, dn), x)
    show("F  9/21 long, only if ADX > 20 and histogram green", trades(x, up & (a > 20) & (hist > 0), dn), x)
    L = pd.DataFrame({"pdi": pdi, "mdi": mdi, "adx": a}).round(1).tail(8)
    print("R| last 8 sessions: " + " | ".join(f"{d.date()} +DI {r.pdi} -DI {r.mdi} ADX {r.adx}" for d, r in L.iterrows()), flush=True)


d = pd.read_csv("data/scan/index_ohlcv.csv.gz", parse_dates=["Date"])
run("NIFTY 50 spot", d[d.INDEX == "NIFTY 50"].set_index("Date")[["Open", "High", "Low", "Close"]].astype(float).sort_index())
run("NIFTY futures", pd.read_csv("data/futures/NIFTY.csv", parse_dates=["Date"]).set_index("Date")[["Open", "High", "Low", "Close"]].astype(float))
