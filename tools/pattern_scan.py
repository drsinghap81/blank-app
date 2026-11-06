"""Bottom-pattern scanner (NSE): double bottom, tilted W, triple bottom, inverse head & shoulders - after a fall.
Independent of the ATH system. WATCH-ONLY: the 2016-26 backtest found no edge over random entries (see the app note).

Rules (same as the backtest, scratchpad bottoms/find.py):
  swings  : zigzag on daily CLOSES, 6% threshold (a low/peak is known once price moved 6% away from it)
  fall    : 250-day high close >= 20% above the first low; first low within 5% of the 250-day low
  DB  second low within +-3% of the first      TW  second low 3-12% higher (tilted W)
  TB  three lows within 4% of their mean        IHS head >= 3% below both shoulders, shoulders within 6%
  neckline = highest peak between the lows; breakout = first close above it within 60 days of the last low
Status: 'breakout' (closed above the neckline in the last 10 sessions) or 'forming' (last low confirmed, close between
the last low and the neckline). Liquid stocks only (20-day traded value >= Rs 2 cr), close >= Rs 100.
Output: data/scan/patterns.json and data/scan/pattern_charts/SYM.json (daily bars, last 320 sessions)."""
import json
import os
import sys
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trend_scan import nse_symbols  # noqa: E402

OUT = "data/scan"; CH = f"{OUT}/pattern_charts"
THR, FALL, MINVAL, MIN_CLOSE, RECENT = 0.06, 0.20, 2e7, 100.0, 10
INDICES = {"^NSEI": "NIFTY 50", "^NSEBANK": "NIFTY BANK", "^CNXIT": "NIFTY IT", "^CNXAUTO": "NIFTY AUTO", "^CNXPHARMA": "NIFTY PHARMA",
           "^CNXMETAL": "NIFTY METAL", "^CNXFMCG": "NIFTY FMCG", "^CNXREALTY": "NIFTY REALTY", "^CNXENERGY": "NIFTY ENERGY",
           "NIFTY_FIN_SERVICE.NS": "NIFTY FIN SERVICE", "^NSEMDCP50": "NIFTY MIDCAP 50"}


def zigzag(c, thr):
    """pivots (kind, index, price, confirm_index) on closes."""
    piv = []; hi = lo = c[0]; hi_i = lo_i = 0; mode = 0
    for i in range(1, len(c)):
        x = c[i]
        if mode >= 0 and x > hi: hi, hi_i = x, i
        if mode <= 0 and x < lo: lo, lo_i = x, i
        if mode >= 0 and x <= hi * (1 - thr) and (mode == 1 or hi_i > 0):
            piv.append(("H", hi_i, hi, i)); mode = -1; lo, lo_i = x, i
        elif mode <= 0 and x >= lo * (1 + thr):
            piv.append(("L", lo_i, lo, i)); mode = 1; hi, hi_i = x, i
    return piv


def patterns_at(piv, k):
    """pattern candidates whose last low is pivot k."""
    out = []
    if k >= 2 and piv[k - 1][0] == "H" and piv[k - 2][0] == "L":
        L1, P1, L2 = piv[k - 2], piv[k - 1], piv[k]; r = L2[2] / L1[2] - 1
        typ = "DB" if -0.03 <= r <= 0.03 else ("TW" if 0.03 < r <= 0.12 else None)
        if typ:
            out.append((typ, [L1, L2], [P1], P1[2]))
    if k >= 4 and [x[0] for x in piv[k - 4:k + 1]] == ["L", "H", "L", "H", "L"]:
        L1, P1, M, P2, L3 = piv[k - 4:k + 1]; lows = np.array([L1[2], M[2], L3[2]]); neck = max(P1[2], P2[2])
        if (np.abs(lows / lows.mean() - 1) <= 0.04).all():
            out.append(("TB", [L1, M, L3], [P1, P2], neck))
        elif M[2] < 0.97 * min(L1[2], L3[2]) and abs(L3[2] / L1[2] - 1) <= 0.06:
            out.append(("IHS", [L1, M, L3], [P1, P2], neck))
    return out


