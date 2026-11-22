"""RSI range-shift pullback (22 Nov 2026, Amritpal: "monthly RSI > 60, weekly > 60, daily range shift from below to 40 support RSI,
buy above that candle next day, first target is daily RSI 60 and then trail till 3-day low is broken").

Reading of the rules (RSI 14, Wilder):
  trend    monthly RSI > 60 and weekly RSI > 60 (last COMPLETED month / week, no look-ahead)
  shift    daily RSI was below 40, then rises back above 40 (and reaches 45+)
  support  it pulls back to 40 and holds (38-44, never a close under 38); the SIGNAL candle is the day RSI turns up there.
           One signal per rise from below 40.
  entry    next session only, buy-stop one tick above the signal candle's high (gap -> the open); not crossed -> no trade
  stop     signal candle's low (not in the rules - assumed)
  exits    as given: half at the first close with daily RSI >= 60, the rest trails: out when price trades below the lowest
           low of the previous 3 sessions. Variants: all out at RSI 60 | no half (all trail after RSI 60) | stop at the
           pullback low instead of the signal low. 120-session limit. 0.2% cost a round trip.
Universe: NSE stocks (Yahoo + bhavcopy check, survivors only) + assets (world indices, commodities, FX, crypto, bond yields) +
NSE sector / theme indices (closes only). Portfolio: Rs 20 L, 1% risk, max 10, <= 20% each.
Also writes TODAY's list: signals on the last session (buy above tomorrow) and setups now in the 40-45 zone (watch).
PILOT env = 150 stocks + all assets. Output data/research/rsi_range(_pilot).json"""
import ast
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
from global_universe import symbols  # noqa: E402
from holy_grail import portfolio, report  # noqa: E402
from flag_stops import tst  # noqa: E402

PILOT = bool(os.environ.get("PILOT"))
COST, MINVAL = 0.002, 2e7


def rsi(c, n=14):
    d = np.diff(c, prepend=c[0]); up = pd.Series(np.clip(d, 0, None)).ewm(alpha=1 / n, adjust=False).mean()
    dn = pd.Series(np.clip(-d, 0, None)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).fillna(100).to_numpy()


def htf_rsi(x, rule):
    """RSI of the previous COMPLETED weekly / monthly bar, for every day of the current week / month (no look-ahead)"""
    per = x.index.to_period(rule); cl = x.CLOSE.groupby(per).last()
    rb = pd.Series(rsi(cl.to_numpy(float)), index=cl.index).shift(1)
    return rb.reindex(per).to_numpy()


def asset_list():
    src = open(os.path.join(HERE, "..", "asset_scan.py")).read()
    A = next(ast.literal_eval(nd.value) for nd in ast.parse(src).body if isinstance(nd, ast.Assign) and getattr(nd.targets[0], "id", "") == "A")
    return {t: (n, g) for g, d in A.items() for t, n in d.items()}


def dl(tick, start):
    out = {}
    for i in range(0, len(tick), 200):
        ch = tick[i:i + 200]; d = None
        for _ in range(3):
            try:
                d = yf.download(ch, start=start, auto_adjust=True, progress=False, group_by="column", threads=True); break
            except Exception as e:  # noqa: BLE001
                print("retry", e); time.sleep(20)
        if d is None or d.empty:
            continue
        for t in ch:
            try:
                x = pd.DataFrame({"OPEN": d["Open"][t], "HIGH": d["High"][t], "LOW": d["Low"][t], "CLOSE": d["Close"][t], "VOL": d["Volume"][t]}).dropna(subset=["CLOSE"])
            except Exception:  # noqa: BLE001
                continue
            x = x[x.CLOSE > 0]
            for k in ("OPEN", "HIGH", "LOW"):
                x[k] = x[k].where(x[k] > 0, x.CLOSE)
            x.index = pd.to_datetime(x.index).tz_localize(None); out[t] = x
        print("R| loaded", i + len(ch), len(out), flush=True); time.sleep(2)
    return out


