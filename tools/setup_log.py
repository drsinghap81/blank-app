"""Today's setups, tracked forward (11 Nov 2026): every setup the app shows is logged once, then followed night by night
on closing prices, so the live record can be checked against the backtests.

Per setup: first day shown, system, entry (the limit price shown, or the trigger for buy-stops once a close reaches it),
stop, and the return from entry after 1 / 5 / 20 / 60 trading days, best and worst close, and how it ended:
  stop  - a close at or below the stop (close-based; a GTT can fill lower). If the stop had been trailed up first, 'trail' = True
  target- a close at or above the plan target (retest / pattern setups have one; Momentum and 9/21 don't)
  exit  - the system's sell signal (the plan's exit list) for that stock
  open  - still running (tracked up to 120 trading days)
  waiting / expired - buy-stop not reached (expires after 20 trading days)
Trailing stop (22 Nov 2026, Amritpal: "it should track target hit, SL hit, SL trailed"): ts starts at the plan stop and only moves up -
  Momentum: the 30-week average of weekly closes (its exit line); Cup 9/21 / 9/21: a 21-day EMA kept night by night from the closes.
  tr = how many times it moved up. A stop hit after a trail is a trailed-stop exit.
Idempotent per scan date: the plan job runs several times a night; a night only advances once.
Writes data/scan[/us|/asx]/setup_log.json. No orders, no account data: scan output only."""
import json
import os
import sys
from datetime import datetime, timezone

DIR = {"NSE": "data/scan/", "US": "data/scan/us/", "ASX": "data/scan/asx/", "UK": "data/scan/uk/"}
STOPK = ("ATH_STOP", "TF_STOP", "VCP_STOP")
HZ = (1, 5, 20, 60)
MAX_DAYS, WAIT_DAYS = 120, 20


def load(p, d=None):
    try:
        return json.load(open(p))
    except Exception:  # noqa: BLE001
        return d if d is not None else {}


def prices(D, mk):
    """Last close per symbol from the evening files (NSE: every stock; US/ASX: the scanned stocks)."""
    px = {}
    for r in (load(D + "trend_scan.json").get("rows") or []) + (load(D + "trend_scan.json").get("early") or []):
        if r.get("close"):
            px[r["symbol"]] = float(r["close"])
    A = load(D + "ath.json")
    for k in ("tracked", "near", "breakouts"):
        for r in A.get(k) or []:
            if r.get("close"):
                px[r["symbol"]] = float(r["close"])
    if mk == "NSE":
        for s, v in (load(D + "nse_close.json").get("prices") or {}).items():
            if v and v[0]:
                px[s] = float(v[0])
    return px


def trail(r, c, W):
    """move the row's stop up (never down) to its system's line"""
    ts = r.get("ts", r["s"]); lvl = None
    if r.get("b") == "mom":
        v = (W.get("s") or {}).get(r["sym"])
        if v and len(v) >= 30:
            lvl = sum(v[-30:]) / 30
    else:
        e = r.get("ema") or r["s"]; e = e + 2 / 22 * (c - e); r["ema"] = round(e, 2); lvl = e
    if lvl and lvl > ts * 1.005 and lvl < c:
        r["ts"] = round(lvl, 2); r["tr"] = r.get("tr", 0) + 1


