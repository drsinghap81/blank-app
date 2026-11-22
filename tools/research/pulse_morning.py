"""Pulse rotation: pre-market / first-hour checks on the Monday buys (22 Nov 2026, Amritpal: "before that, can we check if pre-market and
the first 15 mins or half an hour shows a sector in green, the app can alert or reshuffle stocks on top which are moving in the morning").
Based on: Strong-Pulse + rotation industries as a STOCK system (22 Nov 2026, Amritpal: "yes test it").

Each Friday close, select NSE basic industries in the top 10% by 1-month Pulse AND whose weekly rotation is Leading or Improving
(tools/research/rotation_pulse.py - best industry basket there, 45.6%/yr). Then hold stocks inside them:
  BASKET    every liquid stock of the selected industries, equal weight
  TOP10     the 10 strongest TRENDING stocks (Pulse definition) of the selected industries by 3-month relative strength;
            a holding stays while it ranks in the top 20 and its industry stays selected (buffer cuts churn); equal weight
  TOP5      same with 5 / 10
Controls: TOP10 ANY = the 10 strongest trending stocks from ANY industry (does the industry filter add?) | top-10% Pulse only
(no rotation) TOP10 | all industries equal weight | Nifty 50.
Trading: decided at the Friday close; filled at that close (FRI) or at Monday's open (MON, realistic); 0.2% cost per side on the
weight that changes. Survivors only (today's industry members) - flatters every row. Newest first, bull/bear, ex-Covid.
Variants on the NEW buys of each Monday (holdings kept from last week are not touched):
  OPEN      buy every new pick at Monday's open (the live rule)
  GAP_UP    buy a new pick only if the stock opens above Friday's close (pre-market green); else the slot stays cash that week
  IND_UP    only if the stock's INDUSTRY (equal-weight members) opens above Friday's close
  NO_CHASE  skip new picks gapping up more than 2%
  GAP_DOWN  only new picks opening below Friday's close (buy the dip - control)
  H1 (last ~2 years, hourly bars): buy at the 10:15 price instead of the open; H1_GREEN only if the stock is above its open at 10:15;
  H1_IND only if its industry is above the open at 10:15.
LIMIT env = pilot. Output data/research/pulse_morning(_pilot).json"""
import json
import os
import sys
import time

import numpy as np
import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..")); sys.path.insert(0, HERE)
import nse_bhav; nse_bhav.install()  # noqa: E402,E702
import industry_basket_intraday as B  # noqa: E402
from rotation_pulse import report  # noqa: E402

IND, SYMS = B.IND, B.SYMS
LIMIT = bool(os.environ.get("LIMIT"))
COST = 0.002; MINVAL = 1e7; MINPX = 50


def load():
    C, O, V = {}, {}, {}
    for a in range(0, len(SYMS), 100):
        ch = [s + ".NS" for s in SYMS[a:a + 100]]
        for k in range(4):
            try:
                d = yf.download(ch, start="2015-01-01", interval="1d", progress=False, group_by="column", auto_adjust=True, threads=True)
            except Exception as e:  # noqa: BLE001
                print("retry", e); time.sleep(20); continue
            got = [t for t in ch if t in d["Close"].columns and d["Close"][t].notna().sum() > 200]
            for t in got:
                C[t[:-3]] = d["Close"][t]; O[t[:-3]] = d["Open"][t]; V[t[:-3]] = d["Volume"][t]
            if len(got) >= 0.9 * len(ch):
                break
            time.sleep(20 * (k + 1))
        print("R| loaded", a + len(ch), len(C), flush=True); time.sleep(2)
    b = yf.download("^NSEI", start="2015-01-01", interval="1d", progress=False, auto_adjust=True)["Close"]
    b = b.iloc[:, 0] if isinstance(b, pd.DataFrame) else b
    C = pd.DataFrame(C).sort_index(); C.index = pd.to_datetime(C.index).tz_localize(None)
    O = pd.DataFrame(O).reindex(C.index); V = pd.DataFrame(V).reindex(C.index)
    b.index = pd.to_datetime(b.index).tz_localize(None)
    return C, O, V, b.reindex(C.index).ffill()


