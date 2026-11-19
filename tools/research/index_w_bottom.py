"""W bottom + RSI divergence + falling trendline break on INDICES (19 Nov 2026, Amritpal, Bank Nifty Nov 2026 chart:
"was this W pattern with trendline break with rising volume and rsi divergence a real early entry?").
Earlier tests covered stocks (bottom-patterns.md, bansal-book-strategies-test.md: no edge vs a random stock). This one: NSE sector /
broad indices, daily closes 2015-2026 (data/scan/sector_hist.csv.gz; no index volume, so volume is not tested).
Setup (all known at the signal close):
  fall  : first low >= 8% below the 120-day high close
  W     : swing lows on closes (zigzag 3%); second low within -2%..+4% of the first, 8-60 sessions apart, middle peak >= 3% above
  div   : RSI14 at the 2nd low > RSI14 at the 1st low (bullish divergence) - shown with and without
  TL    : falling line from the 120-day high close through the middle peak; TL break = first close above the line after the 2nd low
  NECK  : first close above the middle peak (classic W breakout)
  9/21  : first EMA9 > EMA21 cross after the 2nd low (our live-style trigger, for timing)
Forward 10 / 20 / 40 sessions from the signal close vs the same index on all days. Run locally (no network)."""
import json

import numpy as np
import pandas as pd

KEEP = ["NIFTY 50", "NIFTY BANK", "NIFTY FINANCIAL SERVICES", "NIFTY PRIVATE BANK", "NIFTY PSU BANK", "NIFTY IT", "NIFTY AUTO", "NIFTY FMCG",
        "NIFTY PHARMA", "NIFTY METAL", "NIFTY REALTY", "NIFTY ENERGY", "NIFTY INFRASTRUCTURE", "NIFTY MEDIA", "NIFTY PSE", "NIFTY CPSE",
        "NIFTY COMMODITIES", "NIFTY INDIA CONSUMPTION", "NIFTY SERVICES SECTOR", "NIFTY MNC", "NIFTY 500", "NIFTY MIDCAP 150", "NIFTY SMALLCAP 250"]


def zigzag(c, th=0.03):
    piv, d, ext, exi = [], 1, c[0], 0               # start assuming an up-leg; (type, pivot index, confirmed index)
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


def main():
    s = pd.read_csv("data/scan/sector_hist.csv.gz", parse_dates=["Date"])
    P = s.pivot_table(index="Date", columns="INDEX", values="CLOSE").sort_index()
    out = {"method": __doc__}
    ev = []
    base = {h: [] for h in (10, 20, 40)}
    for ix in KEEP:
        c = P[ix].dropna()
        if len(c) < 400:
            continue
        v = c.values; n = len(v)
        d = c.diff(); up = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean(); dn = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
        rsi = (100 - 100 / (1 + up / dn)).values
        e9, e21 = c.ewm(span=9, adjust=False).mean().values, c.ewm(span=21, adjust=False).mean().values
        for h in base:
            base[h] += list((c.shift(-h) / c - 1).dropna().values)
        piv = zigzag(v)
        lows = [(p[1], p[2]) for p in piv if p[0] == "L"]
        used = -1
        for a in range(len(lows) - 1):
            l1, _ = lows[a]; l2, conf2 = lows[a + 1]
            if l1 <= used or not (8 <= l2 - l1 <= 60) or l1 < 120:
                continue
            hi120 = v[l1 - 120:l1 + 1].max(); hi_i = l1 - 120 + int(np.argmax(v[l1 - 120:l1 + 1]))
            if v[l1] > hi120 * 0.92 or not (-0.02 <= v[l2] / v[l1] - 1 <= 0.04):
                continue
            mid_i = l1 + int(np.argmax(v[l1:l2 + 1])); mid = v[mid_i]
            if mid < v[l1] * 1.03 or mid_i <= hi_i:
                continue
            slope = (mid - hi120) / (mid_i - hi_i)
            if slope >= 0:
                continue
            div = bool(rsi[l2] > rsi[l1])
            trig = {}
            for j in range(conf2, min(n, l2 + 60)):            # can only act once the 2nd low is confirmed
                if "TL" not in trig and v[j] > hi120 + slope * (j - hi_i):
                    trig["TL"] = j
                if "NECK" not in trig and v[j] > mid:
                    trig["NECK"] = j
                if "921" not in trig and e9[j] > e21[j] and e9[j - 1] <= e21[j - 1]:
                    trig["921"] = j
            if not trig:
                continue
            used = l2
            rec = dict(index=ix, low1=str(c.index[l1].date()), low2=str(c.index[l2].date()), div=div, depth=round((v[l1] / hi120 - 1) * 100, 1))
            for k, j in trig.items():
                rec[k] = str(c.index[j].date()); rec[k + "_from_low2"] = round((v[j] / v[l2] - 1) * 100, 1)
                for h in (10, 20, 40):
                    rec[f"{k}_f{h}"] = round((v[j + h] / v[j] - 1) * 100, 2) if j + h < n else None
            ev.append(rec)
    E = pd.DataFrame(ev)
    out["events"] = ev
    out["all_days"] = {h: dict(avg=round(float(np.mean(base[h]) * 100), 2), median=round(float(np.median(base[h]) * 100), 2),
                               up=round(float((np.array(base[h]) > 0).mean() * 100))) for h in base}
    print("all index days", out["all_days"])
    print("W setups", len(E), "with RSI divergence", int(E["div"].sum()))
    for grp, m in (("all W", E.index == E.index), ("W + RSI divergence", E["div"]), ("W, no divergence", ~E["div"])):
        for k in ("TL", "NECK", "921"):
            row = {}
            for h in (10, 20, 40):
                x = E.loc[m, f"{k}_f{h}"].dropna()
                row[h] = dict(n=len(x), avg=round(float(x.mean()), 2), median=round(float(x.median()), 2), up=round(float((x > 0).mean() * 100)))
            got = E.loc[m, k].notna().mean() * 100
            late = E.loc[m, f"{k}_from_low2"].median()
            out.setdefault("results", {}).setdefault(grp, {})[k] = dict(fired_pct=round(got), entry_above_low2_median=late, fwd=row)
            print(f"R| {grp:22s} {k:5s} fired {got:.0f}%  entry +{late}% above 2nd low  ", row)
    # which came first
    both = E.dropna(subset=["TL", "921"])
    print("TL before 9/21:", round(float((pd.to_datetime(both.TL) < pd.to_datetime(both["921"])).mean() * 100)), "% ; same day:",
          round(float((both.TL == both["921"]).mean() * 100)), "%")
    for r in E[E["index"].isin(["NIFTY BANK", "NIFTY 50"])].tail(12).itertuples():
        print("E|", r.index, r.low1, r.low2, "div" if r.div else "", "TL", getattr(r, "TL", None), getattr(r, "TL_f20", None), "| 921", getattr(r, "_9", None))
    json.dump(out, open("data/research/index_w_bottom.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