def main(mk):
    D = DIR[mk]; P = load(D + "trade_plan.json"); W = load(D + "stock_weekly.json")
    if not P.get("asof"):
        return
    L = load(D + "setup_log.json", dict(market=mk, asof=None, since=None, rows=[]))
    asof = str(P["asof"])[:10]; px = prices(D, mk)
    live = {b["key"] for b in P.get("buckets") or [] if (b.get("pct") or 0) > 0} | {"vcp"}
    exits = {e["symbol"]: e for e in P.get("exits") or []}
    rows = L["rows"]; open_syms = {r["sym"] for r in rows if r["st"] in ("open", "waiting")}
    new_night = L.get("asof") != asof
    # 1. advance every running setup one trading day (once per scan date)
    if new_night:
        for r in rows:
            c = px.get(r["sym"])
            if r["st"] not in ("open", "waiting") or not c:
                continue
            if r["st"] == "waiting":
                r["wd"] = r.get("wd", 0) + 1
                if c >= r["trig"]:
                    r.update(st="open", e=r["trig"], d0=asof, n=0)
                elif r["wd"] >= WAIT_DAYS:
                    r["st"] = "expired"; continue
                else:
                    continue
            r["n"] = r.get("n", 0) + 1; ret = round((c / r["e"] - 1) * 100, 2)
            trail(r, c, W)
            r["ret"] = ret; r["hi"] = max(r.get("hi", ret), ret); r["lo"] = min(r.get("lo", ret), ret)
            for h in HZ:
                if r["n"] == h:
                    r[f"r{h}"] = ret
            if r.get("t") and c >= r["t"]:
                r.update(st="target", end=asof)
            elif c <= r.get("ts", r["s"]):
                r.update(st="stop", end=asof, trail=r.get("ts", r["s"]) > r["s"])
            elif r["sym"] in exits and (not exits[r["sym"]].get("system") or exits[r["sym"]]["system"] == r["sys"]):
                r.update(st="exit", end=asof)
            elif r["n"] >= MAX_DAYS:
                r.update(st="done", end=asof)
    # 2. log setups shown tonight that are not already being followed
    # 22 Nov 2026 (Amritpal: "track all systems very closely - forward testing - even if I haven't executed"): every system's
    # setups are logged, switched-off ones too (on = False), plus bottom-pattern breakouts from patterns.json
    pats = [dict(symbol=r["symbol"], bucket="pt", system="Bottom pattern", kind="PATTERN", price=r.get("close"), stop=r.get("stop"), target=r.get("target"))
            for r in (load(D + "patterns.json").get("rows") or []) if r.get("kind") != "index" and r.get("status") == "breakout" and (r.get("days_since") or 0) <= 1]
    flg = [dict(symbol=r["symbol"], bucket="fl", system="Flag / pennant", kind="FLAG", price=r.get("entry"), stop=r.get("stop"), target=r.get("target"))
           for r in (load(D + "flags.json").get("rows") or []) if r.get("status") == "breakout" and (r.get("days_since") or 0) == 0]
    for x in (P.get("top") or []) + (P.get("swing") or []) + (P.get("more") or []) + pats + flg:
        b = x.get("bucket") or ""
        if not b or x["symbol"] in open_syms or not x.get("stop"):
            continue
        stopk = x.get("kind") in STOPK
        e = float(x.get("trigger") or x.get("price") or 0)
        if not e or e <= x["stop"]:
            continue
        rows.append(dict(id=x.get("id"), sym=x["symbol"], sys=x.get("system"), kind=x.get("kind"), b=b, d=asof, s=round(float(x["stop"]), 2),
                         st="waiting" if stopk else "open", trig=round(e, 2) if stopk else None, e=None if stopk else round(e, 2),
                         d0=None if stopk else asof, n=0, ts=round(float(x["stop"]), 2), tr=0,
                         t=round(float(x["target"]), 2) if x.get("target") else None, on=b in live))
        open_syms.add(x["symbol"])
    L.update(asof=asof, since=L.get("since") or asof, generated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), rows=rows[-600:])
    # 3. summary for the app
    ent = [r for r in rows if r.get("e") and r.get("n", 0) > 0]
    summ = dict(shown=len(rows), entered=len(ent), open=sum(r["st"] == "open" for r in rows), stopped=sum(r["st"] == "stop" for r in rows),
                target=sum(r["st"] == "target" for r in rows), trailed=sum(bool(r.get("tr")) for r in rows),
                exited=sum(r["st"] == "exit" for r in rows), waiting=sum(r["st"] == "waiting" for r in rows))
    for h in HZ:
        v = [r[f"r{h}"] for r in ent if f"r{h}" in r]
        summ[f"d{h}"] = dict(n=len(v), avg=round(sum(v) / len(v), 2) if v else None, win=round(100 * sum(x > 0 for x in v) / len(v)) if v else None)
    done = [r["ret"] for r in rows if r["st"] in ("stop", "exit", "done", "target") and "ret" in r]
    summ["closed"] = dict(n=len(done), avg=round(sum(done) / len(done), 2) if done else None, win=round(100 * sum(x > 0 for x in done) / len(done)) if done else None)
    L["summary"] = summ
    json.dump(L, open(D + "setup_log.json", "w"), separators=(",", ":"))
    print(mk, "setup log:", summ)


if __name__ == "__main__":
    for m in (sys.argv[1:] or ["NSE"]):
        if os.path.exists(DIR[m] + "trade_plan.json"):
            main(m)
