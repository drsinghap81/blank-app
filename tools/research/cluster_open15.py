"""First-15-minute leading cluster -> top 3 stocks basket for the day (23 Nov 2026, Amritpal: "after the open and 15 minutes, check which
cluster - sector, industry or theme - is outperforming, take the top 3 stocks as per our system and create a basket for that day").

Earlier (claude/industry-basket-intraday-test.md, 20 Nov): first-HOUR top industries, all their stocks, intraday -> lost (-36% to -75%
of capital over 3 years). This pilot is the 15-minute version with OUR stock ranking.
Data: Yahoo 15-minute bars (last ~60 sessions only) for the liquid NSE stocks; daily bars for the ranking.
Clusters: NSE official basic industries (3+ liquid members), NSE sectors, Nifty themes (group_pulse.json).
Each day at 09:30 (close of the 09:15-09:30 bar): cluster move = average of its members' move from yesterday's close; leading cluster
= highest move minus Nifty's move (needs 3+ members priced). Top 3 = members that are TRENDING at yesterday's close (Pulse rule:
EMA9 > EMA21, close above a rising 150-day SMA, within 25% of the 52-week high) ranked by 3-month return; fewer if fewer trend.
Buy at 09:30's close. Exits: intraday = 15:15 bar close (0.10% cost); next day close; 5 sessions (0.40% cost).
Controls: the same top-3 rule in a RANDOM cluster each day; the 3 strongest trending stocks of the whole market (no cluster);
the leading cluster's members equal weight (no ranking).
Output data/research/cluster_open15.json (per day and per level)."""
import json
import os
import time

import numpy as np
import pandas as pd
import yfinance as yf

PILOT = bool(os.environ.get("PILOT"))


def dl(tick, **kw):
    out = {}
    for a in range(0, len(tick), 80):
        ch = tick[a:a + 80]
        for k in range(3):
            try:
                d = yf.download(ch, progress=False, group_by="column", auto_adjust=True, threads=True, **kw); break
            except Exception as e:  # noqa: BLE001
                print("retry", e); time.sleep(15); d = None
        if d is None or d.empty:
            continue
        for t in ch:
            try:
                x = pd.DataFrame({k: d[k][t] for k in ("Open", "High", "Low", "Close", "Volume")}).dropna(subset=["Close"])
                if len(x):
                    out[t[:-3]] = x
            except Exception:  # noqa: BLE001
                pass
        time.sleep(2)
    return out


