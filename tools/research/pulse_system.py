"""Strong-Pulse + rotation industries as a STOCK system (22 Nov 2026, Amritpal: "yes test it").

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
LIMIT env = pilot. Output data/research/pulse_system(_pilot).json"""
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
LIMIT = os.environ.get("LIMIT", "0") not in ("", "0")
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

    def sim(mode, fill, gate=None, cash=False):
        val, eq, held, wts, turn = 1.0, [], [], {}, 0.0
        nh = []
        for a, b in zip(weeks[:-1], weeks[1:]):
            new = pick(a, mode, held)
            if gate is not None and not bool(gate.get(a, True)):        # gate off: no new buys, holdings follow their rules (cash=True: hold nothing)
                new = {} if cash else {s: 1.0 for s in held if s in new}
            tot = sum(new.values()) or 1
            nw = {s: v / tot for s, v in new.items()}
            ch = sum(abs(nw.get(s, 0) - wts.get(s, 0)) for s in set(nw) | set(wts)); turn += ch
            if fill == "FRI":
                px0 = C.loc[a]
            else:                                                # Monday open: first session after a
                i = C.index.get_loc(a) + 1
                px0 = O.iloc[i] if i < len(C) else C.loc[a]
            px1 = C.loc[b]
            r_ = 0.0
            for s, wt in nw.items():
                p0, p1 = px0.get(s), px1.get(s)
                if p0 and p1 and np.isfinite(p0) and np.isfinite(p1) and p0 > 0:
                    r_ += wt * float(np.clip(p1 / p0 - 1, -0.6, 1.5))
            if fill == "MON" and wts:                            # the Friday->Monday gap is earned by the OLD holdings
                i = C.index.get_loc(a) + 1
                if i < len(C):
                    g = 0.0
                    for s, wt in wts.items():
                        p0, p1 = C.loc[a].get(s), O.iloc[i].get(s)
                        if p0 and p1 and np.isfinite(p0) and np.isfinite(p1) and p0 > 0:
                            g += wt * float(np.clip(p1 / p0 - 1, -0.3, 0.3))
                    val *= 1 + g
            val *= (1 - COST * ch) * (1 + r_); eq.append((b, val)); held = list(nw); wts = nw; nh.append(len(nw))
        e = pd.Series(dict(eq)); e = pd.concat([pd.Series({weeks[0]: 1.0}), e])
        return e, round(turn / max(1, len(weeks) / 52), 1), round(float(np.mean(nh)), 1)

    bull = (nifty > nifty.rolling(200).mean())
    res = dict(method=__doc__, industries=len(mem), stocks=C.shape[1], runs={})
    print("R| industries", len(mem), "stocks", C.shape[1], "weeks", len(weeks), flush=True)
    if os.environ.get("REDLIGHT") == "1":   # 23 Nov 2026 (Amritpal: "yes" - skip the basket when the traffic light is RED)
        # light as the app (tools/research/light_distribution.light_series) on this panel: RED = 9/21 bearish crosses > bullish crosses over
        # the last 10 sessions AND Nifty's weekly close below its 30-week SMA; AMBER = one of the two. Read at the Friday decision close.
        up9 = (e9 > e21); pv = up9.shift(1)
        xu = (up9 & (pv == False)).sum(axis=1); xd = ((~up9) & (pv == True)).sum(axis=1)   # noqa: E712
        br_bad = xd.rolling(10).sum() > xu.rolling(10).sum()
        wk = nifty.groupby(pd.Grouper(freq="W-FRI")).last().dropna(); below = wk < wk.rolling(30).mean()
        idx_bad = below.reindex(C.index, method="ffill").fillna(False).astype(bool)
        light = pd.Series(np.where(br_bad & idx_bad, "RED", np.where(br_bad | idx_bad, "AMBER", "GREEN")), index=C.index)
        LW = {d: light.loc[d] for d in weeks}
        print("R| light at decision Fridays", pd.Series(list(LW.values())).value_counts().to_dict(), flush=True)
        notred = {d: LW[d] != "RED" for d in weeks}; green = {d: LW[d] == "GREEN" for d in weeks}
        for nm, gate, cash in (("TOP10 MON (live rule)", None, False), ("RED light: no new buys that week (holdings stay)", notred, False),
                               ("RED light: no basket that week (all cash)", notred, True), ("RED or AMBER: no new buys that week", green, False)):
            e, tpy, avgn = sim("top10", "MON", gate, cash=cash)
            rp = report(e, bull); rp["turnover_x_per_year"] = tpy; rp["avg_holdings"] = avgn
            res["runs"][nm] = rp; print(f"R| Pulse rotation | {nm} | {rp}", flush=True)
            if cash and not LIMIT:   # 23 Nov 2026: monthly equity of the live rule (RED-light all cash) for the portfolio-mix test
                m = e.resample("ME").last()
                json.dump({"t": [str(x.date()) for x in m.index], "v": [round(float(v), 5) for v in m.values]}, open("data/research/pulse_monthly.json", "w"))
                print("R| PULSE_MONTHLY " + json.dumps({"t": [str(x.date()) for x in m.index], "v": [round(float(v), 5) for v in m.values]}), flush=True)
        json.dump(res, open("data/research/fii_pulse_redlight" + ("_pilot" if LIMIT else "") + ".json", "w"), indent=1, default=str)
        return
    if os.environ.get("REDFRI") == "1":     # 23 Nov 2026 (Amritpal: "if Friday's market closes red I want to avoid the basket")
        up = nifty > nifty.shift(1)                       # decision day (Friday close) green
        Gu = {d: bool(up.loc[d]) for d in weeks}
        for nm, gate, cash in (("TOP10 MON (live rule)", None, False), ("Friday red: no new buys that week (holdings stay)", Gu, False),
                               ("Friday red: no basket that week (all cash)", Gu, True)):
            e, tpy, avgn = sim("top10", "MON", gate, cash=cash)
            rp = report(e, bull); rp["turnover_x_per_year"] = tpy; rp["avg_holdings"] = avgn
            res["runs"][nm] = rp; print(f"R| Pulse rotation | {nm} | {rp}", flush=True)
        n_red = sum(1 for d in weeks if not Gu[d]); print(f"R| red Fridays {n_red} of {len(weeks)}", flush=True)
        json.dump(res, open("data/research/fii_pulse_redfri" + ("_pilot" if LIMIT else "") + ".json", "w"), indent=1, default=str)
        return
    if os.environ.get("FII") == "1":     # 22 Nov 2026: "test all systems against regular FII buying" (tools/research/fii_gate.py)
        import fii_gate as FG
        G = FG.gates(C.index); res["gates"] = FG.NAMES
        for nm, col in [("TOP10 MON (live rule)", None)] + [(FG.NAMES[k], k) for k in FG.NAMES]:
            e, tpy, avgn = sim("top10", "MON", None if col is None else G[col])
            rp = report(e, bull); rp["turnover_x_per_year"] = tpy; rp["avg_holdings"] = avgn
            res["runs"][nm] = rp; print(f"R| Pulse rotation | {nm} | {rp}", flush=True)
        json.dump(res, open("data/research/fii_pulse_rot" + ("_pilot" if LIMIT else "") + ".json", "w"), indent=1, default=str)
        return
    for nm, mode in (("TOP10 strong-Pulse + rotation industries", "top10"), ("TOP5", "top5"), ("BASKET (all stocks of those industries)", "basket"),
                     ("TOP10 ANY industry (control)", "any"), ("TOP10 top-10% Pulse only, no rotation (control)", "pulse_only"), ("ALL industries' stocks", "all")):
        for fill in ("FRI", "MON"):
            if mode == "all" and fill == "MON":
                continue
            e, tpy, avgn = sim(mode, fill); rp = report(e, bull); rp["turnover_x_per_year"] = tpy; rp["avg_holdings"] = avgn
            res["runs"][f"{nm} | {fill}"] = rp
            print(f"R| {nm} | {fill} | {rp}", flush=True)
    nn = NW.loc[weeks]; res["nifty"] = report(nn / nn.iloc[0], bull); print("R| Nifty 50 |", res["nifty"], flush=True)
    # what it holds now
    d = weeks[-1]; res["now"] = dict(date=str(d.date()), industries=[k for k in sel.columns if sel.loc[d, k]],
                                     top10=list(pick(d, "top10", [])))
    print("R| NOW", res["now"], flush=True)
    os.makedirs("data/research", exist_ok=True)
    json.dump(res, open("data/research/pulse_system" + ("_pilot" if LIMIT else "") + ".json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
