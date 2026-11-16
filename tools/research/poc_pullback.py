"""Volume-profile POC pullback (from a social-media setup, 16 Nov 2026) on Nifty 500 stocks, 2016 - Nov 2026.

Impulse: a pivot swing low (5 bars each side) followed within 60 trading days by a swing high >= 20% above it, with no
lower low in between. "Sweep start": that swing low took out the lowest low of the 25 days before it (stop hunt) and the
close got back above that old low within 2 days.
Volume profile of the impulse (swing low -> swing high): each day's volume spread evenly over its high-low range, 40 price
bins; POC = the bin with the most volume.
A  first touch: after the high, the first day whose low reaches the POC (no new high first, within 60 days). Buy at the POC
   (or the open if it gaps below). Stop POC - 1.5 ATR(14), target the swing high, out after 60 days.
B  sweep + reclaim: after the first touch, within 20 days, a day that trades 0.5 ATR or more below the POC and closes back
   above it. Buy at that close, stop 0.2 ATR under that day's low, target the swing high, out after 60 days.
   Cancelled if a close falls 3 ATR below the POC first.
Stops/targets checked on daily high/low (stop first if both). Costs 0.3% round trip. Liquid only: median 60-day traded
value >= Rs 5 cr and price >= 50. Current Nifty 500 members (survivorship bias flatters results).
Portfolio: Rs 20 L, risk 1% per trade to the stop, max 10% a stock, max 10 open, realised equity.
Output: data/research/poc_pullback.json."""
import json
import math
import os

import numpy as np
import pandas as pd
import yfinance as yf

START, END = "2015-06-01", None
K, MIN_UP, MAX_LEN, BINS = 5, 0.20, 60, 40
COST = 0.003


def atr(h, l, c, n=14):
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    return pd.Series(tr).rolling(n).mean().values


def poc_of(h, l, v, i, j):
    lo, hi = l[i], h[j]
    if hi <= lo:
        return None
    edges = np.linspace(lo, hi, BINS + 1); vol = np.zeros(BINS)
    for d in range(i, j + 1):
        a, b = max(l[d], lo), min(h[d], hi)
        if b <= a or not v[d] > 0:
            continue
        ia, ib = np.searchsorted(edges, a, "right") - 1, np.searchsorted(edges, b, "left")
        ia, ib = max(ia, 0), min(max(ib, ia + 1), BINS)
        vol[ia:ib] += v[d] / (ib - ia)
    k = int(vol.argmax())
    return (edges[k] + edges[k + 1]) / 2


def run_exit(h, l, c, o, t0, entry, stop, tgt, same_day):
    """Walk from t0 (entry day; same_day=True means the entry day's range can hit stop/target after entry)."""
    n = len(c)
    for d in range(t0 if same_day else t0 + 1, min(t0 + 61, n)):
        if l[d] <= stop:
            return d, min(stop, o[d]) if d > t0 else stop, "stop"
        if h[d] >= tgt:
            return d, max(tgt, o[d]) if d > t0 else tgt, "target"
    d = min(t0 + 60, n - 1)
    return d, c[d], "time"


def scan(sym, df):
    o, h, l, c, v = (df[k].values.astype(float) for k in ("Open", "High", "Low", "Close", "Volume"))
    dates = df.index; n = len(c); A = atr(h, l, c)
    val = pd.Series(c * v).rolling(60).median().values
    piv_lo = [i for i in range(K, n - K) if l[i] == l[i - K:i + K + 1].min()]
    piv_hi = set(j for j in range(K, n - K) if h[j] == h[j - K:j + K + 1].max())
    out = []; busy = -1
    for i in piv_lo:
        if i <= busy or i < 30:
            continue
        j = next((j for j in range(i + 1, min(i + MAX_LEN, n - K)) if j in piv_hi and h[j] / l[i] - 1 >= MIN_UP), None)
        if j is None or l[i:j + 1].min() < l[i]:
            continue
        prior = l[i - 25:i - 3].min()
        sweep = l[i] < prior and c[i:i + 3].max() > prior
        P = poc_of(h, l, v, i, j)
        if P is None or not np.isfinite(A[j]):
            continue
        # pullback: first touch of the POC before a new high, within 60 days
        t = None
        for d in range(j + 1, min(j + 61, n)):
            if h[d] > h[j]:
                break
            if l[d] <= P:
                t = d; break
        if t is None or not (val[t] >= 5e7 and c[t] >= 50):
            continue
        a = A[t - 1]
        # A: first touch
        eA = o[t] if o[t] < P else P; sA = P - 1.5 * a
        if eA > sA:
            dA, xA, wA = run_exit(h, l, c, o, t, eA, sA, h[j], True)
            out.append(dict(sym=sym, ver="A", sweep=bool(sweep), entry_d=str(dates[t].date()), exit_d=str(dates[dA].date()),
                            entry=eA, stop=sA, target=h[j], exit=xA, why=wA, up=h[j] / l[i] - 1))
        # B: sweep below the POC and reclaim
        for d in range(t, min(t + 21, n)):
            if c[d] < P - 3 * a or h[d] > h[j]:
                break
            if l[d] <= P - 0.5 * a and c[d] > P:
                sB = l[d] - 0.2 * a; eB = c[d]
                dB, xB, wB = run_exit(h, l, c, o, d, eB, sB, h[j], False)
                out.append(dict(sym=sym, ver="B", sweep=bool(sweep), entry_d=str(dates[d].date()), exit_d=str(dates[dB].date()),
                                entry=eB, stop=sB, target=h[j], exit=xB, why=wB, up=h[j] / l[i] - 1))
                break
        busy = t + 60
    return out


