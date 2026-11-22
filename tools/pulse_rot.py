"""Pulse rotation - weekly picks (22 Nov 2026, Amritpal: "yes, but we can try live too with a small allocation along").

Tested in tools/research/pulse_system.py (claude/pulse-rotation-stock-system-test.md): NSE 2016-26, Monday-open fills, 0.2% a side,
34.5%/yr, worst fall -35.9%, last 1/2/3 years +20.0 / +16.0 / +40.0% (survivors - flatters the absolute numbers).
Rules (same as the test):
  industries  NSE official basic industries with 3+ liquid stocks; Pulse = share of the liquid members trending (relative score
              > 100, EMA9 > EMA21, above a rising 150-day SMA, within 25% of the 52-week high), averaged over 21 sessions;
              rotation = weekly RS vs Nifty 50 of the equal-weight industry index (RS-ratio 10 weeks, momentum 3 weeks).
              Selected = top 10% by Pulse AND momentum >= 100 (Leading or Improving).
  stocks      the 10 strongest TRENDING stocks of the selected industries by 3-month return; a holding stays while it ranks in the
              top 20 and its industry stays selected; equal weight; cash when fewer qualify.
  timing      decided at the Friday close, bought / sold at Monday's open (weekly rebalance).
Writes data/scan/pulse_rot.json: picks (holdings), buys, sells, ranked top 20, selected industries, and a forward-test ledger
(equal weight, Friday close to Friday close of last week's holdings) - kept across runs. Only Fridays (or FORCE=1) rebalance;
other days just refresh the ledger mark."""
import json
import os
import sys
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nse_bhav; nse_bhav.install()  # noqa: E402,E702

OUT = "data/scan/pulse_rot.json"
MINVAL, MINPX, N, BUF = 1e7, 50, 10, 20


def light():
    """Traffic light as the app shows it (same as tools/ath_scan.light_level): 9/21 breadth sells > buys over 10 sessions AND Nifty
    below its 30-week average = RED; one of them = AMBER."""
    try:
        br = json.load(open("data/scan/trend_scan.json")).get("breadth") or {}
        wi = (json.load(open("data/scan/world.json")).get("indices") or {}).get("^NSEI") or {}
        b = br.get("buys10") is not None and br.get("sells10", 0) > br.get("buys10", 0); i = wi.get("up") is False
        return "RED" if b and i else "AMBER" if b or i else "GREEN"
    except Exception:  # noqa: BLE001
        return None