def main():
    C, O, V, nifty = load()
    ret = C.pct_change(fill_method=None).clip(-0.3, 0.3)
    liq = ((C * V).rolling(60, min_periods=40).median() >= MINVAL) & (C >= MINPX)
    rpi = lambda k: 100 * (C / C.shift(k)).div(nifty / nifty.shift(k), axis=0)  # noqa: E731
    w = (rpi(10) + rpi(63) + rpi(126)) / 3
    e9 = C.ewm(span=9, adjust=False).mean(); e21 = C.ewm(span=21, adjust=False).mean(); s150 = C.rolling(150).mean()
    hi52 = C.rolling(250, min_periods=120).max()
    tr = (w > 100) & (e9 > e21) & (C > s150) & (s150 > s150.shift(20)) & (C >= 0.75 * hi52) & liq
    r63 = C / C.shift(63) - 1
    idx, pul, mem = {}, {}, {}
    for k, v in IND.items():
        m = [s for s in v if s in C.columns]
        if len(m) < 3:
            continue
        mem[k] = m
        idx[k] = (1 + ret[m].mean(axis=1).fillna(0)).cumprod()
        pul[k] = (tr[m].astype(float).where(C[m].notna()).where(liq[m])).mean(axis=1).mul(100).rolling(21, min_periods=15).mean()
    idx = pd.DataFrame(idx); pul = pd.DataFrame(pul)
    fri = idx.resample("W-FRI").last().index
    fri = [C.index[C.index.get_indexer([d], method="pad")[0]] for d in fri if d >= C.index[0]]   # last trading day of each week
    fri = sorted(set(fri))
    W = idx.loc[fri]; NW = nifty.loc[fri]; PW = pul.loc[fri]
    RS = 100 * W.div(NW, axis=0); ratio = 100 * RS / RS.rolling(10).mean(); mom = (100 * ratio / ratio.shift(1)).rolling(3).mean()
    IL = (mom >= 100) & ratio.notna() & mom.notna()             # Leading or Improving = momentum >= 100
    top10 = PW.rank(axis=1, pct=True) >= 0.9
    sel = top10 & IL
    start = pd.Timestamp("2016-06-01"); weeks = [d for d in fri if d >= start]
    s2i = {s: k for k, v in mem.items() for s in v}
    trW = tr.loc[fri]; r63W = r63.loc[fri]; liqW = liq.loc[fri]

    def pick(d, mode, held):
        if mode == "all":
            return {s: 1.0 for v in mem.values() for s in v if liqW.loc[d, s]}
        inds = [k for k in sel.columns if sel.loc[d, k]] if mode != "pulse_only" else [k for k in top10.columns if top10.loc[d, k]]
        if mode == "basket":
            return {s: 1.0 for k in inds for s in mem[k] if liqW.loc[d, s]}
        n = 5 if mode == "top5" else 10
        if mode == "any":
            cand = [s for s in C.columns if trW.loc[d, s]]
        else:
            cand = [s for k in inds for s in mem[k] if trW.loc[d, s]]
        rk = sorted(cand, key=lambda s: -(r63W.loc[d, s] if np.isfinite(r63W.loc[d, s]) else -9))
        top2 = set(rk[:2 * n]); keep = [s for s in held if s in top2]
        for s in rk:
            if len(keep) >= n:
                break
            if s not in keep:
                keep.append(s)
        return {s: 1.0 for s in keep}

    def sim(rule, H=None, hstart=None):
        """weekly book; new buys filtered / priced by rule. Returns equity, avg holdings, share of new picks skipped."""
        val, eq, held, wts, nh, skipped, newn = 1.0, [], [], {}, [], 0, 0
        W0 = [w_ for w_ in weeks if hstart is None or w_ >= hstart]
        for a, b in zip(W0[:-1], W0[1:]):
            want = list(pick(a, "top10", held))
            i = C.index.get_loc(a) + 1
            if i >= len(C):
                break
            mon = C.index[i]
            keep = []
            for s in want:
                if s in held:
                    keep.append(s); continue
                newn += 1
                o, c0 = O.loc[mon].get(s), C.loc[a].get(s)
                gap = (o / c0 - 1) if o and c0 and np.isfinite(o) and np.isfinite(c0) and c0 > 0 else 0.0
                ig = IGAP.get(s2i.get(s), pd.Series(dtype=float)).get(mon, 0.0)
                ok = True
                if rule == "GAP_UP": ok = gap > 0
                elif rule == "IND_UP": ok = (ig if np.isfinite(ig) else 0) > 0
                elif rule == "NO_CHASE": ok = gap <= 0.02
                elif rule == "GAP_DOWN": ok = gap < 0
                elif rule in ("H1_GREEN", "H1_IND"):
                    hp = H1.get(s, {}).get(mon)
                    if rule == "H1_GREEN": ok = hp is not None and o and hp > o
                    else:
                        iv = H1IND.get(s2i.get(s), {}).get(mon); ok = iv is not None and iv > 0
                if ok:
                    keep.append(s)
                else:
                    skipped += 1
            nw = {s: 1 / len(want) for s in keep} if want else {}          # skipped slots stay in cash (weight 1/10 each)
            ch = sum(abs(nw.get(s, 0) - wts.get(s, 0)) for s in set(nw) | set(wts))
            g = 0.0                                                         # Friday close -> Monday open earned by the old book
            for s, wt in wts.items():
                p0, p1 = C.loc[a].get(s), O.loc[mon].get(s)
                if p0 and p1 and np.isfinite(p0) and np.isfinite(p1) and p0 > 0:
                    g += wt * float(np.clip(p1 / p0 - 1, -0.3, 0.3))
            val *= 1 + g
            r_ = 0.0
            for s, wt in nw.items():
                p0 = O.loc[mon].get(s)
                if rule.startswith("H1") and s not in held:                # bought at 10:15 instead of the open
                    hp = H1.get(s, {}).get(mon)
                    if hp is None:
                        continue
                    # open -> 10:15 move of a new buy is missed; the old book already earned the gap only
                    p0 = hp
                p1 = C.loc[b].get(s)
                if p0 and p1 and np.isfinite(p0) and np.isfinite(p1) and p0 > 0:
                    r_ += wt * float(np.clip(p1 / p0 - 1, -0.6, 1.5))
            val *= (1 - COST * ch) * (1 + r_); eq.append((b, val)); held = keep; wts = nw; nh.append(len(nw))
        e = pd.Series(dict(eq)); e = pd.concat([pd.Series({W0[0]: 1.0}), e])
        return e, round(float(np.mean(nh)), 1), round(100 * skipped / max(1, newn))

    # industry opening gap (equal weight of the members): Monday open vs Friday close
    gap_all = (O / C.shift(1) - 1).clip(-0.2, 0.2)
    IGAP = {k: gap_all[m].mean(axis=1) for k, m in mem.items()}
    # hourly: first-hour (09:15-10:15) close for every stock, last ~2 years
    H1, H1IND, hstart = {}, {}, None
    try:
        hs = list(C.columns)
        for a_ in range(0, len(hs), 100):
            ch_ = [s_ + ".NS" for s_ in hs[a_:a_ + 100]]
            dh = yf.download(ch_, period="730d", interval="60m", progress=False, group_by="column", auto_adjust=True, threads=True)
            if dh is None or not len(dh):
                continue
            cl, op = dh["Close"], dh["Open"]
            for X_ in (cl, op):
                X_.index = pd.to_datetime(X_.index)
                if X_.index.tz is not None:
                    X_.index = X_.index.tz_convert("Asia/Kolkata").tz_localize(None)
            m915 = cl.index.time == pd.Timestamp("09:15").time()      # the 09:15 bar closes at 10:15
            # hourly and daily series are adjusted differently -> keep the first hour's MOVE and apply it to the daily open
            mv = (cl[m915] / op[m915]).replace([np.inf, -np.inf], np.nan)
            for t in ch_:
                if t in mv.columns:
                    sr = mv[t].dropna(); sr = sr[(sr > 0.8) & (sr < 1.25)]
                    o_ = O[t[:-3]] if t[:-3] in O.columns else None
                    if o_ is None:
                        continue
                    H1[t[:-3]] = {pd.Timestamp(k.date()): float(v * o_.get(pd.Timestamp(k.date()), np.nan)) for k, v in sr.items()
                                  if np.isfinite(o_.get(pd.Timestamp(k.date()), np.nan))}
            time.sleep(2)
        dates = sorted({d_ for v in H1.values() for d_ in v})
        hstart = dates[0] + pd.Timedelta(days=7) if dates else None
        for k, m in mem.items():
            dd = {}
            for d_ in dates:
                if d_ not in O.index:
                    continue
                v = [H1[s][d_] / O.loc[d_, s] - 1 for s in m if s in H1 and d_ in H1[s] and np.isfinite(O.loc[d_, s]) and O.loc[d_, s] > 0]
                if v:
                    dd[d_] = float(np.mean(v))
            H1IND[k] = dd
        print("R| hourly loaded", len(H1), "stocks from", hstart, flush=True)
    except Exception as e:  # noqa: BLE001
        print("R| hourly failed", e, flush=True)

    bull = (nifty > nifty.rolling(200).mean())
    res = dict(method=__doc__, runs={}, runs_2y={})
    for rule in ("OPEN", "GAP_UP", "IND_UP", "NO_CHASE", "GAP_DOWN"):
        e, nh, sk = sim(rule); rp = report(e, bull); rp.update(avg_holdings=nh, new_picks_skipped_pct=sk)
        res["runs"][rule] = rp; print(f"R| {rule} | {rp}", flush=True)
    if hstart is not None:
        for rule in ("OPEN", "GAP_UP", "IND_UP", "H1", "H1_GREEN", "H1_IND"):
            e, nh, sk = sim(rule, hstart=hstart); rp = report(e, bull); rp.update(avg_holdings=nh, new_picks_skipped_pct=sk)
            res["runs_2y"][rule] = rp; print(f"R| last2y {rule} | {rp}", flush=True)
    os.makedirs("data/research", exist_ok=True)
    json.dump(res, open("data/research/pulse_morning" + ("_pilot" if LIMIT else "") + ".json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
