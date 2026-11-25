"""Today-tab call tracker (25 Nov 2026, Amritpal: "are you tracking each day the stocks coming out of the system in the Today tab vs how they
actually perform that day... banks leading on Friday but they fell, now marine stocks - needs to be recorded. How far back can we trace?").

Each NSE close (asof) it records what Today showed for the next session:
  top     = the 5 top-ranked industry groups (Pulse rank)
  newlead = groups that moved into Leading this week (weekly rotation, the "Moved into Leading" line)
  sector  = broad sectors in Leading
  theme   = the 3 top themes
  buy     = the buy list (trade_plan top rows)
and later fills each call's equal-weight return over the next 1, 3 and 5 sessions (close to close from the call-day close), next to Nifty.
State: data/scan/today_calls.json (calls + the last 8 days of closes). Nightly: python tools/today_calls.py.
Backfill from git history: python tools/today_calls.py --backfill   (snapshots exist from 5-7 Nov 2026)."""
import csv
import json
import os
import subprocess
import sys

OUT = "data/scan/today_calls.json"
HOR = (1, 3, 5)


def nifty():
    try:
        return {r[0]: float(r[4]) for r in csv.reader(open("data/futures/NIFTY.csv")) if r and r[0][:2] == "20"}
    except Exception:  # noqa: BLE001
        return {}


def closes(G, N=None):
    px = {}
    for r in (G or {}).get("rows", []):
        for m in r.get("members") or []:
            if m.get("close"):
                px[m["symbol"]] = float(m["close"])
    if N and G and N.get("asof") == G.get("asof"):
        for s, v in (N.get("prices") or {}).items():
            if v and v[-1]:
                px.setdefault(s, float(v[-1]))
    return px


def calls_for(G, T):
    out = []
    if G:
        rows = sorted(G.get("rows") or [], key=lambda r: r.get("rank") or 999)
        mem = lambda r: [m["symbol"] for m in (r.get("members") or [])]  # noqa: E731
        for r in rows[:5]:
            out.append(dict(kind="top", name=r["group"], syms=mem(r), note=f"rank {r.get('rank')}, Pulse 1w {r.get('p1w')}"))
        for r in rows:
            q = r.get("rrg") or {}
            if q.get("now") == "Leading" and q.get("wk1") != "Leading":
                out.append(dict(kind="newlead", name=r["group"], syms=mem(r), note=f"was {q.get('wk1')}"))
        for s in G.get("sectors") or []:
            if (s.get("rrg") or {}).get("now") == "Leading":
                out.append(dict(kind="sector", name=s["sector"], syms=[m for r in rows if r.get("sector") == s["sector"] for m in mem(r)], note=""))
        for t in (G.get("themes") or [])[:3]:
            out.append(dict(kind="theme", name=t["group"], syms=mem(t), note=f"Pulse 1w {t.get('p1w')}"))
    if T:
        for r in T.get("top") or []:
            if r.get("side") == "BUY":
                out.append(dict(kind="buy", name=r["symbol"], syms=[r["symbol"]], note=r.get("system", "")))
    return out


def update(S, G, T, N=None, NF=None):
    """Process one session (G's asof). Idempotent per asof: a re-run on the same asof refreshes that day's closes and calls."""
    if not G or not G.get("asof"):
        return False
    d = G["asof"]; px = closes(G, N); NF = NF or nifty()
    days = S.setdefault("days", [])
    if days and d < days[-1]:
        return False
    if not days or days[-1] != d:
        days.append(d)
    S.setdefault("px", {})[d] = px
    for k in sorted(S["px"])[:-8]:
        del S["px"][k]
    S["calls"] = [c for c in S.get("calls", []) if c["d"] != d]
    for c in calls_for(G, T if (T and T.get("asof") == d) else None):
        c0 = {s: px[s] for s in c["syms"] if s in px}
        if c0:
            S["calls"].append(dict(d=d, kind=c["kind"], name=c["name"], note=c["note"], n=len(c0), c0=c0, nf0=NF.get(d), out={}))
    for c in S["calls"]:                                   # fill outcomes
        if c["d"] not in days:
            continue
        i = days.index(c["d"])
        for h in HOR:
            if str(h) in c["out"] or i + h >= len(days):
                continue
            dh = days[i + h]; p = S["px"].get(dh)
            if p is None:
                continue
            rs = [p[s] / v - 1 for s, v in c["c0"].items() if s in p and v]
            if not rs:
                continue
            nf = (NF[dh] / c["nf0"] - 1) if c.get("nf0") and NF.get(dh) else None
            c["out"][str(h)] = dict(to=dh, r=round(sum(rs) / len(rs) * 100, 2), nifty=round(nf * 100, 2) if nf is not None else None,
                                    up=round(sum(r > 0 for r in rs) / len(rs) * 100))
    keep = days[-120:]                                     # about six months of sessions
    S["days"] = keep; S["calls"] = [c for c in S["calls"] if c["d"] >= keep[0]]
    S["asof"] = d
    return True


