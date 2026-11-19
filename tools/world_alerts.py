"""US / ASX / UK versions of the two India info alerts (19 Nov 2026, Amritpal: "whatever changes you are doing are for all markets").
  1. Index W bottom + falling trendline break (same rule as tools/index_w_alert.py) on each market's broad + sector indices
  2. EMA 9 lift-off (same rule as tools/ema_lift_alert.py) on those indices + the market's 50 most-traded stocks
Usage:  python tools/world_alerts.py US|ASX|UK          -> data/scan/<mk>/index_w.json + ema_lift.json (+ Telegram on new events)
        python tools/world_alerts.py US|ASX|UK test     -> backtest both rules on that market (prints R| lines)"""
import json
import os
import sys
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ema_lift_alert as EL  # noqa: E402
import index_w_alert as IW  # noqa: E402
from global_universe import MARKETS, symbols  # noqa: E402

IDX = {
    "US": {"^GSPC": "S&P 500", "^NDX": "Nasdaq 100", "^DJI": "Dow Jones", "^RUT": "Russell 2000", "XLF": "Financials (XLF)",
           "XLK": "Technology (XLK)", "XLE": "Energy (XLE)", "XLV": "Health Care (XLV)", "XLI": "Industrials (XLI)",
           "XLY": "Consumer Discretionary (XLY)", "XLP": "Consumer Staples (XLP)", "XLU": "Utilities (XLU)", "XLB": "Materials (XLB)",
           "XLRE": "Real Estate (XLRE)", "XLC": "Communication (XLC)", "SMH": "Semiconductors (SMH)", "KRE": "Regional Banks (KRE)"},
    "ASX": {"^AXJO": "ASX 200", "^AORD": "All Ordinaries", "^AXFJ": "Financials", "^AXMJ": "Materials", "^AXEJ": "Energy",
            "^AXHJ": "Health Care", "^AXIJ": "Info Tech", "^AXDJ": "Consumer Discretionary", "^AXSJ": "Consumer Staples",
            "^AXNJ": "Industrials", "^AXPJ": "A-REIT", "^AXUJ": "Utilities", "^AXTJ": "Communication"},
    "UK": {"^FTSE": "FTSE 100", "^FTMC": "FTSE 250", "^FTAS": "FTSE All-Share"},
}
PATH = {"US": "data/scan/us", "ASX": "data/scan/asx", "UK": "data/scan/uk"}
# backtest results per market (python tools/world_alerts.py <MK> test, 19 Nov 2026; indices from 2005, top-50 stocks from 2007)
TEST = {
    "US": dict(w="Tested on 17 US indices/sector ETFs 2005–26 (695 W's): the break came before the 9/21 cross 67% of the time; next 20 sessions median +2.0% (65% up) vs +1.3% (62%) on any day. Useful, like India.",
               lift="Tested 2007–26: indices +0.45% a trade vs +0.67% holding any 16 days; top-50 stocks +1.48% vs +1.61%. No edge in the US: shown for reference only.", alert_w=True),
    "ASX": dict(w="Tested on 13 ASX indices 2005–26 (532 W's): next 20 sessions median +0.7% (58% up) vs +0.7% (56%) on any day. No real edge on the ASX: reference only.",
                lift="Tested 2007–26: indices +0.19% a trade vs +0.27% holding any 16 days; top-50 stocks +0.66% vs +0.94%. No edge on the ASX: reference only.", alert_w=False),
    "UK": dict(w="Tested on FTSE 100 / 250 / All-Share 2005–26 (111 W's): next 20 sessions avg −0.1% vs +0.5% on any day. Worse than random in the UK: reference only.",
               lift="Tested 2007–26: indices +0.30% vs +0.32% holding any 16 days; top-50 stocks +0.03% vs +0.40%. No edge in the UK: reference only.", alert_w=False),
}