def scan(x, sym, name, kind="stock"):
    """latest pattern state for one series (DataFrame Open/High/Low/Close/Volume) or None."""
    c = x.Close.to_numpy(float); lw = x.Low.to_numpy(float); n = len(c); dts = x.index
    if n < 150:
        return None
    piv = zigzag(c, THR)
    rmax = pd.Series(c).rolling(250, min_periods=120).max().shift(1).to_numpy()
    rmin = pd.Series(c).rolling(250, min_periods=120).min().to_numpy()
    best = None
    for k in range(len(piv) - 1, max(-1, len(piv) - 4), -1):           # the latest few lows only
        if piv[k][0] != "L":
            continue
        for typ, lows, peaks, neck in patterns_at(piv, k):
            first = lows[0]; i1 = first[1]
            if np.isnan(rmax[i1]) or rmax[i1] < first[2] * (1 + FALL) or first[2] > rmin[i1] * 1.05:
                continue
            last = lows[-1]; sig = None; broke = False
            for j in range(last[3], min(n, last[1] + 60)):
                if c[j] < last[2]:
                    broke = True; break
                if c[j] > neck:
                    sig = j; break
            if broke:
                continue
            if sig is not None:
                if n - 1 - sig >= RECENT:
                    continue
                status = "breakout"
            else:
                if n - 1 > last[1] + 60 or c[-1] < last[2] or neck / c[-1] - 1 > 0.20:
                    continue
                status = "forming"
            plow = float(min(lw[l_[1]] for l_ in lows))
            rv = rsi(c); li = [l_[1] for l_ in lows]; dv = divergence(c, rv, li)
            row = dict(symbol=sym, name=name, kind=kind, typ=typ, status=status, close=float(c[-1]), neck=float(neck),
                       to_neck_pct=float((neck / c[-1] - 1) * 100), stop=round(plow * 0.99, 2), stop_pct=float((1 - plow * 0.99 / c[-1]) * 100),
                       height_pct=float((neck / min(l_[2] for l_ in lows) - 1) * 100), fall_pct=float((rmax[i1] / first[2] - 1) * 100),
                       lows=[[str(dts[l_[1]].date()), float(l_[2])] for l_ in lows], peaks=[[str(dts[p_[1]].date()), float(p_[2])] for p_ in peaks],
                       rsi_lows=[round(float(rv[i_]), 1) for i_ in li], rsi_div=round(dv, 1), rsi_now=round(float(rv[-1]), 1),
                       signal_date=str(dts[sig].date()) if sig is not None else None,
                       days_since=int(n - 1 - sig) if sig is not None else None)
            if best is None or (row["status"] == "breakout") > (best["status"] == "breakout"):
                best = row
        if best:
            break
    return best


def sq9_levels(price, span=3):
    """Gann Square-of-9 odd squares (1, 9, 25, 49, 81, 121 ...) around a price, e.g. Rs 50 -> 49 (7^2) below, 81 (9^2) above."""
    r0 = int(np.sqrt(price)); r0 -= (r0 % 2 == 0)
    return [(o * o, f"{o}\u00b2") for o in range(max(1, r0 - 2 * span), r0 + 2 * span + 1, 2)]


