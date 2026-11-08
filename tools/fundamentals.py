"""Company fundamentals for every liquid stock in the Markets tab (Yahoo Finance via yfinance).
Usage: python tools/fundamentals.py NSE|US|ASX [refresh_days] [limit]
Reads the stock list from <out>/group_pulse.json, keeps <out>/fundamentals.json as a cache and
re-fetches entries older than refresh_days (default 6) plus anything missing.
Fields (all rounded, missing when Yahoo has nothing):
  ab about (trimmed business summary), web, emp, mc market cap (local currency), pe, fpe, pb, dy %,
  roe %, roce % (EBIT / (total assets - current liabilities), latest year), opm %, npm %, de (debt/equity, x),
  ins % held by insiders (promoters for India), inst % held by institutions,
  q  last quarters [label, EPS, EPS YoY %, sales, sales YoY %] newest first,
  a  last years [year, EPS, EPS growth %, sales, sales growth %] newest first, g3 3-year EPS CAGR %.
"""
import concurrent.futures as cf
import datetime as dt
import json
import math
import os
import sys
import time

import pandas as pd

OUT = {"NSE": "data/scan/", "US": "data/scan/us/", "ASX": "data/scan/asx/"}
SUF = {"NSE": ".NS", "US": "", "ASX": ".AX"}


def num(v, nd=1):
    try:
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else round(f, nd)
    except Exception:  # noqa: BLE001
        return None


def row(df, *names):
    if df is None or getattr(df, "empty", True):
        return None
    for n in names:
        if n in df.index:
            return df.loc[n]
    return None


def yoy(cur, prev):
    if cur is None or prev is None or prev == 0:
        return None
    if prev < 0:
        return None if cur < 0 else 999.0          # loss -> profit: shown as "turnaround"
    return round((cur / prev - 1) * 100, 1)


def quarters(q):
    eps = row(q, "Diluted EPS", "Basic EPS"); rev = row(q, "Total Revenue", "Operating Revenue")
    ni = row(q, "Net Income", "Net Income Common Stockholders")
    if eps is None and ni is None and rev is None:
        return []
    cols = sorted(q.columns, reverse=True)
    def g(s, c):
        return None if s is None else num(s.get(c), 2)
    out = []
    for i, c in enumerate(cols[:6]):
        prev = next((p for p in cols if 330 <= (c - p).days <= 400), None)
        e = g(eps, c); ep = g(eps, prev) if prev is not None else None
        if e is None and ni is not None:                      # Yahoo India often lacks EPS -> use net income growth
            e = None; ey = yoy(g(ni, c), g(ni, prev)) if prev is not None else None
        else:
            ey = yoy(e, ep)
        s = g(rev, c); sp = g(rev, prev) if prev is not None else None
        if e is None and s is None and ey is None:
            continue
        out.append([c.strftime("%b %y"), e, ey, s, yoy(s, sp)])
    return out


def years(a):
    eps = row(a, "Diluted EPS", "Basic EPS"); rev = row(a, "Total Revenue", "Operating Revenue")
    if eps is None and rev is None:
        return [], None
    cols = sorted(a.columns, reverse=True)[:4]
    v = lambda s, c: None if s is None else num(s.get(c), 2)  # noqa: E731
    out = []
    for i, c in enumerate(cols):
        p = cols[i + 1] if i + 1 < len(cols) else None
        out.append([c.strftime("%b %y"), v(eps, c), yoy(v(eps, c), v(eps, p)) if p is not None else None,
                    v(rev, c), yoy(v(rev, c), v(rev, p)) if p is not None else None])
    g3 = None
    if len(out) == 4 and out[0][1] and out[3][1] and out[0][1] > 0 and out[3][1] > 0:
        g3 = round(((out[0][1] / out[3][1]) ** (1 / 3) - 1) * 100, 1)
    return out, g3