def summary(S):
    sm = {}
    for kind in ("top", "newlead", "sector", "theme", "buy"):
        for h in HOR:
            X = [c["out"][str(h)] for c in S.get("calls", []) if c["kind"] == kind and str(h) in c["out"]]
            if X:
                beat = [x for x in X if x["nifty"] is not None]
                sm.setdefault(kind, {})[str(h)] = dict(n=len(X), avg=round(sum(x["r"] for x in X) / len(X), 2),
                                                        vs=round(sum(x["r"] - x["nifty"] for x in beat) / len(beat), 2) if beat else None,
                                                        beat=round(sum(x["r"] > x["nifty"] for x in beat) / len(beat) * 100) if beat else None,
                                                        green=round(sum(x["r"] > 0 for x in X) / len(X) * 100))
    S["summary"] = sm


def save(S):
    summary(S)
    slim = dict(S); slim["calls"] = [{k: v for k, v in c.items() if k != "c0"} | {"syms": sorted(c["c0"])[:40]} for c in S["calls"]]
    json.dump(S, open(OUT + ".state", "w"), separators=(",", ":"))
    json.dump(slim, open(OUT, "w"), separators=(",", ":"))


def load():
    for f in (OUT + ".state",):
        if os.path.exists(f):
            return json.load(open(f))
    return {"calls": [], "days": [], "px": {}}


def git_versions(path):
    L = subprocess.run(["git", "log", "--reverse", "--format=%H %ct", "--", path], capture_output=True, text=True).stdout.split("\n")
    out = []
    for line in L:
        if line.strip():
            h, t = line.split()
            try:
                out.append((int(t), h, json.loads(subprocess.run(["git", "show", f"{h}:{path}"], capture_output=True, text=True).stdout)))
            except Exception:  # noqa: BLE001
                pass
    return out


def backfill():
    Gv = git_versions("data/scan/group_pulse.json"); Tv = git_versions("data/scan/trade_plan.json"); Nv = git_versions("data/scan/nse_close.json")
    lastG = {}
    for t, h, G in Gv:                                      # last version per asof
        if G.get("asof"):
            lastG[G["asof"]] = (t, G)
    lastT = {}
    for t, h, T in Tv:
        if T.get("asof"):
            lastT[T["asof"]] = T
    lastN = {N.get("asof"): N for t, h, N in Nv if N.get("asof")}
    S = {"calls": [], "days": [], "px": {}}; NF = nifty()
    for d in sorted(lastG):
        update(S, lastG[d][1], lastT.get(d), lastN.get(d), NF)
        print("backfill", d, len([c for c in S["calls"] if c["d"] == d]), "calls")
    return S


if __name__ == "__main__":
    if "--backfill" in sys.argv:
        S = backfill()
    else:
        S = load()
        G = json.load(open("data/scan/group_pulse.json")) if os.path.exists("data/scan/group_pulse.json") else None
        T = json.load(open("data/scan/trade_plan.json")) if os.path.exists("data/scan/trade_plan.json") else None
        N = json.load(open("data/scan/nse_close.json")) if os.path.exists("data/scan/nse_close.json") else None
        update(S, G, T, N)
    save(S)
    print(json.dumps(S.get("summary"), indent=0)[:1500])