def main():
    G = json.load(open("data/scan/group_pulse.json"))
    CL = {}
    for r in G["nse"]["rows"]:
        liq = [m["symbol"] for m in r["members"] if m.get("liquid")]
        if len(liq) >= 3:
            CL[("industry", r["basic"])] = liq
            CL.setdefault(("sector", r.get("sector") or r.get("macro")), []).extend(liq)
    for t in G.get("themes") or []:
        liq = [m["symbol"] for m in t["members"]]
        if len(liq) >= 3:
            CL[("theme", t["group"])] = liq
    syms = sorted({s for v in CL.values() for s in v})
    if PILOT:
        syms = syms[:300]; CL = {k: [s for s in v if s in set(syms)] for k, v in CL.items()}
    print("R| clusters", {lv: sum(1 for k in CL if k[0] == lv) for lv in ("sector", "industry", "theme")}, "stocks", len(syms), flush=True)
    I = dl([s + ".NS" for s in syms], period="60d", interval="15m")
    D = dl([s + ".NS" for s in syms], period="2y", interval="1d")
    nif15 = yf.download("^NSEI", period="60d", interval="15m", progress=False, auto_adjust=True)["Close"].squeeze().dropna()
    nifd = yf.download("^NSEI", period="2y", interval="1d", progress=False, auto_adjust=True)["Close"].squeeze().dropna()
    for X in (I,):
        for k, x in X.items():
            x.index = x.index.tz_convert("Asia/Kolkata").tz_localize(None) if x.index.tz is not None else x.index
    nif15.index = nif15.index.tz_convert("Asia/Kolkata").tz_localize(None) if nif15.index.tz is not None else nif15.index
    C = pd.DataFrame({k: v.Close for k, v in D.items()}); C.index = pd.to_datetime(C.index).tz_localize(None)
    e9 = C.ewm(span=9, adjust=False).mean(); e21 = C.ewm(span=21, adjust=False).mean(); s150 = C.rolling(150).mean()
    hi = C.rolling(250, min_periods=120).max(); trend = (e9 > e21) & (C > s150) & (s150 > s150.shift(20)) & (C >= 0.75 * hi)
    r63 = C / C.shift(63) - 1
    days = sorted({t.date() for t in nif15.index})
    rng = np.random.default_rng(0); rows = []
    for dy in days:
        dts = pd.Timestamp(dy)
        prev_i = C.index.searchsorted(dts) - 1
        if prev_i < 0:
            continue
        pd_ = C.index[prev_i]; nxt = C.index[C.index > dts]
        b0 = pd.Timestamp(f"{dy} 09:15"); bx = pd.Timestamp(f"{dy} 15:15")
        mv, ent, ex = {}, {}, {}
        for s, x in I.items():
            if b0 in x.index and bx in x.index and pd_ in C.index and np.isfinite(C.at[pd_, s]):
                mv[s] = x.at[b0, "Close"] / C.at[pd_, s] - 1; ent[s] = x.at[b0, "Close"]; ex[s] = x.at[bx, "Close"]
        if len(mv) < 50 or b0 not in nif15.index:
            continue
        nm = nif15.at[b0] / float(nifd[nifd.index < dts].iloc[-1]) - 1
        def ret(sel):
            if not sel:
                return None
            r = dict(intraday=float(np.mean([ex[s] / ent[s] - 1 for s in sel])) - 0.001)
            for h_, lab in ((1, "next_close"), (5, "d5")):
                v = [C.at[nxt[h_ - 1], s] / ent[s] - 1 for s in sel if len(nxt) >= h_ and np.isfinite(C.at[nxt[h_ - 1], s])] if len(nxt) >= h_ else []
                r[lab] = float(np.mean(v)) - 0.004 if v else None
            r["names"] = sel
            return r
        def top3(mem):
            c = [s for s in mem if s in mv and bool(trend.at[pd_, s]) and np.isfinite(r63.at[pd_, s])]
            return sorted(c, key=lambda s: -r63.at[pd_, s])[:3]
        for lv in ("sector", "industry", "theme"):
            sc = {k: np.mean([mv[s] for s in v if s in mv]) - nm for k, v in CL.items() if k[0] == lv and sum(s in mv for s in v) >= 3}
            if not sc:
                continue
            best = max(sc, key=sc.get); rk = list(sc)[rng.integers(len(sc))]
            rows.append(dict(day=str(dy), level=lv, cluster=best[1], lead=round(sc[best] * 100, 2), top3=ret(top3(CL[best])),
                             all_members=ret([s for s in CL[best] if s in mv]), random_top3=ret(top3(CL[rk]))))
        allt = sorted([s for s in mv if bool(trend.at[pd_, s]) and np.isfinite(r63.at[pd_, s])], key=lambda s: -r63.at[pd_, s])[:3]
        rows.append(dict(day=str(dy), level="market", cluster="whole market", top3=ret(allt)))
    res = dict(method=__doc__, days=len({r["day"] for r in rows}), levels={})
    for lv in ("sector", "industry", "theme", "market"):
        R = [r for r in rows if r["level"] == lv]
        o = {}
        for basket in ("top3", "all_members", "random_top3"):
            for ex_ in ("intraday", "next_close", "d5"):
                v = [r[basket][ex_] for r in R if r.get(basket) and r[basket].get(ex_) is not None]
                if v:
                    v = np.array(v); o[f"{basket} | {ex_}"] = dict(days=len(v), avg=round(float(v.mean()) * 100, 2), win=round(float((v > 0).mean()) * 100),
                                                                  total=round(float(np.prod(1 + v) - 1) * 100, 1) if ex_ == "intraday" else None)
        res["levels"][lv] = o
        for k, v in o.items():
            print(f"R| {lv} | {k} | {v}", flush=True)
    res["recent"] = rows[-12:]
    for r in rows[-8:]:
        print("R| day", r["day"], r["level"], r["cluster"], r.get("lead"), (r.get("top3") or {}).get("names"), round(((r.get("top3") or {}).get("intraday") or 0) * 100, 2), flush=True)
    os.makedirs("data/research", exist_ok=True)
    json.dump(res, open("data/research/cluster_open15" + ("_pilot" if PILOT else "") + ".json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
