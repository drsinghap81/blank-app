"""Rotation + Pulse together (22 Nov 2026, Amritpal: "check that" - does a group moving into Improving / Leading while its Pulse is
rising do better than either alone?).

Universe: NSE official basic industries with 3+ liquid stocks (today's members - survivorship bias in their favour), equal-weight
daily index each (daily returns clipped at +-30%), 2015-26 from Yahoo (+ bhavcopy check on recent sessions).
Weekly at the Friday close:
  rotation  vs Nifty 50, app formula: RS-ratio = 100 x RS / 10-week avg; RS-momentum = 3-week avg of ratio change (L/W/G/I)
  Pulse     app formula (tools/group_pulse.py): a stock is 'trending' when its relative performance score > 100, EMA9 > EMA21,
            Stage 2 (above a rising 150-day SMA), within 25% of its 52-week high and liquid; Pulse = share of the industry's stocks
            trending, averaged over the last 21 sessions (1-month Pulse). Rising = higher than 4 weeks ago.
Events and states, next 1 / 4 / 13 weeks' return of the industry MINUS Nifty (from the Friday close):
  base (every industry-week) | entry into Improving or Leading | Pulse rising | ENTRY + Pulse rising | ENTRY + Pulse rising + Pulse
  above the median | state: in Improving/Leading with Pulse rising vs falling
Portfolios (weekly rebalance, 0.2% on what changes, equal weight): hold every industry in Improving/Leading with Pulse rising |
hold Leading (earlier test) | hold top-10% Pulse | all industries. Newest first, bull/bear, ex-Covid.
LIMIT env = pilot (fewer industries). Output data/research/rotation_pulse(_pilot).json"""
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

IND, SYMS = B.IND, B.SYMS
LIMIT = bool(os.environ.get("LIMIT"))
COST = 0.002; MINVAL = 1e7; MINPX = 50


def load():
    C, V = {}, {}
    for a in range(0, len(SYMS), 100):
        ch = [s + ".NS" for s in SYMS[a:a + 100]]
        for k in range(4):
            try:
                d = yf.download(ch, start="2015-01-01", interval="1d", progress=False, group_by="column", auto_adjust=True, threads=True)
            except Exception as e:  # noqa: BLE001
                print("retry", e); time.sleep(20); continue
            got = [t for t in ch if t in d["Close"].columns and d["Close"][t].notna().sum() > 200]
            for t in got:
                C[t[:-3]] = d["Close"][t]; V[t[:-3]] = d["Volume"][t]
            if len(got) >= 0.9 * len(ch):
                break
            time.sleep(20 * (k + 1))
        print("R| loaded", a + len(ch), len(C), flush=True); time.sleep(2)
    b = yf.download("^NSEI", start="2015-01-01", interval="1d", progress=False, auto_adjust=True)["Close"]
    b = b.iloc[:, 0] if isinstance(b, pd.DataFrame) else b
    C = pd.DataFrame(C).sort_index(); V = pd.DataFrame(V).reindex(C.index)
    C.index = pd.to_datetime(C.index).tz_localize(None); V.index = C.index; b.index = pd.to_datetime(b.index).tz_localize(None)
    return C, V, b.reindex(C.index).ffill()


