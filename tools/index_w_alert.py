"""Index early alert: W bottom + falling trendline break (19 Nov 2026, Amritpal; tested in tools/research/index_w_bottom.py,
project doc index-w-bottom-trendline-test). INFORMATION ONLY - stock entries stay on 9/21 + the RED light.
Rule (tested on 23 NSE indices 2015-26, 541 setups): two zigzag(2%) closing lows within -2%..+4%, 8-60 sessions apart, the
first >= 5% below the 120-day high close, middle peak >= 2% above the first low; trendline = from that high through the middle
peak. Trendline break = first close above the line after the 2nd low is confirmed. It came before the index's 9/21 cross 71% of the
time, ~1% lower (entry +3.1% off the 2nd low vs +3.9%); next 20 sessions median +1.6% (63% up) vs +1.2% (59%) on any day; 9/21
after the W +1.9%. RSI divergence added nothing (also tested with 3% swings / 8% fall: same picture).
Output: data/scan/index_w.json   (status 'broken' = broke in the last 10 sessions; 'forming' = W in place, line not yet broken)"""
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OUT = "data/scan"
KEEP = ["NIFTY 50", "NIFTY BANK", "NIFTY FINANCIAL SERVICES", "NIFTY PRIVATE BANK", "NIFTY PSU BANK", "NIFTY IT", "NIFTY AUTO", "NIFTY FMCG",
        "NIFTY PHARMA", "NIFTY METAL", "NIFTY REALTY", "NIFTY ENERGY", "NIFTY INFRASTRUCTURE", "NIFTY MEDIA", "NIFTY PSE", "NIFTY CPSE",
        "NIFTY COMMODITIES", "NIFTY INDIA CONSUMPTION", "NIFTY SERVICES SECTOR", "NIFTY MNC", "NIFTY 500", "NIFTY MIDCAP 150",
        "NIFTY SMALLCAP 250", "NIFTY CAPITAL MARKETS", "NIFTY CONSUMER DURABLES", "NIFTY OIL & GAS", "NIFTY HEALTHCARE INDEX", "NIFTY INDIA DEFENCE"]


def zigzag(c, th=0.02):
    piv, d, ext, exi = [], 1, c[0], 0
    for i in range(1, len(c)):
        if d == 1:
            if c[i] > ext:
                ext, exi = c[i], i
            elif c[i] < ext * (1 - th):
                piv.append(("H", exi, i)); d, ext, exi = -1, c[i], i
        else:
            if c[i] < ext:
                ext, exi = c[i], i
            elif c[i] > ext * (1 + th):
                piv.append(("L", exi, i)); d, ext, exi = 1, c[i], i
    return piv


def latest(c):
    """the most recent W on this index: dict or None"""
    v = c.values; n = len(v); dts = c.index
    d = c.diff(); up = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean(); dn = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = (100 - 100 / (1 + up / dn)).values
    lows = [(p[1], p[2]) for p in zigzag(v) if p[0] == "L"]
    for a in range(len(lows) - 2, -1, -1):
        (l1, _), (l2, conf2) = lows[a], lows[a + 1]
        if n - 1 - l2 > 70:
            return None                                   # nothing recent
        if not (8 <= l2 - l1 <= 60) or l1 < 120:
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
        line = lambda j: hi + slope * (j - hi_i)  # noqa: E731
        brk = next((j for j in range(conf2, min(n, l2 + 60)) if v[j] > line(j)), None)
        rec = dict(low1=str(dts[l1].date()), low1_close=round(float(v[l1]), 2), low2=str(dts[l2].date()), low2_close=round(float(v[l2]), 2),
                   high=round(float(hi), 2), high_date=str(dts[hi_i].date()), mid=round(float(mid), 2), mid_date=str(dts[mid_i].date()),
                   rsi_div=bool(rsi[l2] > rsi[l1]), close=round(float(v[-1]), 2), asof=str(dts[-1].date()), neckline=round(float(mid), 2))
        if brk is not None:
            ago = n - 1 - brk
            if ago > 20:                                   # 20 Nov 2026: keep the latest break visible for 20 sessions (was 10)
                return None
            rec.update(status="broken", broke_on=str(dts[brk].date()), days_ago=int(ago), broke_close=round(float(v[brk]), 2),
                       line_then=round(float(line(brk)), 2), from_low2=round(float(v[brk] / v[l2] - 1) * 100, 1),
                       since=round(float(v[-1] / v[brk] - 1) * 100, 1), above_neck=bool(v[-1] > mid))
        else:
            if n - 1 >= l2 + 60:
                return None
            rec.update(status="forming", line_now=round(float(line(n)), 2), dist_pct=round(float(line(n) / v[-1] - 1) * 100, 1))
        return rec
    return None


def slug(name):
    import re
    return re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")


