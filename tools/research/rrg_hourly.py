"""Hourly rotation (RRG) as an early warning - sample test (22 Nov 2026, Amritpal: "the rotation chart, if we add it on hourly, can
it give an early indication? just do a sample test").

Sample: 12 NSE sector indices + 20 large NSE stocks, each vs the Nifty 50, last ~2 years (Yahoo keeps 60-minute bars ~730 days).
RRG as in the app (tools/group_pulse.py rrg): RS = series / Nifty; RS-ratio = 100 x RS / n-bar average of RS; RS-momentum = m-bar
average of 100 x ratio / previous ratio. Leading = ratio >= 100 and momentum >= 100; Improving = ratio < 100, momentum >= 100.
Views: DAILY (10 / 3 days), WEEKLY (10 / 3 weeks), HOURLY-FAST (10 / 3 hourly bars), HOURLY-DAY (70 / 21 hourly bars = 10 / 3 days).
Measured:
  1. lead time - for each DAILY (and WEEKLY) entry into Leading, how many trading days earlier the hourly view had entered Leading
     (most recent hourly entry in the 15 trading days before, still Leading at the daily signal)
  2. follow-through - share of hourly Leading entries followed by a daily Leading entry within 5 trading days (else a false alarm)
  3. edge - relative return vs Nifty over the next 5 / 10 / 20 trading days after each kind of entry (hourly: from the bar's
     close), against the average of all days (baseline). Same for Improving entries.
Output data/research/rrg_hourly.json"""
import json
import os
import time

import numpy as np
import pandas as pd
import yfinance as yf

SECT = {"^NSEBANK": "Bank", "^CNXIT": "IT", "^CNXAUTO": "Auto", "^CNXPHARMA": "Pharma", "^CNXMETAL": "Metal", "^CNXFMCG": "FMCG",
        "^CNXREALTY": "Realty", "^CNXENERGY": "Energy", "NIFTY_FIN_SERVICE.NS": "Fin services", "^CNXPSUBANK": "PSU bank",
        "^CNXMEDIA": "Media", "^CNXINFRA": "Infra"}
STK = ["RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "SBIN", "BHARTIARTL", "ITC", "LT", "AXISBANK", "KOTAKBANK", "HINDUNILVR",
       "MARUTI", "SUNPHARMA", "TATASTEEL", "M&M", "BAJFINANCE", "TITAN", "NTPC", "ONGC"]
TICK = dict(SECT, **{s + ".NS": s for s in STK})
H = [5, 10, 20]


def get(t, **kw):
    for _ in range(3):
        try:
            d = yf.download(t, auto_adjust=True, progress=False, **kw)
            if d is not None and len(d):
                c = d["Close"].squeeze().dropna(); c.index = pd.to_datetime(c.index)
                if c.index.tz is not None:
                    c.index = c.index.tz_convert("Asia/Kolkata").tz_localize(None)
                return c
        except Exception as e:  # noqa: BLE001
            print("retry", t, e)
        time.sleep(5)
    return None


def quad(rs, n, m):
    ratio = 100 * rs / rs.rolling(n).mean(); mom = (100 * ratio / ratio.shift(1)).rolling(m).mean()
    q = pd.Series(np.where(ratio >= 100, np.where(mom >= 100, "L", "W"), np.where(mom >= 100, "I", "G")), index=rs.index)
    return q.where(ratio.notna() & mom.notna())


def entries(q, k):
    prev = q.shift(1)
    return q.index[(q == k) & (prev != k) & prev.notna()]