def report(eq, bull):
    eq = eq.dropna(); end = eq.index[-1]; yrs = (end - eq.index[0]).days / 365.25; out = {}
    out["CAGR"] = round((float(eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1) * 100, 1)
    out["max DD"] = round(float((eq / eq.cummax() - 1).min()) * 100, 1)
    for y in (1, 2, 3, 5):
        e = eq[eq.index >= end - pd.DateOffset(years=y)]
        out[f"{y}y"] = round((float(e.iloc[-1] / e.iloc[0]) ** (1 / y) - 1) * 100, 1)
    yr = eq.resample("YE").last(); yr = pd.concat([eq.iloc[:1], yr]).pct_change().dropna()
    out["years"] = {str(k.year): round(v * 100, 1) for k, v in sorted(yr.items(), reverse=True)}
    r = eq.pct_change().dropna(); b = bull.reindex(r.index, method="ffill").fillna(False).astype(bool).values
    ann = lambda x: round(float((1 + x).prod() ** (52 / max(1, len(x))) - 1) * 100, 1)  # noqa: E731
    out["bull/bear a year"] = [ann(r[b]), ann(r[~b])]
    cov = np.asarray((r.index >= "2020-02-15") & (r.index <= "2020-12-31")); rx = r[~cov]; ex = (1 + rx).cumprod()
    out["ex-Covid"] = [ann(rx), round(float((ex / ex.cummax() - 1).min()) * 100, 1)]
    return out


def main():
    C, V, nifty = load()
    ret = C.pct_change(fill_method=None).clip(-0.3, 0.3)
    liq = ((C * V).rolling(60, min_periods=40).median() >= MINVAL) & (C >= MINPX)
    rpi = lambda k: 100 * (C / C.shift(k)).div(nifty / nifty.shift(k), axis=0)  # noqa: E731
    w = (rpi(10) + rpi(63) + rpi(126)) / 3
    e9 = C.ewm(span=9, adjust=False).mean(); e21 = C.ewm(span=21, adjust=False).mean(); s150 = C.rolling(150).mean()
    hi52 = C.rolling(250, min_periods=120).max()
    tr = ((w > 100) & (e9 > e21) & (C > s150) & (s150 > s150.shift(20)) & (C >= 0.75 * hi52) & liq).astype(float).where(C.notna())
    idx, pul = {}, {}
    for k, v in IND.items():
        m = [s for s in v if s in C.columns]
        if len(m) < 3:
            continue
        idx[k] = (1 + ret[m].mean(axis=1).fillna(0)).cumprod()
        live = liq[m]; share = (tr[m].where(live)).mean(axis=1) * 100
        pul[k] = share.rolling(21, min_periods=15).mean()
    idx = pd.DataFrame(idx); pul = pd.DataFrame(pul)
    W = idx.resample("W-FRI").last(); NW = nifty.resample("W-FRI").last(); PW = pul.resample("W-FRI").last()
    RS = 100 * W.div(NW, axis=0); ratio = 100 * RS / RS.rolling(10).mean(); mom = (100 * ratio / ratio.shift(1)).rolling(3).mean()
    Q = pd.DataFrame(np.where(ratio >= 100, np.where(mom >= 100, "L", "W"), np.where(mom >= 100, "I", "G")), index=W.index, columns=W.columns).where(ratio.notna() & mom.notna())
    rel = {h: (W.shift(-h) / W - 1).sub(NW.shift(-h) / NW - 1, axis=0) for h in (1, 4, 13)}
    start = pd.Timestamp("2016-06-01"); keep = W.index >= start
    up = PW > PW.shift(4); med = PW.where(PW > 0).stack().median()
    IL = Q.isin(["I", "L"]); entry = IL & ~IL.shift(1).fillna(False).astype(bool) & Q.shift(1).notna()
    masks = {"every industry-week (base)": pd.DataFrame(True, index=W.index, columns=W.columns),
             "entry into Improving/Leading": entry, "Pulse rising": up, "ENTRY + Pulse rising": entry & up,
             "ENTRY + Pulse rising + Pulse above median": entry & up & (PW >= med),
             "in Improving/Leading, Pulse rising": IL & up, "in Improving/Leading, Pulse falling": IL & ~up,
             "in Lagging/Weakening, Pulse rising": Q.isin(["G", "W"]) & up}
    res = dict(method=__doc__, industries=W.shape[1], stocks=C.shape[1], pulse_median=round(float(med), 1), events={}, portfolios={})
    print("R| industries", W.shape[1], "stocks", C.shape[1], "weeks", int(keep.sum()), "Pulse median", round(float(med), 1), flush=True)
    for nm, M in masks.items():
        M = M.loc[keep]; o = {}
        for h, R in rel.items():
            v = R.loc[keep][M.fillna(False).astype(bool)].stack().dropna()
            yrs = {}
            for y in (1, 2, 3, 5):
                vv = v[v.index.get_level_values(0) >= W.index[-1] - pd.DateOffset(years=y)]
                yrs[f"last {y}y"] = round(float(vv.mean()) * 100, 2) if len(vv) else None
            o[f"{h}w"] = dict(n=int(len(v)), avg=round(float(v.mean()) * 100, 2), beat=round(float((v > 0).mean()) * 100), **yrs)
        res["events"][nm] = o
        print(f"R| {nm} | {o}", flush=True)
    # portfolios
    bull = (nifty > nifty.rolling(200).mean()).resample("W-FRI").last()
    wr = W.pct_change(fill_method=None).shift(-1)
    def port(sel):
        eq, prev, val = [], None, 1.0
        for d in W.index[keep]:
            held = [c for c in W.columns if sel.loc[d, c]] if d in sel.index else []
            r_ = float(wr.loc[d, held].mean()) if held else 0.0
            ch = 1.0 if prev is None else (len(set(held) ^ set(prev)) / max(1, len(set(held) | set(prev))))
            val *= (1 + (0 if np.isnan(r_) else r_)) * (1 - COST * ch); prev = held; eq.append((d, val))
        return pd.Series(dict(eq)).shift(1).fillna(1.0)
    top10 = PW.rank(axis=1, pct=True) >= 0.9
    P = {"hold Improving/Leading with Pulse rising": IL & up, "hold Leading (earlier test)": Q == "L", "hold top-10% Pulse": top10,
         "hold Improving/Leading with Pulse rising + above median": IL & up & (PW >= med), "all industries": pd.DataFrame(True, index=W.index, columns=W.columns)}
    for nm, sel in P.items():
        rp = report(port(sel.fillna(False)), bull); res["portfolios"][nm] = rp
        print(f"R| PORT {nm} | {rp}", flush=True)
    nn = NW.loc[keep]; res["nifty"] = report(nn / nn.iloc[0], bull); print("R| PORT Nifty 50 |", res["nifty"], flush=True)
    os.makedirs("data/research", exist_ok=True)
    json.dump(res, open("data/research/rotation_pulse" + ("_pilot" if LIMIT else "") + ".json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