def support(x, sym, name):
    """Uptrend stock at (or within 5% above) an old swing level it has not revisited since moving 8%+ away from it.
    Backtest 2016-26 (scratchpad srt/): breakout retests +0.20R vs +0.09R random (1-ATR stop, 3R target); old swing lows none;
    1:3 room and Gann confluence added nothing."""
    c = x.Close.to_numpy(float); h = x.High.to_numpy(float); l = x.Low.to_numpy(float); n = len(c); dts = x.index
    if n < 260:
        return None
    s50 = pd.Series(c).rolling(50).mean().to_numpy(); s200 = pd.Series(c).rolling(200).mean().to_numpy()
    if not (c[-1] > s50[-1] > s200[-1] and s200[-1] > s200[-21]):
        return None
    tr = np.maximum(h - l, np.maximum(abs(h - np.roll(c, 1)), abs(l - np.roll(c, 1)))); atr = pd.Series(tr).rolling(14).mean().to_numpy()
    piv = zigzag(c, THR); lv = []; pi = 0; touch = None
    for t in range(n):
        while pi < len(piv) and piv[pi][3] <= t:
            k_, i_, pr, ci = piv[pi]; lv.append(dict(p=pr, kind=k_, i=i_, armed=False, used=False)); pi += 1
        for L in lv:
            if L["used"] or t - L["i"] > 750:
                continue
            if not L["armed"]:
                L["armed"] = c[t] >= L["p"] * 1.08
                continue
            if l[t] <= L["p"] * 1.03 and c[t] >= L["p"]:
                L["used"] = True
                if t >= n - 5 and c[-1] <= L["p"] * 1.08 and (touch is None or L["p"] > touch[0]["p"] or t > touch[1]):
                    touch = (L, t)
            elif c[t] < L["p"] * 0.98:
                L["used"] = True
    if touch:
        L, t = touch; status = "touched"
    else:
        near = [L for L in lv if L["armed"] and not L["used"] and n - 1 - L["i"] <= 750 and L["p"] <= c[-1] <= L["p"] * 1.05]
        if not near:
            return None
        L = max(near, key=lambda z: z["p"]); t = n - 1; status = "near"
    lvl = float(L["p"]); stop = lvl - float(atr[-1]); E = float(c[-1])
    res = [q[2] for q in piv if q[0] == "H" and n - 1 - q[1] <= 750 and q[2] > E * 1.01]
    rh = float(h[-61:].max())
    if rh > E * 1.01:
        res.append(rh)
    nr = float(min(res)) if res else None
    W = sq9_levels(lvl); g = min(W, key=lambda z: abs(lvl / z[0] - 1))
    gap = float(((int(np.sqrt(g[0])) + 2) ** 2 / g[0] - 1) * 100)
    up = [z for z in sq9_levels(E) if z[0] > E][:1]; dn = [z for z in W if z[0] < min(lvl, g[0])][-1:]
    return dict(symbol=sym, name=name, status=status, touch_date=str(dts[t].date()) if status == "touched" else None,
                days_ago=int(n - 1 - t) if status == "touched" else None, level=round(lvl, 2),
                level_kind="breakout retest" if L["kind"] == "H" else "old swing low", level_date=str(dts[L["i"]].date()),
                close=E, above_pct=float((E / lvl - 1) * 100), stop=round(stop, 2), risk_pct=float((1 - stop / E) * 100),
                resistance=round(nr, 2) if nr else None, room_r=float((nr - E) / (E - stop)) if nr and E > stop else None,
                sq9=g[0], sq9_cross=g[1], sq9_dist_pct=float((lvl / g[0] - 1) * 100), sq9_gap_pct=gap,
                sq9_below=[[z[0], z[1]] for z in dn], sq9_above=[[z[0], z[1]] for z in up],
                sq9_match=bool(abs(lvl / g[0] - 1) <= 0.01))


def rsi(c, n=14):
    """Wilder RSI on closes."""
    c = np.asarray(c, float); d = np.diff(c, prepend=c[0])
    au = pd.Series(np.where(d > 0, d, 0.0)).ewm(alpha=1 / n, adjust=False).mean().to_numpy()
    ad = pd.Series(np.where(d < 0, -d, 0.0)).ewm(alpha=1 / n, adjust=False).mean().to_numpy()
    return 100 - 100 / (1 + au / np.maximum(ad, 1e-12))


def divergence(c, r, lows_i):
    """bullish RSI divergence: a later low at or below an earlier low while RSI is 2+ points higher. Returns RSI gap or 0."""
    best = 0.0
    for a in range(len(lows_i)):
        for b in range(a + 1, len(lows_i)):
            ia, ib = lows_i[a], lows_i[b]
            if c[ib] <= c[ia] and r[ib] > r[ia] + 2:
                best = max(best, float(r[ib] - r[ia]))
    return best


def chart(x):
    t = x.tail(320)
    return dict(t=[str(d.date()) for d in t.index], o=[round(float(v), 2) for v in t.Open], h=[round(float(v), 2) for v in t.High],
                l=[round(float(v), 2) for v in t.Low], c=[round(float(v), 2) for v in t.Close],
                sma50=[None if np.isnan(v) else round(float(v), 2) for v in x.Close.rolling(50).mean().tail(320)],
                sma200=[None if np.isnan(v) else round(float(v), 2) for v in x.Close.rolling(200).mean().tail(320)],
                rsi=[round(float(v), 1) for v in rsi(x.Close.to_numpy(float))[-320:]])


