"""Green open, green day? (23 Nov 2026, Amritpal: "some sectors start green and end green on a green Nifty, Bank Nifty, Midcap or
Smallcap - can't we take intraday advantage of that?")

Yahoo 15-minute bars (last ~60 sessions), 1,066 liquid NSE stocks grouped into the 22 NSE sectors (group_pulse.json), plus
Nifty 50, Nifty Bank, Nifty Midcap 100, Nifty Smallcap 100. A sector's move = equal-weight average of its members.
Question 1 (the observation): when the index is green at 09:30, how often does a sector that is green at 09:30 end the day green
(close above yesterday's close)? -> but you can only buy at 09:30, so
Question 2 (the trade): return from the 09:30 price (or 10:15 after the first hour) to the 15:15 close, 0.10% cost, for
  - every green-at-09:30 sector on index-green days (all members, equal weight)
  - the strongest green sector only;  top 3 trending stocks of it (our ranking)
  - gates: Nifty green / all four indices green / Nifty green at 09:30 AND still green at 10:15 (enter 10:15)
  - controls: red-at-09:30 sectors on the same days; all days
Output data/research/open_green.json"""
import json
import os

import numpy as np
import pandas as pd
import yfinance as yf

from cluster_open15 import dl

IDX = {"Nifty 50": ["^NSEI"], "Nifty Bank": ["^NSEBANK"], "Midcap": ["NIFTY_MIDCAP_100.NS", "^NSEMDCP50", "^CNXMIDCAP"], "Smallcap": ["^CNXSC", "NIFTY_SMLCAP_100.NS", "^CNXSMALLCAP"]}


def naive(ix):
    return ix.tz_convert("Asia/Kolkata").tz_localize(None) if ix.tz is not None else ix