def chart_json(x, r, days=160):
    """daily candles + EMA 9 + the W trendline for the app's chart sheet (20 Nov 2026). x: DataFrame Open/High/Low/Close."""
    x = x[["Open", "High", "Low", "Close"]].dropna()
    x = x[(x > 0).all(axis=1)]
    if x.empty:
        return None
    e9 = x.Close.ewm(span=9, adjust=False).mean()
    y = x.tail(days); e = e9.tail(days); idx = list(x.index)
    out = dict(t=[str(d.date()) for d in y.index], o=[round(float(v), 2) for v in y.Open], h=[round(float(v), 2) for v in y.High],
               l=[round(float(v), 2) for v in y.Low], c=[round(float(v), 2) for v in y.Close], e9=[round(float(v), 2) for v in e])
    try:
        hi_i, mid_i = idx.index(pd.Timestamp(r["high_date"])), idx.index(pd.Timestamp(r["mid_date"]))
        slope = (r["mid"] - r["high"]) / (mid_i - hi_i)
        end_i = min(len(idx) - 1, (idx.index(pd.Timestamp(r["broke_on"])) + 5) if r.get("broke_on") else len(idx) - 1)
        out["tl"] = [[str(idx[hi_i].date()), r["high"]], [str(idx[end_i].date()), round(r["high"] + slope * (end_i - hi_i), 2)]]
    except Exception:  # noqa: BLE001
        pass
    out["marks"] = [m for m in ([r.get("low1"), "low 1"], [r.get("low2"), "low 2"], [r.get("broke_on"), "break"]) if m[0]]
    return out


def write_charts(rows, frames, folder):
    """frames: {row key -> OHLC DataFrame}; writes <folder>/index_w_charts/<slug>.json and sets r['chart'] = slug"""
    os.makedirs(f"{folder}/index_w_charts", exist_ok=True)
    for r in rows:
        x = frames.get(r.get("ticker") or r["index"])
        if x is None:
            continue
        j = chart_json(x, r)
        if j:
            sl = slug(r.get("ticker") or r["index"]); r["chart"] = sl
            json.dump(dict(name=r["index"], **j), open(f"{folder}/index_w_charts/{sl}.json", "w"), separators=(",", ":"))


def extras(r, x):
    """volume on the break day vs its 20-day average, and the EMA 9 lift-off state (whole candle above a rising EMA 9)"""
    import ema_lift_alert as EL
    out = {}
    if x is None or x.empty:
        return out
    if r.get("broke_on") and "Volume" in x and x.Volume.notna().sum() > 30:
        v = x.Volume; d = pd.Timestamp(r["broke_on"])
        if d in v.index:
            i = v.index.get_loc(d); avg = v.iloc[max(0, i - 20):i].mean()
            if avg and avg > 0:
                out["vol_ratio"] = round(float(v.iloc[i] / avg), 2)
            # volume on the up-days since the 2nd low vs the down-days before it (rising volume on the rally)
    s = EL.state(x[["Open", "High", "Low", "Close"]].dropna())
    if s:
        out.update(ema_status=s["status"], ema_since=s["signal"], ema_gain=s["gain"], ema9=s["ema"])
    return out


def main():
    s = pd.read_csv(f"{OUT}/sector_hist.csv.gz", parse_dates=["Date"])
    P = s.pivot_table(index="Date", columns="INDEX", values="CLOSE").sort_index()
    try:
        import index_ohlcv
        X = index_ohlcv.update(KEEP)
        XO = {k: g.set_index("Date").sort_index() for k, g in X.groupby("INDEX")}
    except Exception as e:  # noqa: BLE001
        print("index_ohlcv failed", e); XO = {}
    rows = []
    for ix in KEEP:
        if ix not in P.columns:
            continue
        c = P[ix].dropna()
        if len(c) < 200:
            continue
        r = latest(c)
        if r:
            r.update(extras(r, XO.get(ix)))
            # 20 Nov 2026 test (551 W breaks, 23 indices 2016-26): with a 9 EMA lift-off within 3 days of the break, next 20 sessions
            # median +1.5% (63% up); without one -0.6% (46% up). Break-day volume >= 1.2x added nothing (+1.40% vs +1.36%).
            r["full"] = bool(r["status"] == "broken" and r.get("ema_status") in ("riding", "lift-off today"))
            rows.append(dict(index=ix, **r))
    rows.sort(key=lambda r: (r["status"] != "broken", r.get("days_ago", 99), r.get("dist_pct", 99)))
    prev = {}
    try:
        prev = {(r["index"], r.get("broke_on")) for r in json.load(open(f"{OUT}/index_w.json")).get("rows", []) if r.get("status") == "broken"}
    except Exception:  # noqa: BLE001
        prev = set()
    new = [r for r in rows if r["status"] == "broken" and (r["index"], r["broke_on"]) not in prev and r["days_ago"] <= 1]
    out = dict(generated=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M+00:00"), asof=str(P.index[-1].date()), rows=rows,
               rule=__doc__.split("Output:")[0].strip(),
               test=dict(setups=541, tl_before_921_pct=71, fwd20_median=1.6, fwd20_up=63, any_day_fwd20_median=1.18, any_day_up=59))
    FR = {k: v for k, v in XO.items()}
    for r in rows:                      # indices without OHLC history: draw closes as flat candles
        if r["index"] not in FR and r["index"] in P.columns:
            cc = P[r["index"]].dropna(); FR[r["index"]] = pd.DataFrame({"Open": cc, "High": cc, "Low": cc, "Close": cc})
    write_charts(rows, FR, OUT)
    json.dump(out, open(f"{OUT}/index_w.json", "w"), indent=1)
    for r in rows:
        print(r["index"], r["status"], r.get("broke_on") or f"line {r.get('line_now')} ({r.get('dist_pct')}% away)")
    if new and os.environ.get("SEND_TELEGRAM") == "1":
        try:
            import notify
            notify.send("Index early alert (W + trendline break, info only):\n" + "\n".join(
                f"{r['index']}: broke the falling trendline on {r['broke_on']} at {r['broke_close']:,.0f} (+{r['from_low2']}% off the 2nd low)" for r in new)
                + "\nNext: wait for 9/21 / your own entry rules.")
        except Exception as e:  # noqa: BLE001
            print("notify failed", e)


if __name__ == "__main__":
    main()
