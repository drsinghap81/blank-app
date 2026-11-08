"""Paper trading of the US / ASX trade plan (no broker, no real orders).

Usage: python tools/paper_global.py US|ASX
Each run (after that market's evening scans and trade_plan.py):
  1. Fills orders queued by the previous run on the first daily bar after the plan date (Yahoo):
       BUY next open (ATH breakout, 9/21): filled at the open if the open is at or below the plan limit (close + 1%), else "missed".
       BUY-STOP (ATH near trigger, day order): filled if the high reaches the trigger, at max(open, trigger) if that is within the
       limit (trigger + 1%); otherwise not triggered / missed.
       SELL next open (exit signals): filled at the open.
  2. 9/21 positions: the plan stop is a resting stop -> exit at min(open, stop) when the day's low touches it.
     ATH positions exit on the scan's "exit next open" (weekly close below the 30-week SMA), queued as a SELL.
  3. Sizing at fill time, from paper equity: 1% risk to the stop, max 10% of equity, max 10 positions, cash only. Cost 0.1% a side.
  4. Marks to market at the scan's close, records equity vs the index (S&P 500 / ASX 200), then queues tomorrow's orders:
     exits for held symbols and the plan's top-10 buys not already held.
State: data/scan/<us|asx>/paper.json (start capital 100,000 in the market's currency).
"""
import json
import math
import sys
from datetime import date, datetime, timezone

import pandas as pd

DIR = {"US": "data/scan/us/", "ASX": "data/scan/asx/"}
SUF = {"US": "", "ASX": ".AX"}
BENCH = {"US": "^GSPC", "ASX": "^AXJO"}
START = 100_000.0
RISK, CAP, MAXPOS, COST = 0.01, 0.10, 10, 0.001


def load(p, d):
    try:
        return json.load(open(p))
    except Exception:  # noqa: BLE001
        return d


def ytk(s, mk):
    return (s.replace("/", "-").replace(".", "-") if mk == "US" else s) + SUF[mk]


def bars(tickers):
    import yfinance as yf
    out = {}
    if not tickers:
        return out
    d = yf.download(sorted(set(tickers)), period="1mo", interval="1d", auto_adjust=False, progress=False, group_by="ticker", threads=True)
    for t in set(tickers):
        try:
            x = d[t] if isinstance(d.columns, pd.MultiIndex) else d
            x = x.dropna(subset=["Open", "High", "Low", "Close"])
            x.index = [str(i.date()) for i in x.index]
            out[t] = x
        except Exception:  # noqa: BLE001
            pass
    return out


def equity(S, px):
    return S["cash"] + sum(p["qty"] * px.get(sym, p["last"]) for sym, p in S["pos"].items())


