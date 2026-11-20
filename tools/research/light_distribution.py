"""Trade outcome distribution by the market traffic light (21 Nov 2026, Amritpal: "in all our systems like bottoms or 9/21, ATH,
how the distribution looks in green traffic light days and red").

Traffic light exactly as tools/research/red_light.py (all liquid NSE stocks, Yahoo 2015 -> today, survivors):
  breadth bad = last 10 sessions more EMA 9/21 cross-downs than cross-ups; index bad = Nifty's last weekly close < its 30-week SMA
  RED = both, AMBER = one, GREEN = neither. The light used is the one known when the trade is decided:
    9/21   : signal close (the session before the next-open entry)
    bottoms: breakout close (buy next open)
    ATH    : previous close before the intramonth trigger cross (or the month-close breakout's entry open)
Systems (live rules, every signal taken - no slot limit, so the distribution is not shaped by which trades fit):
  9/21    tools/research/concentrated_921.run with 150 slots at 0.5% risk (min position 0.5% of capital) (5-day-low stop, Supertrend exit)  + the live book
          (10 positions, 1% risk, 3-month strength) for reference
  bottoms tools/research/bottom_filters.events (double / tilted W / triple bottom / inverse H&S, neckline breakout,
          target = height or SL = close 4% (6% IHS) under the neckline, else 120 days), Nifty 500
  ATH     tools/ath_scan.analyse on full Yahoo history, base >= 24 months (main), weekly close < 30-week SMA exit; open trades
          valued at the last close
Per system x light: n, avg, median, win %, p10/p25/p75/p90, share >= +20%, share <= -10%, and share of signals vs share of days.
PILOT env = 150 stocks. Output: data/research/light_distribution.json"""
import json
import os
import sys
import time
from datetime import date

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trend_bt_global import load  # noqa: E402
import concentrated_921 as K  # noqa: E402
from signal_breadth import breadth  # noqa: E402
import bottom_filters as BF  # noqa: E402

PILOT = bool(os.environ.get("PILOT"))
LIGHTS = ("GREEN", "AMBER", "RED")


def light_series(d):
    B = breadth(d)
    nif = yf.download("^NSEI", start="2015-01-01", auto_adjust=True, progress=False)["Close"].squeeze().dropna()
    nif.index = pd.to_datetime(nif.index).tz_localize(None)
    w = nif.groupby(pd.Grouper(freq="W-FRI")).last().dropna(); below = (w < w.rolling(30).mean())
    B["idx_bad"] = below.reindex(B.index, method="ffill").shift(1).fillna(False).astype(bool)
    B["br_bad"] = B.W1.fillna(False).astype(bool)
    B["light"] = np.where(B.br_bad & B.idx_bad, "RED", np.where(B.br_bad | B.idx_bad, "AMBER", "GREEN"))
    B = B[B.index >= "2016-06-01"]
    return B.light


def at_close(L, dt):
    """light at the last close on or before dt"""
    i = L.index.searchsorted(pd.Timestamp(dt), side="right") - 1
    return L.iloc[i] if i >= 0 else None


def before(L, dt):
    """light at the last close strictly before dt"""
    i = L.index.searchsorted(pd.Timestamp(dt), side="left") - 1
    return L.iloc[i] if i >= 0 else None


def dist(r):
    r = np.asarray(r, float); r = r[np.isfinite(r)]
    if len(r) < 5:
        return dict(n=int(len(r)))
    q = np.percentile(r, [10, 25, 50, 75, 90])
    return dict(n=int(len(r)), avg=round(float(r.mean()), 2), med=round(float(q[2]), 2), win=round(float((r > 0).mean() * 100), 1),
                p10=round(float(q[0]), 1), p25=round(float(q[1]), 1), p75=round(float(q[3]), 1), p90=round(float(q[4]), 1),
                big_win=round(float((r >= 20).mean() * 100), 1), big_loss=round(float((r <= -10).mean() * 100), 1))


def report(name, T, L, res):
    """T: DataFrame with columns ret (%), light, d (decision date)"""
    T = T[T.light.isin(LIGHTS)]
    days = {k: float((L == k).mean() * 100) for k in LIGHTS}
    out = {"all": dist(T.ret)}
    for k in LIGHTS:
        x = T[T.light == k]
        out[k] = dist(x.ret); out[k]["share_signals"] = round(len(x) / max(1, len(T)) * 100, 1); out[k]["share_days"] = round(days[k], 1)
    # newest-first windows and ex-Covid
    T = T.assign(d=pd.to_datetime(T.d))
    end = T.d.max()
    for y in (1, 2, 3, 5):
        x = T[T.d > end - pd.DateOffset(years=y)]
        out[f"last {y}y"] = {k: dist(x[x.light == k].ret) for k in LIGHTS}
    xc = T[~((T.d >= "2020-02-15") & (T.d <= "2020-12-31"))]
    out["ex-Covid"] = {k: dist(xc[xc.light == k].ret) for k in LIGHTS}
    res[name] = out
    for k in ("all",) + LIGHTS:
        print(f"R| {name} | {k}: {out[k]}", flush=True)
    for w in ("last 1y", "last 2y", "last 3y", "last 5y", "ex-Covid"):
        print(f"R| {name} | {w}: " + "; ".join(f"{k} n{out[w][k].get('n')} avg {out[w][k].get('avg')} med {out[w][k].get('med')} win {out[w][k].get('win')}" for k in LIGHTS), flush=True)