def main():
    nh = get("^NSEI", period="730d", interval="60m"); nd = get("^NSEI", period="3y", interval="1d")
    res = dict(method=__doc__, per_series={}, summary={})
    agg = {k: [] for k in ("lead_L", "lead_L_w", "follow_fast", "follow_day", "follow_fast_I", "follow_day_I")}
    fwd = {k: {h: [] for h in H} for k in ("base", "daily_L", "weekly_L", "hfast_L", "hday_L", "daily_I", "hfast_I", "hday_I")}
    for t, name in TICK.items():
        sh = get(t, period="730d", interval="60m"); sd = get(t, period="3y", interval="1d")
        if sh is None or sd is None or len(sh) < 500:
            print("R| skip", name); continue
        jh = pd.concat([sh, nh], axis=1, join="inner").dropna(); jd = pd.concat([sd, nd], axis=1, join="inner").dropna()
        rsh = jh.iloc[:, 0] / jh.iloc[:, 1]; rsd = jd.iloc[:, 0] / jd.iloc[:, 1]
        rsw = rsd.resample("W-FRI").last().dropna()
        qd = quad(rsd, 10, 3); qw = quad(rsw, 10, 3); qf = quad(rsh, 10, 3); qy = quad(rsh, 70, 21)
        t0 = rsh.index[0] + pd.Timedelta(days=45)                 # common window once the hourly views have warmed up
        days = rsd.index[rsd.index >= t0.normalize()]
        dpos = {d: i for i, d in enumerate(rsd.index)}
        # 22 Nov 2026 fix: Yahoo's hourly and daily series are adjusted differently -> measure everything on the HOURLY series
        dl = rsh.groupby(rsh.index.normalize()).tail(1)              # last hourly bar of each day
        dl_days = dl.index.normalize()
        def fret(ts, h):                                          # relative return from ts to the close h trading days later
            i = dl_days.searchsorted(ts.normalize())
            if i >= len(dl):
                return None
            if ts.normalize() == ts:                              # a daily / weekly signal: from that day's close
                base = dl.iloc[i]
            else:
                base = rsh.asof(ts)
            j = i + h
            return None if j >= len(dl) or not base else float(dl.iloc[j] / base - 1)
        for d in days:
            for h in H:
                r_ = fret(d, h)
                if r_ is not None:
                    fwd["base"][h].append(r_)
        eD = [d for d in entries(qd, "L") if d >= t0]; eW = [d for d in entries(qw, "L") if d >= t0]
        eF = [d for d in entries(qf, "L") if d >= t0]; eY = [d for d in entries(qy, "L") if d >= t0]
        eDi = [d for d in entries(qd, "I") if d >= t0]; eFi = [d for d in entries(qf, "I") if d >= t0]; eYi = [d for d in entries(qy, "I") if d >= t0]
        for key, ev in (("daily_L", eD), ("weekly_L", eW), ("hfast_L", eF), ("hday_L", eY), ("daily_I", eDi), ("hfast_I", eFi), ("hday_I", eYi)):
            for e in ev:
                for h in H:
                    r_ = fret(e, h)
                    if r_ is not None:
                        fwd[key][h].append(r_)
        # lead time: for each daily Leading entry, the most recent hourly-day-view entry within 15 trading days that is still Leading
        def lead(evd, evh, qh):
            out = []
            for d in evd:
                i = dpos.get(d)
                if i is None:
                    continue
                lo = rsd.index[max(0, i - 15)]; end_ts = d + pd.Timedelta(hours=16)
                cand = [x for x in evh if lo <= x <= end_ts]
                if cand and qh.asof(end_ts) == "L":
                    x = max(cand); out.append(int(i - rsd.index.searchsorted(x.normalize())))
                    HRS.append(round(((d + pd.Timedelta(hours=15, minutes=30)) - x).total_seconds() / 3600, 1))
                else:
                    out.append(None)
            return out
        HRS = []; lf = lead(eD, eF, qf); hf = HRS[:]; HRS.clear(); ly = lead(eD, eY, qy); hy = HRS[:]; HRS.clear(); lw = lead(eW, eY, qy)
        agg.setdefault("hrs_fast", []).extend(hf); agg.setdefault("hrs_day", []).extend(hy)
        # follow-through: hourly entry followed by a daily Leading state within 5 trading days
        def follow(evh, k="L"):
            ok = 0
            for x in evh:
                i = rsd.index.searchsorted(x.normalize()); win = qd.iloc[i:i + 6]
                ok += bool((win == k).any())
            return ok, len(evh)
        fF = follow(eF); fY = follow(eY); fFi = follow(eFi, "I"); fYi = follow(eYi, "I")
        months = max(1, (rsh.index[-1] - t0).days / 30.4)
        row = dict(name=name, daily_L=len(eD), weekly_L=len(eW), hfast_L=len(eF), hday_L=len(eY), hfast_per_month=round(len(eF) / months, 1), hday_per_month=round(len(eY) / months, 1),
                   lead_fast=[v for v in lf if v is not None], lead_day=[v for v in ly if v is not None], lead_week_from_hday=[v for v in lw if v is not None],
                   pre_signalled_fast=f"{sum(v is not None for v in lf)}/{len(lf)}", pre_signalled_day=f"{sum(v is not None for v in ly)}/{len(ly)}",
                   follow_fast=f"{fF[0]}/{fF[1]}", follow_day=f"{fY[0]}/{fY[1]}")
        res["per_series"][name] = row
        agg["lead_L"] += [v for v in ly if v is not None]; agg["lead_L_w"] += [v for v in lw if v is not None]
        agg["follow_fast"].append(fF); agg["follow_day"].append(fY); agg["follow_fast_I"].append(fFi); agg["follow_day_I"].append(fYi)
        res["per_series"][name]["_pre"] = (sum(v is not None for v in lf), sum(v is not None for v in ly), len(eD))
        print("R|", name, {k: v for k, v in row.items() if not k.startswith("lead_")}, "| lead (days) day-view:", row["lead_day"][:12], flush=True)
    fs = lambda L: f"{sum(a for a, b in L)}/{sum(b for a, b in L)} = {round(100 * sum(a for a, b in L) / max(1, sum(b for a, b in L)))}%"  # noqa: E731
    pre = [v["_pre"] for v in res["per_series"].values()]
    S = dict(
        daily_leading_entries=sum(p[2] for p in pre),
        pre_signalled_by_hourly_fast=f"{sum(p[0] for p in pre)} ({round(100 * sum(p[0] for p in pre) / max(1, sum(p[2] for p in pre)))}%)",
        pre_signalled_by_hourly_day=f"{sum(p[1] for p in pre)} ({round(100 * sum(p[1] for p in pre) / max(1, sum(p[2] for p in pre)))}%)",
        lead_days_hourly_day_vs_daily=dict(median=float(np.median(agg["lead_L"])) if agg["lead_L"] else None, mean=round(float(np.mean(agg["lead_L"])), 1) if agg["lead_L"] else None,
                                            dist={k: int(sum(1 for v in agg["lead_L"] if v == k)) for k in range(0, 16)}),
        lead_hours_fast=dict(median=float(np.median(agg["hrs_fast"])) if agg.get("hrs_fast") else None, p75=float(np.percentile(agg["hrs_fast"], 75)) if agg.get("hrs_fast") else None),
        lead_hours_day=dict(median=float(np.median(agg["hrs_day"])) if agg.get("hrs_day") else None, p75=float(np.percentile(agg["hrs_day"], 75)) if agg.get("hrs_day") else None),
        lead_days_hourly_day_vs_weekly=dict(median=float(np.median(agg["lead_L_w"])) if agg["lead_L_w"] else None, n=len(agg["lead_L_w"])),
        follow_through_hourly_fast_to_daily_leading=fs(agg["follow_fast"]), follow_through_hourly_day_to_daily_leading=fs(agg["follow_day"]),
        follow_through_hourly_fast_I=fs(agg["follow_fast_I"]), follow_through_hourly_day_I=fs(agg["follow_day_I"]),
        forward_relative_return={k: {f"{h}d": dict(n=len(v[h]), avg=round(100 * float(np.mean(v[h])), 2) if v[h] else None,
                                                  beat=round(100 * float(np.mean(np.array(v[h]) > 0))) if v[h] else None) for h in H} for k, v in fwd.items()})
    res["summary"] = S
    for k, v in S.items():
        print("R| SUMMARY", k, v, flush=True)
    for v in res["per_series"].values():
        v.pop("_pre", None)
    os.makedirs("data/research", exist_ok=True)
    json.dump(res, open("data/research/rrg_hourly.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