def load(start):
    u = symbols("NSE"); tick = sorted(u.ticker)
    if PILOT:
        tick = tick[:150]
    P = {}
    for t, x in dl(tick, start).items():
        if len(x) >= 300 and (x.CLOSE * x.VOL).rolling(20).mean().iloc[-250:].max() >= MINVAL and x.CLOSE.iloc[-1] >= 50:
            P[t.replace(".NS", "")] = ("stock", x)
    AL = asset_list()
    for t, x in dl(list(AL), start).items():
        if len(x) >= 300:
            P[AL[t][0]] = ("asset" if AL[t][1] != "World indices" else "index", x)
    try:
        from index_w_alert import KEEP
        h = pd.read_csv("data/scan/sector_hist.csv.gz", index_col=0, parse_dates=True)
        for nm in KEEP:
            cl = h[h.INDEX == nm].CLOSE.sort_index().astype(float)
            cl = cl[cl.index >= start]
            if len(cl) >= 300 and nm not in P:
                P[nm] = ("index", pd.DataFrame({"OPEN": cl, "HIGH": cl, "LOW": cl, "CLOSE": cl, "VOL": 0.0}))
    except Exception as e:  # noqa: BLE001
        print("sector indices unavailable", e)
    return P


def setups(x, htf="or60"):
    """-> list of dict(i, kind 'signal'), plus the open state at the end ('zone' if RSI now sits in 40-45 after a shift)"""
    c = x.CLOSE.to_numpy(float); n = len(c); r = rsi(c); rw = htf_rsi(x, "W"); rm = htf_rsi(x, "M")
    # 22 Nov 2026 (Amritpal: "no - daily rise to 40 from below, then took support at 40"): RSI below 40 -> crosses back above 40
    # (and gets to 45+ so it is not just hovering) -> pulls back to 38-44 and turns up = the signal candle; a close under 38 resets
    out = []; seen_low = False; armed = False; pk = 0; peak_i = None; now = None
    for i in range(30, n):
        if r[i] < 38:
            armed = False
        if r[i] < 40:
            seen_low = True; armed = False
            continue
        if seen_low and not armed and r[i - 1] < 40 <= r[i]:
            armed, pk, peak_i, pk_i, seen_low = True, r[i], i, i, False
            continue
        if armed and i - peak_i > 40:                      # stale: the pullback must come within 40 sessions of the cross
            armed = False
        if armed:
            pk0 = pk                                       # the bounce high BEFORE today (the dip must come after it)
            if r[i] > pk:
                pk, pk_i = r[i], i
            # 22 Nov 2026 (Amritpal's Nifty chart: low 42.4 on 23 Oct, turned up 26 Oct at 46.1; "any one of them above 60"):
            # the pullback low (yesterday) sits in 38-45 and today RSI turns up; weekly OR monthly RSI > 60 (htf='none': no filter)
            hok = True if htf == "none" else (rw[i] > 60 or rm[i] > 60)
            if pk0 >= 45 and 38 <= r[i - 1] <= 45 and r[i] > r[i - 1] and r[i - 1] < pk0 - 3 and hok:
                out.append(dict(i=i, peak=pk_i, rsi=round(float(r[i]), 1), rw=round(float(rw[i]), 1), rm=round(float(rm[i]), 1)))
                armed = False
    i = n - 1
    if armed and pk >= 45 and 38 <= r[i] <= 46 and (htf == "none" or rw[i] > 60 or rm[i] > 60):
        now = dict(rsi=round(float(r[i]), 1), rw=round(float(rw[i]), 1), rm=round(float(rm[i]), 1))
    return out, now, r


def trade(x, r, s, mode):
    o, h, l, c = (x[k].to_numpy(float) for k in ("OPEN", "HIGH", "LOW", "CLOSE")); n = len(c); i = s["i"]; j = i + 1
    if j >= n or not h[j] > h[i]:
        return None
    e = max(o[j], h[i] * 1.0005)
    stop = l[i] if mode != "pullback-low stop" else float(l[s["peak"]:i + 1].min())
    if not stop < e * 0.999:
        return None
    if l[j] <= stop:
        return dict(j=j, k=j, ret=stop / e - 1, stopped=True, half=False, e=e, stop=stop)
    half = None; t1 = False; k = j + 1
    while k < n:
        if o[k] <= stop: px = o[k]; st = True; break
        if l[k] <= stop: px = stop; st = True; break
        if t1:
            lv = float(l[k - 3:k].min())
            if l[k] < lv: px = min(o[k], lv); st = False; break
        if not t1 and r[k] >= 60:
            if mode == "all out at RSI 60": px = c[k]; st = False; break
            t1 = True
            if mode != "no half, trail all": half = c[k]
        if k - j >= 120: px = c[k]; st = False; break
        k += 1
    else:
        k = n - 1; px = c[k]; st = False
    ret = px / e - 1
    if half is not None:
        ret = 0.5 * (half / e - 1) + 0.5 * ret
    return dict(j=j, k=k, ret=ret, stopped=st, half=half is not None, e=e, stop=stop)