def fetch(tk):
    import yfinance as yf
    for k in range(3):
        try:
            t = yf.Ticker(tk); i = t.info or {}
            if not i or (not i.get("longName") and not i.get("shortName") and not i.get("marketCap")):
                return None
            d = {"u": dt.date.today().isoformat()}
            ab = (i.get("longBusinessSummary") or "").strip()
            if ab:
                d["ab"] = ab if len(ab) <= 420 else ab[:420].rsplit(" ", 1)[0] + "…"
            for k2, src, nd, mul in (("mc", "marketCap", 0, 1), ("pe", "trailingPE", 1, 1), ("fpe", "forwardPE", 1, 1), ("pb", "priceToBook", 1, 1),
                                     ("roe", "returnOnEquity", 1, 100), ("opm", "operatingMargins", 1, 100), ("npm", "profitMargins", 1, 100),
                                     ("ins", "heldPercentInsiders", 1, 100), ("inst", "heldPercentInstitutions", 1, 100), ("emp", "fullTimeEmployees", 0, 1)):
                v = num(i.get(src), 4)
                if v is not None:
                    d[k2] = round(v * mul, nd) if nd else int(v * mul)
            dy = num(i.get("dividendYield"), 4)
            if dy is not None:
                d["dy"] = round(dy if dy > 0.3 else dy * 100, 2)          # yfinance switched dividendYield from fraction to %
            de = num(i.get("debtToEquity"), 2)
            if de is not None:
                d["de"] = round(de / 100, 2)
            if i.get("website"):
                d["web"] = i["website"]
            try:
                d["q"] = quarters(t.quarterly_income_stmt)
            except Exception:  # noqa: BLE001
                pass
            try:
                a = t.income_stmt; d["a"], g3 = years(a)
                if g3 is not None:
                    d["g3"] = g3
                b = t.balance_sheet
                ebit = row(a, "EBIT", "Operating Income"); ta = row(b, "Total Assets"); cl = row(b, "Current Liabilities")
                if ebit is not None and ta is not None and cl is not None:
                    c = sorted(set(a.columns) & set(b.columns), reverse=True)
                    if c:
                        cap = num(ta.get(c[0]), 0); cl0 = num(cl.get(c[0]), 0); e0 = num(ebit.get(c[0]), 0)
                        if cap and cl0 is not None and e0 is not None and cap - cl0 > 0:
                            d["roce"] = round(e0 / (cap - cl0) * 100, 1)
            except Exception:  # noqa: BLE001
                pass
            return {k3: v for k3, v in d.items() if v not in (None, [], "")}
        except Exception as e:  # noqa: BLE001
            if "Too Many Requests" in str(e) or "Rate" in str(e):
                time.sleep(20 * (k + 1))
            else:
                time.sleep(2 + 2 * k)
    return None


def main():
    mk = sys.argv[1]; days = int(sys.argv[2]) if len(sys.argv) > 2 else 6; lim = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    out = OUT[mk]
    G = json.load(open(out + "group_pulse.json"))
    syms = sorted({m["symbol"] for r in G["rows"] for m in r["members"]})
    path = out + "fundamentals.json"
    try:
        cache = json.load(open(path)).get("s", {})
    except Exception:  # noqa: BLE001
        cache = {}
    cut = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    todo = [s for s in syms if s not in cache or cache[s].get("u", "") < cut]
    todo.sort(key=lambda s: cache.get(s, {}).get("u", ""))           # oldest first
    if lim:
        todo = todo[:lim]
    print(mk, "stocks", len(syms), "to fetch", len(todo), flush=True)
    tk = {s: (s.replace("/", "-").replace(".", "-") if mk == "US" else s) + SUF[mk] for s in todo}
    ok = miss = 0; t0 = time.time()
    with cf.ThreadPoolExecutor(4) as ex:
        for n, (s, v) in enumerate(zip(todo, ex.map(fetch, [tk[s] for s in todo]))):
            if v:
                cache[s] = v; ok += 1
            else:
                miss += 1
            if n % 100 == 0:
                print(n, "ok", ok, "miss", miss, f"{time.time() - t0:.0f}s", flush=True)
            if time.time() - t0 > 100 * 60:                            # stay inside the job limit; the rest goes next night
                print("time cap reached"); break
    keep = {s: cache[s] for s in syms if s in cache}
    json.dump({"generated": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z", "market": mk, "source": "Yahoo Finance",
               "s": keep}, open(path, "w"), separators=(",", ":"))
    print("done ok", ok, "miss", miss, "stored", len(keep), "of", len(syms))
    q = [v for v in keep.values() if v.get("q")]
    print("with quarters", len(q), "with roce", sum("roce" in v for v in keep.values()), "with about", sum("ab" in v for v in keep.values()))
    if q:
        print("sample", json.dumps(next(iter(q))) [:600])


if __name__ == "__main__":
    main()
