"""Today's setups, tracked forward (11 Nov 2026): every setup the app shows is logged once, then followed night by night
on closing prices, so the live record can be checked against the backtests.

Per setup: first day shown, system, entry (the limit price shown, or the trigger for buy-stops once a close reaches it),
stop, and the return from entry after 1 / 5 / 20 / 60 trading days, best and worst close, and how it ended:
  stop  - a close at or below the plan stop (close-based; a GTT can fill lower)
  exit  - the system's sell signal (the plan's exit list) for that stock
  open  - still running (tracked up to 120 trading days)
  waiting / expired - buy-stop not reached (expires after 20 trading days)
Idempotent per scan date: the plan job runs several times a night; a night only advances once.
Writes data/scan[/us|/asx]/setup_log.json. No orders, no account data: scan output only."""
import json
import os
import sys
from datetime import datetime, timezone

DIR = {"NSE": "data/scan/", "US": "data/scan/us/", "ASX": "data/scan/asx/"}
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


def main(mk):
    D = DIR[mk]; P = load(D + "trade_plan.json")
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
            r["ret"] = ret; r["hi"] = max(r.get("hi", ret), ret); r["lo"] = min(r.get("lo", ret), ret)
            for h in HZ:
                if r["n"] == h:
                    r[f"r{h}"] = ret
            if c <= r["s"]:
                r.update(st="stop", end=asof)
            elif r["sym"] in exits and (not exits[r["sym"]].get("system") or exits[r["sym"]]["system"] == r["sys"]):
                r.update(st="exit", end=asof)
            elif r["n"] >= MAX_DAYS:
                r.update(st="done", end=asof)
    # 2. log setups shown tonight that are not already being followed
    for x in (P.get("top") or []) + (P.get("swing") or []):
        b = x.get("bucket") or ""
        if b not in live or x["symbol"] in open_syms or not x.get("stop"):
            continue
        stopk = x.get("kind") in STOPK
        e = float(x.get("trigger") or x.get("price") or 0)
        if not e or e <= x["stop"]:
            continue
        rows.append(dict(id=x.get("id"), sym=x["symbol"], sys=x.get("system"), kind=x.get("kind"), b=b, d=asof, s=round(float(x["stop"]), 2),
                         st="waiting" if stopk else "open", trig=round(e, 2) if stopk else None, e=None if stopk else round(e, 2),
                         d0=None if stopk else asof, n=0))
        open_syms.add(x["symbol"])
    L.update(asof=asof, since=L.get("since") or asof, generated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), rows=rows[-600:])
    # 3. summary for the app
    ent = [r for r in rows if r.get("e") and r.get("n", 0) > 0]
    summ = dict(shown=len(rows), entered=len(ent), open=sum(r["st"] == "open" for r in rows), stopped=sum(r["st"] == "stop" for r in rows),
                exited=sum(r["st"] == "exit" for r in rows), waiting=sum(r["st"] == "waiting" for r in rows))
    for h in HZ:
        v = [r[f"r{h}"] for r in ent if f"r{h}" in r]
        summ[f"d{h}"] = dict(n=len(v), avg=round(sum(v) / len(v), 2) if v else None, win=round(100 * sum(x > 0 for x in v) / len(v)) if v else None)
    done = [r["ret"] for r in rows if r["st"] in ("stop", "exit", "done") and "ret" in r]
    summ["closed"] = dict(n=len(done), avg=round(sum(done) / len(done), 2) if done else None, win=round(100 * sum(x > 0 for x in done) / len(done)) if done else None)
    L["summary"] = summ
    json.dump(L, open(D + "setup_log.json", "w"), separators=(",", ":"))
    print(mk, "setup log:", summ)


if __name__ == "__main__":
    for m in (sys.argv[1:] or ["NSE"]):
        if os.path.exists(DIR[m] + "trade_plan.json"):
            main(m)