def main(mk):
    D = DIR[mk]; path = D + "paper.json"
    P = load(D + "trade_plan.json", {})
    asof = str(P.get("asof") or "")[:10]
    if not asof:
        print("no plan"); return
    S = load(path, None) or {"market": mk, "start": asof, "capital": START, "cash": START, "pos": {}, "queue": [], "closed": [],
                             "log": [], "equity": [], "rules": "1% risk to the stop, max 10% a stock, 10 positions, fills at the next open, 0.1% cost a side"}
    if S["equity"] and S["equity"][-1][0] >= asof:
        print("already ran for", asof); return
    syms = {q["symbol"] for q in S["queue"]} | set(S["pos"])
    B = bars([ytk(s, mk) for s in syms] + [BENCH[mk]])
    nxt = lambda s, d0: next(((d, r) for d, r in B.get(ytk(s, mk), pd.DataFrame()).iterrows() if d0 < d <= asof), (None, None))  # noqa: E731
    events = []
    # 1. sells first (frees cash and slots), then buys in plan rank order
    for q in [q for q in S["queue"] if q["side"] == "SELL"]:
        p = S["pos"].get(q["symbol"])
        if not p:
            continue
        d, r = nxt(q["symbol"], q["date"])
        if d is None:
            S.setdefault("carry", []).append(q); continue
        px = float(r["Open"]) * (1 - COST)
        S["cash"] += p["qty"] * px; del S["pos"][q["symbol"]]
        S["closed"].append(dict(symbol=q["symbol"], system=p["system"], entry_date=p["date"], entry=p["entry"], exit_date=d,
                                exit=round(px, 4), qty=p["qty"], ret=round(px / p["entry"] - 1, 4), R=round((px - p["entry"]) / (p["entry"] - p["stop0"]), 2),
                                why=q.get("why", "exit signal")))
        events.append(f"{d} SELL {p['qty']} {q['symbol']} @ {px:.2f} ({q.get('why', '')})")
    eq0 = equity(S, {})
    for q in sorted([q for q in S["queue"] if q["side"] == "BUY"], key=lambda q: q.get("rank", 99)):
        s = q["symbol"]
        if s in S["pos"]:
            continue
        d, r = nxt(s, q["date"])
        if d is None:
            continue
        o, h = float(r["Open"]), float(r["High"])
        if q["kind"] == "ATH_STOP":
            if h < q["trigger"]:
                events.append(f"{d} {s} buy-stop {q['trigger']:.2f} not triggered"); continue
            fill = max(o, q["trigger"])
        else:
            fill = o
        if fill > q["limit"]:
            events.append(f"{d} {s} missed: opened {o:.2f} above the limit {q['limit']:.2f}"); continue
        if fill <= q["stop"]:
            events.append(f"{d} {s} skipped: opened below the stop"); continue
        if len(S["pos"]) >= MAXPOS:
            events.append(f"{d} {s} skipped: 10 positions held"); continue
        qty = math.floor(min(RISK * eq0 / (fill - q["stop"]), CAP * eq0 / fill, S["cash"] / (fill * (1 + COST))))
        if qty <= 0:
            events.append(f"{d} {s} skipped: no cash"); continue
        cost = qty * fill * (1 + COST); S["cash"] -= cost
        S["pos"][s] = dict(qty=qty, entry=round(fill * (1 + COST), 4), date=d, stop=q["stop"], stop0=q["stop"], system=q["system"], kind=q["kind"], last=fill)
        events.append(f"{d} BUY {qty} {s} @ {fill:.2f} ({q['system']}, stop {q['stop']:.2f})")
    # 2. 9/21 resting stops on every bar since entry (or the last run)
    last = S["equity"][-1][0] if S["equity"] else S["start"]
    for s, p in list(S["pos"].items()):
        if p["system"] != "9/21 trend":
            continue
        X = B.get(ytk(s, mk))
        if X is None:
            continue
        for d, r in X.iterrows():
            if d <= last or d < p["date"]:
                continue
            if d > asof:
                break
            if float(r["Low"]) <= p["stop"]:
                px = min(float(r["Open"]), p["stop"]) * (1 - COST)
                S["cash"] += p["qty"] * px; del S["pos"][s]
                S["closed"].append(dict(symbol=s, system=p["system"], entry_date=p["date"], entry=p["entry"], exit_date=d, exit=round(px, 4),
                                        qty=p["qty"], ret=round(px / p["entry"] - 1, 4), R=round((px - p["entry"]) / (p["entry"] - p["stop0"]), 2), why="stop hit"))
                events.append(f"{d} STOP {p['qty']} {s} @ {px:.2f}")
                break
    # 3. mark to market
    px = {}
    for s, p in S["pos"].items():
        X = B.get(ytk(s, mk))
        if X is not None and len(X[X.index <= asof]):
            px[s] = float(X[X.index <= asof]["Close"].iloc[-1]); p["last"] = round(px[s], 4)
    bx = B.get(BENCH[mk]); bench = float(bx[bx.index <= asof]["Close"].iloc[-1]) if bx is not None and len(bx[bx.index <= asof]) else None
    S["equity"].append([asof, round(equity(S, px), 2), bench])
    # 4. tomorrow's queue
    Q = S.pop("carry", [])
    for e in P.get("exits") or []:
        if e["symbol"] in S["pos"] and S["pos"][e["symbol"]]["system"] == e["system"]:
            Q.append(dict(side="SELL", symbol=e["symbol"], date=asof, why=e.get("why")))
    for r in P.get("top") or []:
        if r["symbol"] in S["pos"]:
            continue
        Q.append(dict(side="BUY", symbol=r["symbol"], date=asof, kind=r["kind"], system=r["system"], rank=r.get("rank", 99),
                      trigger=r.get("trigger"), limit=r["price"], stop=r["stop"]))
    S["queue"] = Q
    S["log"] = (events + S["log"])[:200]
    S["generated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    c = S["closed"]
    b0 = next((v[2] for v in S["equity"] if v[2]), None)
    S["stats"] = dict(days=len(S["equity"]), equity=S["equity"][-1][1], ret=round(S["equity"][-1][1] / S["capital"] - 1, 4),
                      bench_ret=round(bench / b0 - 1, 4) if bench and b0 else None, closed=len(c),
                      win=round(sum(x["ret"] > 0 for x in c) / len(c), 3) if c else None, avg=round(sum(x["ret"] for x in c) / len(c), 4) if c else None,
                      avgR=round(sum(x["R"] for x in c) / len(c), 2) if c else None, open=len(S["pos"]),
                      maxdd=round(min(0, min(v[1] / max(w[1] for w in S["equity"][:i + 1]) - 1 for i, v in enumerate(S["equity"]))), 4))
    json.dump(S, open(path, "w"), separators=(",", ":"), default=str)
    print(mk, asof, "events", len(events), *events[:20], "stats", S["stats"], "queued", len(Q), sep="\n  ")


if __name__ == "__main__":
    for m in sys.argv[1:] or ["US", "ASX"]:
        main(m)