def main():
    G = json.load(open("data/scan/group_pulse.json"))["nse"]["rows"]
    IND = {}
    for r in G:
        liq = [m["symbol"] for m in r["members"] if m.get("liquid")]
        if len(liq) >= 3:
            IND[r["basic"]] = liq
    syms = sorted({s for v in IND.values() for s in v})
    C, V = {}, {}
    for a in range(0, len(syms), 100):
        ch = [s + ".NS" for s in syms[a:a + 100]]
        for k in range(3):
            try:
                d = yf.download(ch, period="2y", interval="1d", progress=False, group_by="column", auto_adjust=True, threads=True)
                got = [t for t in ch if t in d["Close"].columns and d["Close"][t].notna().sum() > 200]
                for t in got:
                    C[t[:-3]] = d["Close"][t]; V[t[:-3]] = d["Volume"][t]
                if len(got) >= 0.9 * len(ch):
                    break
            except Exception as e:  # noqa: BLE001
                print("retry", e)
            time.sleep(15 * (k + 1))
    b = yf.download("^NSEI", period="2y", interval="1d", progress=False, auto_adjust=True)["Close"]
    b = b.iloc[:, 0] if isinstance(b, pd.DataFrame) else b
    C = pd.DataFrame(C).sort_index(); C.index = pd.to_datetime(C.index).tz_localize(None); V = pd.DataFrame(V).reindex(C.index)
    b.index = pd.to_datetime(b.index).tz_localize(None); nifty = b.reindex(C.index).ffill()
    if C.shape[1] < 0.8 * len(syms):
        raise SystemExit(f"only {C.shape[1]} of {len(syms)} stocks downloaded - keeping the previous file")
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
    fri = sorted({C.index[C.index.get_indexer([d], method="pad")[0]] for d in idx.resample("W-FRI").last().index if d >= C.index[0]})
    if fri[-1] != C.index[-1]:
        fri.append(C.index[-1])                     # this week so far (a mid-week run reads the latest close)
    W = idx.loc[fri]; NW = nifty.loc[fri]; PW = pul.loc[fri]
    RS = 100 * W.div(NW, axis=0); ratio = 100 * RS / RS.rolling(10).mean(); mom = (100 * ratio / ratio.shift(1)).rolling(3).mean()
    d = fri[-1]
    pct = PW.loc[d].rank(pct=True)
    sel = [k for k in PW.columns if pct.get(k, 0) >= 0.9 and np.isfinite(mom.loc[d, k]) and mom.loc[d, k] >= 100]
    cand = [s for k in sel for s in mem[k] if bool(tr.loc[d, s])]
    rk = sorted(set(cand), key=lambda s: -(r63.loc[d, s] if np.isfinite(r63.loc[d, s]) else -9))
    try:
        prev = json.load(open(OUT))
    except Exception:  # noqa: BLE001
        prev = {}
    asof = str(d.date()); friday = d.weekday() == 4 or os.environ.get("FORCE") == "1"
    held_prev = prev.get("picks") or []
    lt = light()
    if friday and prev.get("decided") != asof:
        top2 = set(rk[:BUF]); keep = [s for s in held_prev if s in top2]
        for s in rk:
            if len(keep) >= N:
                break
            if s not in keep:
                keep.append(s)
        if lt == "RED":       # 23 Nov 2026 (tested, claude/pulse-rotation-stock-system-test.md): RED traffic light at the Friday close -> no basket that week
            keep = []
        picks, buys, sells, decided = keep, [s for s in keep if s not in held_prev], [s for s in held_prev if s not in keep], asof
    else:
        picks, buys, sells, decided = held_prev, prev.get("buys") or [], prev.get("sells") or [], prev.get("decided")
    s2i = {s: k for k, v in mem.items() for s in v}
    # forward-test ledger: equal weight, Friday close -> Friday close of last week's holdings (no costs; a paper mark)
    led = prev.get("ledger") or []
    if friday and (not led or led[-1]["date"] != asof):
        if led and led[-1].get("holdings"):
            p0d = pd.Timestamp(led[-1]["date"])
            rr = [float(C.loc[d, s] / C.loc[p0d, s] - 1) for s in led[-1]["holdings"] if s in C.columns and p0d in C.index and np.isfinite(C.loc[d, s]) and np.isfinite(C.loc[p0d, s])]
            r_ = float(np.mean(rr)) if rr else 0.0
            nr = float(nifty.loc[d] / nifty.loc[p0d] - 1) if p0d in nifty.index else None
        else:
            r_, nr = 0.0, 0.0
        eq = (led[-1]["equity"] if led else 1.0) * (1 + r_); neq = (led[-1].get("nifty_eq", 1.0) if led else 1.0) * (1 + (nr or 0))
        led.append(dict(date=asof, holdings=picks, week_ret=round(r_ * 100, 2), equity=round(eq, 4), nifty_eq=round(neq, 4)))
    rows = [dict(symbol=s, industry=s2i.get(s), close=round(float(C.loc[d, s]), 2), r3m=round(float(r63.loc[d, s]) * 100, 1),
                 rank=rk.index(s) + 1 if s in rk else None) for s in picks]
    out = dict(generated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), asof=asof, decided=decided, picks=picks, buys=buys,
               sells=sells, light=lt, red_skip=bool(lt == "RED" and friday), rows=rows, ranked=rk[:BUF], industries=[dict(name=k, pulse=round(float(PW.loc[d, k]), 1), momentum=round(float(mom.loc[d, k]), 2),
                                                                           ratio=round(float(ratio.loc[d, k]), 2)) for k in sel],
               ledger=led[-160:], started=(led[0]["date"] if led else asof),
               rule="Each Friday close: NSE industries in the top 10% by 1-month Pulse AND rotation Leading/Improving; hold the 10 strongest trending stocks "
                    "of those industries by 3-month return (a holding stays while it ranks in the top 20 and its industry stays selected); equal weight; "
                    "buy / sell at Monday's open. If the traffic light is RED at the Friday close: no basket that week (all cash).",
               test="NSE 2016-26 (survivors), Monday-open fills, 0.2% a side: 34.5%/yr, worst fall -35.9%; last 1/2/3 years +20.0/+16.0/+40.0%. "
                    "Same top-10 pick from any industry 18.9%; strong Pulse without rotation 27.8%. ~54x turnover a year. "
                    "With the RED-light skip (cash that week): 37.4%/yr, worst fall -23.0%, last 1/3/5 years +19.7/+40.6/+45.9%.")
    json.dump(out, open(OUT, "w"), indent=1)
    print("pulse rotation", asof, "decided", decided, "industries", sel, "picks", picks, "buys", buys, "sells", sells)


if __name__ == "__main__":
    main()