def dl(tickers, start, minrows=150):
    out = {}
    for i in range(0, len(tickers), 100):
        ch = tickers[i:i + 100]
        for _ in range(3):
            try:
                D = yf.download(ch, start=start, auto_adjust=True, progress=False, group_by="ticker", threads=True); break
            except Exception as e:  # noqa: BLE001
                print("retry", e); time.sleep(15); D = None
        if D is None or D.empty:
            continue
        for t in ch:
            try:
                x = (D[t] if len(ch) > 1 else D)[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
                x.index = pd.to_datetime(x.index).tz_localize(None)
                x = x[(x[["Open", "High", "Low", "Close"]] > 0).all(axis=1)]
                if len(x) > minrows:
                    out[t] = x
            except Exception:  # noqa: BLE001
                pass
        time.sleep(1)
    return out


def top_stocks(mk, n=50):
    u = symbols(mk); tick = list(u.ticker); name = dict(zip(u.ticker, u.symbol))
    P = dl(tick, (pd.Timestamp.today() - pd.Timedelta(days=60)).strftime("%Y-%m-%d"), minrows=15)
    val = {t: float((x.Close * x.Volume).tail(20).mean()) for t, x in P.items()}
    best = sorted(val, key=lambda t: -val[t])[:n]
    return {t: name.get(t, t) for t in best}


# ---------------------------------------------------------------- backtests
def w_events(c):
    v = c.values; n = len(v); out = []
    d = c.diff(); e9, e21 = c.ewm(span=9, adjust=False).mean().values, c.ewm(span=21, adjust=False).mean().values
    lows = [(p[1], p[2]) for p in IW.zigzag(v) if p[0] == "L"]; used = -1
    for a in range(len(lows) - 1):
        (l1, _), (l2, conf2) = lows[a], lows[a + 1]
        if l1 <= used or not (8 <= l2 - l1 <= 60) or l1 < 120:
            continue
        hi = v[l1 - 120:l1 + 1].max(); hi_i = l1 - 120 + int(np.argmax(v[l1 - 120:l1 + 1]))
        if v[l1] > hi * 0.95 or not (-0.02 <= v[l2] / v[l1] - 1 <= 0.04):
            continue
        mid_i = l1 + int(np.argmax(v[l1:l2 + 1])); mid = v[mid_i]
        if mid < v[l1] * 1.02 or mid_i <= hi_i:
            continue
        slope = (mid - hi) / (mid_i - hi_i)
        if slope >= 0:
            continue
        tl = next((j for j in range(conf2, min(n, l2 + 60)) if v[j] > hi + slope * (j - hi_i)), None)
        x9 = next((j for j in range(max(conf2, 1), min(n, l2 + 60)) if e9[j] > e21[j] and e9[j - 1] <= e21[j - 1]), None)
        if tl is None:
            continue
        used = l2
        out.append(dict(tl=tl, x9=x9, f20=(v[tl + 20] / v[tl] - 1) if tl + 20 < n else None, entry=v[tl] / v[l2] - 1,
                        e9entry=(v[x9] / v[l2] - 1) if x9 is not None else None, f20_921=(v[x9 + 20] / v[x9] - 1) if x9 is not None and x9 + 20 < n else None))
    return out


def lift_trades(x, cost):
    o, h, l, c = x.Open.values, x.High.values, x.Low.values, x.Close.values
    e = x.Close.ewm(span=9, adjust=False).mean(); rising = (e > e.shift(3)).values; e = e.values
    above, below = l > e, h < e; m = len(c); T = []; i = 60
    while i < m - 2:
        if above[i] and rising[i] and not above[i - 10:i].any():
            j0 = i + 1; k = next((j + 1 for j in range(j0, m - 1) if below[j]), m - 1)
            T.append((x.index[i], o[k] / o[j0] - 1 - cost)); i = k
        else:
            i += 1
    return T


def st(r):
    r = np.array([z for z in r if z is not None and np.isfinite(z)])
    if not len(r):
        return dict(n=0)
    w, ls = r[r > 0].sum(), -r[r < 0].sum()
    return dict(n=len(r), avg=round(float(r.mean() * 100), 2), median=round(float(np.median(r) * 100), 2), win=round(float((r > 0).mean() * 100)),
                pf=round(float(w / ls), 2) if ls else None)


def test(mk):
    I = dl(list(IDX[mk]), "2005-01-01")
    S = dl(list(top_stocks(mk)), "2007-01-01")
    allc = []
    W = []
    for t, x in I.items():
        W += w_events(x.Close)
        allc += list((x.Close.shift(-20) / x.Close - 1).dropna().values)
    print("R|", mk, "indices", len(I), "stocks", len(S), flush=True)
    print("R|", mk, "W + trendline break: setups", len(W), "| 20d after the break", st([w["f20"] for w in W]), "| any index day 20d", st(allc),
          "| entry above 2nd low median", round(float(np.median([w["entry"] for w in W]) * 100), 1) if W else None,
          "| 9/21 after W: entry", round(float(np.nanmedian([w["e9entry"] if w["e9entry"] is not None else np.nan for w in W]) * 100), 1) if W else None,
          "20d", st([w["f20_921"] for w in W]),
          "| break before 9/21", round(float(np.mean([w["x9"] is None or w["tl"] < w["x9"] for w in W]) * 100)) if W else None, flush=True)
    for grp, D, cost in (("indices", I, 0.0005), ("top 50 stocks", S, 0.001)):
        T = sorted([t for x in D.values() for t in lift_trades(x, cost)])
        hold = []
        for x in D.values():
            o, c = x.Open.values, x.Close.values
            hold += [c[min(len(c) - 1, j + 15)] / o[j] - 1 - cost for j in range(61, len(c) - 16, 5)]
        a = st([t[1] for t in T if t[0] < pd.Timestamp("2017-01-01")]); b = st([t[1] for t in T if t[0] >= pd.Timestamp("2017-01-01")])
        print("R|", mk, "EMA9 lift-off", grp, st([t[1] for t in T]), "| 2007-16", a, "| 2017-26", b, "| any day held 16 sessions", st(hold), flush=True)


# ---------------------------------------------------------------- live alerts
def run(mk):
    os.makedirs(PATH[mk], exist_ok=True)
    I = dl(list(IDX[mk]), (pd.Timestamp.today() - pd.Timedelta(days=500)).strftime("%Y-%m-%d"))
    tops = top_stocks(mk)
    S = dl(list(tops), (pd.Timestamp.today() - pd.Timedelta(days=500)).strftime("%Y-%m-%d"))
    asof = max(x.index[-1] for x in I.values())
    # 1. index W
    wr = []
    for t, x in I.items():
        if x.index[-1] != asof:
            continue
        r = IW.latest(x.Close)
        if r:
            wr.append(dict(index=IDX[mk][t], ticker=t, **r))
    wr.sort(key=lambda r: (r["status"] != "broken", r.get("days_ago", 99), r.get("dist_pct", 99)))
    pw = {}
    try:
        pw = {(r["index"], r.get("broke_on")) for r in json.load(open(f"{PATH[mk]}/index_w.json")).get("rows", []) if r.get("status") == "broken"}
    except Exception:  # noqa: BLE001
        pw = set()
    json.dump(dict(generated=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M+00:00"), asof=str(asof.date()), market=mk, rows=wr, test=TEST[mk]["w"],
                   rule=IW.__doc__.split("Output:")[0].strip()), open(f"{PATH[mk]}/index_w.json", "w"), indent=1)
    # 2. EMA 9 lift-off
    er = []
    for t, x in list(I.items()) + list(S.items()):
        if x.index[-1] != asof:
            continue
        s = EL.state(x[["Open", "High", "Low", "Close"]])
        if s:
            er.append(dict(symbol=IDX[mk].get(t) or tops.get(t, t), index=t in I, **s))
    order = {"lift-off today": 0, "left below": 1, "riding": 2}
    er.sort(key=lambda r: (not r["index"], order[r["status"]], -r["gain"]))
    prev = {}
    try:
        prev = json.load(open(f"{PATH[mk]}/ema_lift.json"))
    except Exception:  # noqa: BLE001
        pass
    json.dump(dict(generated=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M+00:00"), asof=str(asof.date()), market=mk, ema=9, rows=er, test=TEST[mk]["lift"],
                   rule=EL.__doc__.split("Data:")[0].strip()), open(f"{PATH[mk]}/ema_lift.json", "w"), indent=1)
    for r in wr:
        print("W|", r["index"], r["status"], r.get("broke_on") or r.get("line_now"))
    for r in er:
        if r["index"] or r["status"] != "riding":
            print("E|", r["symbol"], r["status"], r["signal"], r["gain"])
    if os.environ.get("SEND_TELEGRAM") == "1":
        # messages only where the rule tested positive on this market (US index W); everything else is shown in the app only
        msgs = [f"{r['index']}: broke its falling trendline after a W on {r['broke_on']}" for r in wr
                if TEST[mk]["alert_w"] and r["status"] == "broken" and r["days_ago"] <= 1 and (r["index"], r["broke_on"]) not in pw]
        if msgs:
            try:
                import notify
                notify.send(f"{MARKETS[mk]['label']} alerts (info only):\n" + "\n".join(msgs[:25]))
            except Exception as e:  # noqa: BLE001
                print("notify failed", e)


if __name__ == "__main__":
    mk = sys.argv[1].upper()
    test(mk) if len(sys.argv) > 2 and sys.argv[2] == "test" else run(mk)
