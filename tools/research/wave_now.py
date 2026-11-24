"""Elliott position of today's system stocks (24 Nov 2026, Amritpal: "can we analyse our system stocks on which wave they are -
impulse or correction"). Objective, rule-based count (no hand labelling):
  weekly bars, 3 years; zigzag on highs/lows with threshold = max(8%, 2 x 14-week ATR%) -> alternating swing highs / lows.
  Start = the lowest swing low of the last 2 years. Legs from it are numbered 1,2,3,4,5 and checked against the three Elliott rules:
  wave 2 stays above the start, wave 3 is not the shortest of 1/3/5, wave 4 stays above the top of wave 1 (no overlap).
  The leg in progress = last pivot -> this week's close.
  Labels: Impulse wave 1 / 2 / 3 / 4 / 5; "5 waves done - correction (A-B-C) likely"; "Corrective / overlapping" when a rule breaks;
  "Down impulse" when the start is a high (price below the 2-year range midpoint and falling pivots).
Stocks: today's plan (top + swing + more) and the Stock score list's strategy stocks (ath, trend, flags, patterns)."""
import json
import time

import numpy as np
import pandas as pd
import yfinance as yf


def zig(h, l, thr):
    piv = []; d = 0; ext_i = 0; ext_v = l[0]
    hi_i, hi_v, lo_i, lo_v = 0, h[0], 0, l[0]
    for i in range(1, len(h)):
        if h[i] > hi_v: hi_i, hi_v = i, h[i]
        if l[i] < lo_v: lo_i, lo_v = i, l[i]
        if d >= 0 and hi_v > 0 and l[i] <= hi_v * (1 - thr[i]) and hi_i > (piv[-1][0] if piv else -1):
            if d == 0 and lo_i < hi_i: piv.append((lo_i, lo_v, "L"))
            piv.append((hi_i, hi_v, "H")); d = -1; lo_i, lo_v = i, l[i]
        elif d <= 0 and lo_v > 0 and h[i] >= lo_v * (1 + thr[i]) and lo_i > (piv[-1][0] if piv else -1):
            if d == 0 and hi_i < lo_i: piv.append((hi_i, hi_v, "H"))
            piv.append((lo_i, lo_v, "L")); d = 1; hi_i, hi_v = i, h[i]
    return piv


def count(x):
    h, l, c = x.High.to_numpy(float), x.Low.to_numpy(float), x.Close.to_numpy(float)
    tr = np.maximum(h[1:], c[:-1]) - np.minimum(l[1:], c[:-1]); atr = pd.Series(np.r_[np.nan, tr]).rolling(14).mean().to_numpy() / c
    thr = np.nan_to_num(np.maximum(0.08, 2 * atr), nan=0.08)
    P = zig(h, l, thr); n = len(c)
    if len(P) < 2:
        return "no clear swings", {}
    lows = [p for p in P if p[2] == "L" and p[0] >= n - 104]
    j = int(np.argmin(l[max(0, n - 104):])) + max(0, n - 104)          # lowest low of the last 2 years
    if lows and min(lows, key=lambda p: p[1])[1] <= l[j] * 1.0001:
        s = min(lows, key=lambda p: p[1]); seq = P[P.index(s):]
    else:                                                               # low not confirmed as a pivot: start there anyway
        s = (j, l[j], "L"); seq = [s] + [p for p in P if p[0] > j]
        if len(seq) > 1 and seq[1][2] == "L":
            seq = [s] + seq[2:]
    pts = [p[1] for p in seq] + [c[-1]]               # start, pivots..., current close (leg in progress)
    legs = len(pts) - 1                                 # completed legs = len(seq)-1, plus the one in progress
    done = len(seq) - 1
    w = [pts[i + 1] - pts[i] for i in range(len(pts) - 1)]
    info = dict(start=round(s[1], 2), weeks_since_start=n - 1 - s[0], legs_done=done, close=round(c[-1], 2), from_start_pct=round((c[-1] / s[1] - 1) * 100, 1))
    # rules on completed legs
    if done >= 2 and pts[2] <= pts[0]:
        return "Corrective / overlapping (wave 2 broke the start)", info
    if done >= 4 and pts[4] <= pts[1]:
        return "Corrective / overlapping (wave 4 overlapped wave 1)", info
    if done >= 5:
        a, b, e = w[0], w[2], w[4]
        if b < a and b < e:
            return "Corrective (wave 3 shortest)", info
        return ("5 waves done - correction (A-B-C) likely" if done == 5 else f"Beyond 5 waves ({done} legs) - correction / new cycle"), info
    cur = done + 1                                      # wave in progress
    up = c[-1] > seq[-1][1]
    if cur in (2, 4) and up:            # above the last swing high: the previous impulse wave is still extending
        cur -= 1; cur_txt = f"wave {cur} (extending, new highs)"
    elif cur in (3, 5) and not up:      # below the last swing low: the pullback is still deepening
        cur -= 1; cur_txt = f"wave {cur} (pullback deepening)"
    else:
        cur_txt = f"wave {cur}"
    if cur == 3 and done >= 2 and len(w) >= 3:
        info["w3_vs_w1"] = round((c[-1] - pts[2]) / max(1e-9, w[0]), 2)     # 1.618 = typical wave 3 target
    if cur == 5 and done >= 4:
        info["w5_target_eq_w1"] = round(pts[4] + w[0], 2)
    kind = "Impulse" if cur in (1, 3, 5) else "Impulse pullback"
    return f"{kind}: {cur_txt}", info


def main():
    tp = json.load(open("data/scan/trade_plan.json")); syms = {}
    for r in (tp.get("top") or []) + (tp.get("swing") or []) + (tp.get("more") or []):
        syms[r["symbol"]] = r.get("system") or ""
    at = json.load(open("data/scan/ath.json"))
    for r in (at.get("breakouts") or []) + [t for t in (at.get("tracked") or []) if t.get("status") == "open"]:
        syms.setdefault(r["symbol"], "Monthly ATH")
    fl = json.load(open("data/scan/flags.json"))
    for r in fl.get("rows") or []:
        syms.setdefault(r["symbol"], r.get("shape") or "Flag")
    print("R| stocks", len(syms), flush=True)
    out = []; L = list(syms)
    for i in range(0, len(L), 50):
        ch = L[i:i + 50]
        d = yf.download([s + ".NS" for s in ch], period="3y", interval="1wk", auto_adjust=True, progress=False, group_by="ticker", threads=True)
        for s in ch:
            try:
                x = d[s + ".NS"].dropna(subset=["Close"]); x = x[x.High >= x.Low]
                if len(x) < 60:
                    continue
                lab, info = count(x)
                out.append(dict(symbol=s, system=syms[s], wave=lab, **info))
            except Exception as e:  # noqa: BLE001
                print("R| skip", s, str(e)[:80], flush=True)
        time.sleep(1)
    D = pd.DataFrame(out)
    print("R| SUMMARY " + json.dumps(D.wave.value_counts().to_dict()), flush=True)
    for _, r in D.sort_values(["wave", "system"]).iterrows():
        extra = " ".join(f"{k}={r[k]}" for k in ("w3_vs_w1", "w5_target_eq_w1") if k in r and pd.notna(r[k]))
        print(f"R| ROW {r.symbol:12s} | {r.system[:18]:18s} | {r.wave:52s} | start {r.start} ({r.weeks_since_start}w ago) +{r.from_start_pct}% | legs {r.legs_done} {extra}", flush=True)
    json.dump(out, open("data/research/wave_now.json", "w"), indent=0, default=str)


if __name__ == "__main__":
    main()