MODES = ["as given (half at RSI 60, trail 3-day low)", "pullback-low stop"]
HTFS = {"weekly OR monthly RSI > 60": "or60", "no weekly/monthly filter": "none"}


def main():
    P = load("2015-01-01")
    nif = yf.download("^NSEI", start="2015-01-01", auto_adjust=True, progress=False)["Close"].squeeze().dropna()
    nif.index = pd.to_datetime(nif.index).tz_localize(None); bull = nif > nif.rolling(200).mean()
    today = []; rows = {f"{hn} | {m}": [] for hn in HTFS for m in MODES}; nsig = 0
    for sym, (kind, x) in P.items():
      for hn, hv in HTFS.items():
          S, now, r = setups(x, hv)
          D = x.index; n = len(x)
          for s in S:
              if s["i"] == n - 1:
                  if hv == "or60": today.append(dict(symbol=sym, kind=kind, status="signal", buy_above=round(float(x.HIGH.iloc[-1]) * 1.0005, 2), stop=round(float(x.LOW.iloc[-1]), 2),
                                    close=round(float(x.CLOSE.iloc[-1]), 2), rsi=s["rsi"], rsi_w=s["rw"], rsi_m=s["rm"], date=str(D[-1].date())))
                  continue
              if D[s["i"]] < pd.Timestamp("2016-06-01"):
                  continue
              nsig += hv == "or60"
              for m in MODES:
                  t = trade(x, r, s, m)
                  if t:
                      risk = 1 - t["stop"] / t["e"] if m != "pullback-low stop" else 1 - t["stop"] / t["e"]
                      risk = max(risk, 1e-3); ret = t["ret"] - COST
                      rows[f"{hn} | {m}"].append(dict(sym=sym, side=1, entry=D[t["j"]], exit=D[t["k"]], e=t["e"], risk=risk, ret=ret, r_mult=ret / risk, half=t["half"],
                                          days=t["k"] - t["j"], adx=s["rsi"], stopped=t["stopped"], hit=t["half"], kind=kind, year=D[t["j"]].year))
          if hv == "or60" and now and not any(d["symbol"] == sym for d in today):
              today.append(dict(symbol=sym, kind=kind, status="in the 40 zone (watch)", close=round(float(x.CLOSE.iloc[-1]), 2), rsi=now["rsi"], rsi_w=now["rw"],
                                rsi_m=now["rm"], date=str(D[-1].date())))
    print("R| universe", len(P), {k: sum(v[0] == k for v in P.values()) for k in ("stock", "index", "asset")}, "| signals since Jun 2016", nsig, flush=True)
    print("R| TODAY", len(today), [(d["symbol"], d["kind"], d["status"], d["rsi"]) for d in today], flush=True)
    C = {s: x.CLOSE.astype(float).to_dict() for s, (k, x) in P.items() if k == "stock"}
    days = sorted({d for k, x in P.values() if k == "stock" for d in x.index if d >= pd.Timestamp("2016-06-01")})
    res = dict(method=__doc__, universe=len(P), signals=nsig, today=today, runs={})
    for m, L in rows.items():
        T = pd.DataFrame(L)
        if not len(T):
            print("R|", m, "no trades"); continue
        end = T.entry.max()
        tr = dict(all=tst(T), **{f"last {y}y": tst(T[T.entry > end - pd.DateOffset(years=y)]) for y in (1, 2, 3, 5)},
                  ex_covid=tst(T[~((T.entry >= "2020-02-15") & (T.entry <= "2020-12-31"))]),
                  by_kind={k: tst(T[T["kind"] == k]) for k in ("stock", "index", "asset")},
                  by_year={str(y): tst(T[T.year == y]) for y in sorted(T.year.unique(), reverse=True)})
        TS = T[T["kind"] == "stock"]
        rp = report(portfolio(TS, C, days), bull) if len(TS) else None
        res["runs"][m] = dict(trades=tr, port_stocks=rp)
        print(f"R| {m} | all {tr['all']} | 1y {tr['last 1y']} | 2y {tr['last 2y']} | 5y {tr['last 5y']}", flush=True)
        print(f"R| {m} | by kind {tr['by_kind']}", flush=True)
        print(f"R| {m} | portfolio (stocks) {rp}", flush=True)
    os.makedirs("data/research", exist_ok=True)
    json.dump(res, open("data/research/rsi_range" + ("_pilot" if PILOT else "") + ".json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