def stats(T):
    if not len(T):
        return {}
    r = T.exit / T.entry - 1 - COST; R = (T.exit - T.entry) / (T.entry - T.stop) - COST * T.entry / (T.entry - T.stop)
    return dict(n=len(T), per_yr=round(len(T) / 10.4, 1), win=round((r > 0).mean() * 100, 1), avg_ret=round(r.mean() * 100, 2),
                avg_R=round(R.mean(), 2), t=round(r.mean() / (r.std() / math.sqrt(len(r))), 2) if len(r) > 2 else None,
                target_hit=round((T.why == "target").mean() * 100, 1), stop_hit=round((T.why == "stop").mean() * 100, 1),
                pos_years=f"{int((T.assign(r=r).groupby(T.entry_d.str[:4]).r.sum() > 0).sum())}/{T.entry_d.str[:4].nunique()}")


def portfolio(T, cap=2e6):
    T = T.sort_values("entry_d"); eq = cap; open_ = []; curve = []
    for _, x in T.iterrows():
        open_ = [p for p in open_ if p["exit_d"] > x.entry_d] if open_ else []
        if len(open_) >= 10:
            continue
        risk = x.entry - x.stop
        q = min(0.01 * eq / risk, 0.10 * eq / x.entry)
        pnl = q * (x.exit - x.entry) - COST * q * x.entry
        eq += pnl; open_.append(dict(exit_d=x.exit_d)); curve.append((x.exit_d, eq))
    if not curve:
        return {}
    s = pd.Series([e for _, e in curve], index=pd.to_datetime([d for d, _ in curve])).sort_index()
    yrs = (s.index[-1] - pd.Timestamp("2016-01-01")).days / 365.25
    return dict(cagr=round(((s.iloc[-1] / cap) ** (1 / yrs) - 1) * 100, 1), max_dd=round((s / s.cummax() - 1).min() * 100, 1), trades=len(curve))


def main():
    syms = pd.read_csv("data/universe/nifty500.csv").Symbol.tolist()
    res = []
    for k in range(0, len(syms), 50):
        batch = [s + ".NS" for s in syms[k:k + 50]]
        D = yf.download(batch, start=START, interval="1d", auto_adjust=False, group_by="ticker", progress=False, threads=True)
        for s in batch:
            try:
                df = D[s].dropna(subset=["Close"])
            except Exception:  # noqa: BLE001
                continue
            if len(df) < 300:
                continue
            res += scan(s[:-3], df)
        print("done", k + 50, len(res), flush=True)
    T = pd.DataFrame(res); T = T[T.entry_d >= "2016-01-01"]
    nifty = yf.download("^NSEI", start="2016-01-01", auto_adjust=False, progress=False)
    if hasattr(nifty.columns, "levels"):
        nifty.columns = nifty.columns.get_level_values(0)
    nc = nifty.Close.dropna(); yrs = (nc.index[-1] - nc.index[0]).days / 365.25
    bench = dict(cagr=round(((nc.iloc[-1] / nc.iloc[0]) ** (1 / yrs) - 1) * 100, 1), max_dd=round((nc / nc.cummax() - 1).min() * 100, 1))
    out = dict(method=__doc__, nifty_buy_hold=bench, versions={})
    for ver in ("A", "B"):
        for sw in (False, True):
            X = T[(T.ver == ver) & (T.sweep if sw else True)]
            key = f"{ver} {'sweep-start only' if sw else 'all impulses'}"
            out["versions"][key] = dict(trades=stats(X), portfolio=portfolio(X))
            print(key, out["versions"][key], flush=True)
    print("Nifty buy & hold", bench)
    os.makedirs("data/research", exist_ok=True)
    json.dump(out, open("data/research/poc_pullback.json", "w"), indent=1)
    T.to_csv("data/research/poc_pullback_trades.csv.gz", index=False)


if __name__ == "__main__":
    main()