def main():
    os.makedirs(CH, exist_ok=True)
    for f in os.listdir(CH):
        os.remove(os.path.join(CH, f))
    from session import drop_partial
    u = nse_symbols(); u = u[u.board == "main"] if "board" in u else u
    u["ticker"] = u.symbol + ".NS"; name = dict(zip(u.symbol, u.name)) if "name" in u else {}
    jobs = [(t, s, name.get(s, s), "stock") for t, s in zip(u.ticker, u.symbol)] + [(t, n_, n_, "index") for t, n_ in INDICES.items()]
    rows, srows, asof = [], [], None
    for a in range(0, len(jobs), 80):
        chunk = jobs[a:a + 80]; dd = None
        for _ in range(3):
            try:
                dd = yf.download([j[0] for j in chunk], period="3y", interval="1d", auto_adjust=True, progress=False, group_by="column", threads=True)
                break
            except Exception as e:  # noqa: BLE001
                print("retry", a, e, flush=True); time.sleep(20)
        if dd is None or dd.empty:
            continue
        for t, sym, nm, kind in chunk:
            try:
                x = pd.DataFrame({k: dd[k][t] for k in ("Open", "High", "Low", "Close", "Volume")}).dropna(subset=["Close"])
                x = drop_partial(x, "NSE")
                if len(x) < 150:
                    continue
                asof = max(asof, x.index[-1].date()) if asof else x.index[-1].date()
                if kind == "stock":
                    if float(x.Close.iloc[-1]) < MIN_CLOSE or float((x.Close * x.Volume).tail(20).mean()) < MINVAL:
                        continue
                r = scan(x, sym, nm, kind)
                s_ = support(x, sym, nm) if kind == "stock" else None
                if r:
                    rows.append(r)
                if s_:
                    srows.append(s_)
                if r or s_:
                    json.dump(chart(x), open(f"{CH}/{sym.replace(' ', '_')}.json", "w"))
            except Exception as e:  # noqa: BLE001
                print("fail", sym, e)
        print(a + len(chunk), "done;", len(rows), "patterns", flush=True)
    regime = None
    try:
        h = pd.read_csv(f"{OUT}/sector_hist.csv.gz", index_col=0, parse_dates=True)
        N = h[h.INDEX == "NIFTY 500"].CLOSE.sort_index(); regime = dict(nifty500=float(N.iloc[-1]), sma200=float(N.rolling(200).mean().iloc[-1]))
        regime["down"] = regime["nifty500"] < regime["sma200"]
    except Exception:  # noqa: BLE001
        pass
    order = {"breakout": 0, "forming": 1}
    rows.sort(key=lambda r: (r["kind"] != "index", order[r["status"]], r["to_neck_pct"] if r["status"] == "forming" else r["days_since"]))
    out = dict(generated=datetime.now(timezone.utc).isoformat(timespec="minutes"), asof=str(asof), market="NSE", regime=regime,
               rules="zigzag 6% on closes; after a 20%+ fall; DB +-3%, tilted W +3..12%, TB within 4%, IHS head 3% below shoulders; "
                     "breakout = close above the neckline within 60 days of the last low",
               backtest="2016-26, 3,994 signals: 120-day return +3.5% vs +7.4% for a random liquid stock; in market downtrends +10.5% "
                        "vs +13.6% for any stock; target before stop 63% vs 63% for a random stock; with bullish RSI divergence "
                        "66% vs 65%, 120d +4.7%. No edge - watch only.",
               rows=rows)
    json.dump(out, open(f"{OUT}/patterns.json", "w"), indent=0)
    print("patterns", len(rows), {s: sum(r["status"] == s for r in rows) for s in order})
    srows.sort(key=lambda r: (r["status"] != "touched", not r["sq9_match"], r["days_ago"] if r["status"] == "touched" else r["above_pct"]))
    json.dump(dict(generated=out["generated"], asof=out["asof"], market="NSE",
                   rules="Uptrend (close > SMA50 > SMA200, SMA200 rising over 20 days). Level = old swing (zigzag 6% on closes, last 3 years) "
                         "that price moved 8%+ above. 'Touched' = first return since: low within 3% of the level, close at or above it (last 5 sessions). "
                         "'Near' = close 0-5% above a level not yet revisited. Stop = level - 1 ATR(14). Square of 9: odd squares "
                         "(1, 9, 25, 49, 81, 121 ...); 'on Sq9' = the level is within 1% of an odd square.",
                   backtest="2016-26, 16,908 first touches, 3R target vs stop (1 ATR below the level): breakout retests +0.20R per trade, "
                            "old swing lows +0.10R, random uptrend stock the same day +0.09R. Trades with 1:3 room to the next resistance: no better. "
                            "Within 1% of an odd square: no better (breakout retests +0.15R vs +0.21R away from one; swing lows +0.04R vs +0.09R). Watch only.",
                   rows=srows), open(f"{OUT}/support.json", "w"), indent=0)
    print("support", len(srows), sum(r["status"] == "touched" for r in srows), "touched;", sum(r["sq9_match"] for r in srows), "on a Square-of-9 number")


if __name__ == "__main__":
    main()