def main():
    G = json.load(open("data/scan/group_pulse.json")); SEC = {}
    for r in G["nse"]["rows"]:
        liq = [m["symbol"] for m in r["members"] if m.get("liquid")]
        SEC.setdefault(r.get("sector") or r.get("macro"), []).extend(liq)
    SEC = {k: v for k, v in SEC.items() if len(v) >= 5}
    syms = sorted({s for v in SEC.values() for s in v})
    I = dl([s + ".NS" for s in syms], period="60d", interval="15m")
    D = dl([s + ".NS" for s in syms], period="2y", interval="1d")
    for x in I.values():
        x.index = naive(x.index)
    IX15, IXD = {}, {}
    for nm, tks in IDX.items():
        for tk in tks:
            try:
                a = yf.download(tk, period="60d", interval="15m", progress=False, auto_adjust=True)["Close"]
                b = yf.download(tk, period="1y", interval="1d", progress=False, auto_adjust=True)["Close"]
                a = a.iloc[:, 0] if isinstance(a, pd.DataFrame) else a; b = b.iloc[:, 0] if isinstance(b, pd.DataFrame) else b
                a, b = a.dropna(), b.dropna()
                if len(a) > 100 and len(b) > 100:
                    a.index = naive(a.index); b.index = pd.to_datetime(b.index).tz_localize(None); IX15[nm] = a; IXD[nm] = b; break
            except Exception as e:  # noqa: BLE001
                print("index fail", tk, e)
    print("R| index bars", {k: len(v) for k, v in IX15.items()}, flush=True)
    C = pd.DataFrame({k: v.Close for k, v in D.items()}); C.index = pd.to_datetime(C.index).tz_localize(None)
    e9 = C.ewm(span=9, adjust=False).mean(); e21 = C.ewm(span=21, adjust=False).mean(); s150 = C.rolling(150).mean()
    hi = C.rolling(250, min_periods=120).max(); trend = (e9 > e21) & (C > s150) & (s150 > s150.shift(20)) & (C >= 0.75 * hi); r63 = C / C.shift(63) - 1
    days = sorted({t.date() for t in IX15["Nifty 50"].index}); rows = []
    for dy in days:
        dts = pd.Timestamp(dy); pi = C.index.searchsorted(dts) - 1
        if pi < 0:
            continue
        pdt = C.index[pi]; b0, b1, bx = (pd.Timestamp(f"{dy} {h}") for h in ("09:15", "10:00", "15:15"))
        def ixmv(nm, b):
            s15, sd = IX15[nm], IXD[nm]; prev = sd[sd.index < dts]
            return float(s15.at[b] / prev.iloc[-1] - 1) if b in s15.index and len(prev) else None
        ig = {nm: ixmv(nm, b0) for nm in IX15}; ig1 = {nm: ixmv(nm, b1) for nm in IX15}
        if ig["Nifty 50"] is None:
            continue
        st = {}
        for sec, mem in SEC.items():
            m0, m1, r0, r1, endg, tops = [], [], [], [], [], []
            for s in mem:
                x = I.get(s)
                if x is None or b0 not in x.index or bx not in x.index or not np.isfinite(C.at[pdt, s]):
                    continue
                pc = C.at[pdt, s]; p0 = x.at[b0, "Close"]; px = x.at[bx, "Close"]
                m0.append(p0 / pc - 1); r0.append(px / p0 - 1); endg.append(px / pc - 1)
                if b1 in x.index:
                    p1 = x.at[b1, "Close"]; m1.append(p1 / pc - 1); r1.append(px / p1 - 1)
            if len(m0) < 5:
                continue
            cand = sorted([s for s in mem if s in I and b0 in I[s].index and bx in I[s].index and bool(trend.at[pdt, s]) and np.isfinite(r63.at[pdt, s])],
                          key=lambda s: -r63.at[pdt, s])[:3]
            t3 = float(np.mean([I[s].at[bx, "Close"] / I[s].at[b0, "Close"] - 1 for s in cand])) if cand else None
            st[sec] = dict(m0=np.mean(m0), m1=np.mean(m1) if m1 else None, r0=np.mean(r0) - 0.001, r1=(np.mean(r1) - 0.001) if r1 else None,
                           end=np.mean(endg), top3=(t3 - 0.001) if t3 is not None else None)
        rows.append(dict(day=str(dy), ig=ig, ig1=ig1, st=st))
    res = dict(method=__doc__, days=len(rows), out={})

    def summ(label, picks, key="r0"):
        v = [p[key] for p in picks if p.get(key) is not None]
        if not v:
            return
        v = np.array(v); o = dict(n=len(v), avg=round(float(v.mean()) * 100, 3), win=round(float((v > 0).mean()) * 100), total_if_daily=None)
        res["out"][label] = o; print(f"R| {label} | {o}", flush=True)

    gates = {"all days": lambda r: True, "Nifty green 09:30": lambda r: r["ig"]["Nifty 50"] > 0,
             "all 4 indices green 09:30": lambda r: all(v is not None and v > 0 for v in r["ig"].values()),
             "Nifty red 09:30": lambda r: r["ig"]["Nifty 50"] < 0}
    for gname, g in gates.items():
        R = [r for r in rows if g(r)]
        res["out"][f"{gname} | days"] = len(R)
        gs = [s for r in R for s in r["st"].values() if s["m0"] > 0]; rs = [s for r in R for s in r["st"].values() if s["m0"] < 0]
        if gs:
            p_end = float(np.mean([s["end"] > 0 for s in gs])) * 100; p_end_r = float(np.mean([s["end"] > 0 for s in rs])) * 100 if rs else None
            print(f"R| {gname} ({len(R)} days) | green-at-09:30 sectors that END green: {p_end:.0f}% (red-at-09:30 that end green {p_end_r if p_end_r is None else round(p_end_r)}%)", flush=True)
            res["out"][f"{gname} | P(end green | green at 09:30)"] = round(p_end)
        summ(f"{gname} | every green sector, buy 09:30 -> close", gs)
        summ(f"{gname} | every red sector, buy 09:30 -> close", rs)
        best = [max(r["st"].values(), key=lambda s: s["m0"]) for r in R if r["st"]]
        summ(f"{gname} | strongest sector at 09:30 -> close", best)
        summ(f"{gname} | strongest sector, top 3 stocks -> close", best, key="top3")
        conf = [s for r in R for s in r["st"].values() if s["m0"] > 0 and s["m1"] is not None and s["m1"] > s["m0"] and r["ig1"]["Nifty 50"] and r["ig1"]["Nifty 50"] > 0]
        summ(f"{gname} | green sector still rising at 10:15 + Nifty green 10:15, buy 10:15 -> close", conf, key="r1")
    os.makedirs("data/research", exist_ok=True)
    json.dump(res, open("data/research/open_green.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