def main():
    res = dict(method=__doc__)
    d, u = load("NSE")
    if PILOT:
        keep = sorted(d.SYMBOL.unique())[:150]; d = d[d.SYMBOL.isin(keep)]
    d = d.sort_values(["SYMBOL", "Date"])
    g = d.groupby("SYMBOL").CLOSE
    d["r63"] = g.transform(lambda s: s / s.shift(63) - 1)
    L = light_series(d)
    res["days"] = {k: round(float((L == k).mean() * 100), 1) for k in LIGHTS}
    print("R| panel", d.SYMBOL.nunique(), "stocks; days", res["days"], "from", L.index[0].date(), "to", L.index[-1].date(), flush=True)

    # ---- 9/21: every signal (400 slots), then the live book
    for nm, args in (("9/21 every signal (150 slots)", (150, 0.005, "random", 0)), ("9/21 live book (10 pos, strength)", (10, 0.01, "r63", 0))):
        _, T = K.run(d, *args)
        T = T.assign(ret=T.ret * 100, d=pd.to_datetime(T.entry), light=[before(L, e) for e in T.entry])
        report(nm, T, L, res)

    # ---- bottoms (Nifty 500 list, as the live pattern scan)
    syms = pd.read_csv("data/universe/nifty500.csv").Symbol.tolist()
    if PILOT:
        syms = syms[:60]
    ev = []
    for a in range(0, len(syms), 60):
        b = [s + ".NS" for s in syms[a:a + 60]]
        D = yf.download(b, start="2015-01-01", auto_adjust=True, progress=False, group_by="ticker", threads=True)
        for t in b:
            try:
                x = D[t].dropna(subset=["Close"])
            except Exception:  # noqa: BLE001
                continue
            ev += BF.events(t[:-3], x)
        time.sleep(2)
    E = pd.DataFrame(ev)
    if len(E):
        E = E[E.d >= "2016-06-01"]
        E = E.assign(ret=E.classic, light=[at_close(L, x) for x in E.d])
        report("bottoms (all patterns)", E, L, res)
        f = E[E.above50 & E.rsi60]
        report("bottoms above 50-day & RSI > 60", f, L, res)

    # ---- ATH (full history)
    import ath_scan as A
    tick = list(u.ticker)
    if PILOT:
        tick = [t for t in tick if t.replace(".NS", "").replace(".BO", "") in set(d.SYMBOL.str.replace(r"\.(NS|BO)$", "", regex=True))][:150] or tick[:150]
    today = date.today(); evs = []
    for a in range(0, len(tick), 80):
        chunk = tick[a:a + 80]; dd = None
        for _ in range(3):
            try:
                dd = yf.download(chunk, period="max", interval="1d", auto_adjust=False, progress=False, group_by="column", threads=True); break
            except Exception as e:  # noqa: BLE001
                print("retry", a, e, flush=True); time.sleep(20)
        if dd is None or dd.empty:
            continue
        for t in chunk:
            try:
                x = pd.DataFrame({k: dd[k][t] for k in ("Open", "High", "Low", "Close", "Volume")}).dropna(subset=["Close"])
                if len(x) < 300 or float(x.Close.iloc[-1]) < A.MIN_CLOSE:
                    continue
                e_, _, _ = A.analyse(t, x, today, lookback_days=0)
                evs += [dict(sym=t, d=r["date"], ret=r["ret"] * 100, main=r["main"], status=r["status"]) for r in e_]
            except Exception as ex:  # noqa: BLE001
                print("ath skip", t, str(ex)[:80], flush=True)
        print("ath", a + len(chunk), "events", len(evs), flush=True)
        time.sleep(2)
    AE = pd.DataFrame(evs)
    if len(AE):
        AE = AE[(AE.d >= "2016-06-01") & AE.main]
        AE = AE.assign(light=[before(L, x) for x in AE.d])
        print("R| ATH open trades valued at last close:", int((AE.status != "exited").sum()), "of", len(AE), flush=True)
        report("ATH monthly (base 24m+)", AE, L, res)
        report("ATH monthly, closed trades only", AE[AE.status == "exited"], L, res)

    if not PILOT:
        os.makedirs("data/research", exist_ok=True)
        json.dump(res, open("data/research/light_distribution.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
