"""Short covering, short build-up and ITM put writing in F&O stocks: do they come BEFORE the move? (19 Nov 2026, Amritpal:
"check where we got late entry and any short squeeze ... we need to enter a bit earlier ... were ITM puts being written before the move")

Data: NSE F&O bhavcopy (UDiFF, Jul 2024 -> today), every F&O stock + BANKNIFTY / NIFTY / FINNIFTY. Per symbol per day:
  price = underlying close, futures OI (all expiries), put / call OI split ITM / OTM against that day's underlying price.
Signals (decided at the close, measured from that close):
  SB  short build-up        : 10-day price <= -5% and futures OI +15% or more            (the fuel)
  SC  short covering        : 3-day price >= +3% and futures OI -5% or more, after SB within the past 10 days (the release)
  SC0 short covering, any   : 3-day price >= +3% and futures OI -5% or more
  LB  long build-up         : 3-day price >= +3% and futures OI +5% or more
  PW  ITM put writing       : ITM put OI +25% or more in 3 days while price moved -2%..+2% (writers selling puts above spot)
  PWb put writing broad     : total put OI +25% in 3 days, price -2%..+2%, PCR up
Forward: next 5 / 10 / 20 sessions, stock minus the average F&O stock (so the market move is removed). One event per stock per 10 days.
Also prints the Oct-Nov 2026 bank rally day by day. Output: data/research/fo_squeeze.json + data/oi/fo_daily.csv.gz"""
import io
import json
import os
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36", "Referer": "https://www.nseindia.com/"}
BANKS = ["BANKNIFTY", "HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK", "BANKBARODA", "PNB", "CANBK", "UNIONBANK", "BANKINDIA",
         "INDUSINDBK", "FEDERALBNK", "IDFCFIRSTB", "AUBANK", "CHOLAFIN", "BAJFINANCE", "IREDA"]


def one(day):
    url = f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{day:%Y%m%d}_F_0000.csv.zip"
    for _ in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=40)
            if r.status_code == 404:
                return None
            if r.ok and r.content[:2] == b"PK":
                z = zipfile.ZipFile(io.BytesIO(r.content)); F = pd.read_csv(z.open(z.namelist()[0]))
                return agg(F, day)
        except Exception:  # noqa: BLE001
            time.sleep(3)
    return None


def agg(F, day):
    F = F[F.FinInstrmTp.isin(["STF", "IDF", "STO", "IDO"])]
    fut = F[F.FinInstrmTp.isin(["STF", "IDF"])]
    near = fut.sort_values("XpryDt").groupby("TckrSymb").first()
    und = near.UndrlygPric.where(near.UndrlygPric > 0, near.ClsPric)
    out = pd.DataFrame({"price": und, "fut_oi": fut.groupby("TckrSymb").OpnIntrst.sum()})
    op = F[F.FinInstrmTp.isin(["STO", "IDO"])].copy()
    op["und"] = op.TckrSymb.map(und)
    pe, ce = op[op.OptnTp == "PE"], op[op.OptnTp == "CE"]
    out["put_itm"] = pe[pe.StrkPric > pe.und].groupby("TckrSymb").OpnIntrst.sum()
    out["put_otm"] = pe[pe.StrkPric <= pe.und].groupby("TckrSymb").OpnIntrst.sum()
    out["call_itm"] = ce[ce.StrkPric < ce.und].groupby("TckrSymb").OpnIntrst.sum()
    out["call_otm"] = ce[ce.StrkPric >= ce.und].groupby("TckrSymb").OpnIntrst.sum()
    out["Date"] = pd.Timestamp(day)
    return out.fillna(0).reset_index().rename(columns={"TckrSymb": "sym", "index": "sym"})


def main():
    days = pd.bdate_range("2024-07-08", pd.Timestamp.today())
    with ThreadPoolExecutor(6) as ex:
        parts = [p for p in ex.map(one, days) if p is not None]
    A = pd.concat(parts, ignore_index=True).sort_values(["sym", "Date"])
    print("days", A.Date.nunique(), "symbols", A.sym.nunique(), A.Date.min().date(), "->", A.Date.max().date(), flush=True)
    os.makedirs("data/oi", exist_ok=True)
    A.to_csv("data/oi/fo_daily.csv.gz", index=False)
    P = A.pivot(index="Date", columns="sym", values="price"); OI = A.pivot(index="Date", columns="sym", values="fut_oi")
    PI = A.pivot(index="Date", columns="sym", values="put_itm"); PT = PI + A.pivot(index="Date", columns="sym", values="put_otm")
    CT = A.pivot(index="Date", columns="sym", values="call_itm") + A.pivot(index="Date", columns="sym", values="call_otm")
    pcr = PT / CT.replace(0, np.nan)
    r3, r10 = P / P.shift(3) - 1, P / P.shift(10) - 1
    o3, o10 = OI / OI.shift(3).replace(0, np.nan) - 1, OI / OI.shift(10).replace(0, np.nan) - 1
    pi3, pt3 = PI / PI.shift(3).replace(0, np.nan) - 1, PT / PT.shift(3).replace(0, np.nan) - 1
    flat = (r3 >= -0.02) & (r3 <= 0.02)
    SB = (r10 <= -0.05) & (o10 >= 0.15)
    sbrec = SB.rolling(10, min_periods=1).max().shift(1).fillna(0).astype(bool)
    SC0 = (r3 >= 0.03) & (o3 <= -0.05)
    S = {"SB short build-up": SB, "SC short covering after short build-up": SC0 & sbrec, "SC0 short covering (any)": SC0,
         "LB long build-up": (r3 >= 0.03) & (o3 >= 0.05), "PW ITM put writing, price flat": (pi3 >= 0.25) & flat & (PI.shift(3) > 0),
         "PWb put writing broad + PCR up": (pt3 >= 0.25) & flat & (pcr > pcr.shift(3))}
    stocks = [c for c in P.columns if c not in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50")]
    res = dict(method=__doc__, days=int(A.Date.nunique()), symbols=len(stocks))
    for h in (5, 10, 20):
        f = P[stocks].shift(-h) / P[stocks] - 1
        ex = f.sub(f.mean(axis=1), axis=0)
        res.setdefault("baseline", {})[h] = dict(avg_abs=round(float(f.stack().mean() * 100), 2))
        for name, m in S.items():
            m = m[stocks].fillna(False)
            ev = []
            for c in stocks:
                last = None
                for dt in m.index[m[c].values]:
                    if last is None or (P.index.get_loc(dt) - P.index.get_loc(last)) >= 10:
                        v = ex.at[dt, c]
                        if pd.notna(v):
                            ev.append(v)
                        last = dt
            ev = np.array(ev)
            res.setdefault(name, {})[h] = dict(n=len(ev), excess_avg=round(float(ev.mean() * 100), 2) if len(ev) else None,
                                               excess_median=round(float(np.median(ev) * 100), 2) if len(ev) else None,
                                               beat=round(float((ev > 0).mean() * 100)) if len(ev) else None)
    for name in S:
        print("R|", name, res[name], flush=True)
    # the Oct-Nov 2026 bank rally, day by day
    win = P.loc["2026-10-15":"2026-11-14"].index
    res["bank_rally"] = {}
    for b in BANKS:
        if b not in P.columns:
            continue
        rows = []
        for dt in win:
            flags = [k.split(" ")[0] for k, m in S.items() if bool(m.at[dt, b]) if b in m.columns]
            rows.append(dict(d=str(dt.date()), px=round(float(P.at[dt, b]), 1), fut_oi_chg3=round(float(o3.at[dt, b] * 100), 1) if pd.notna(o3.at[dt, b]) else None,
                             put_itm_chg3=round(float(pi3.at[dt, b] * 100), 1) if pd.notna(pi3.at[dt, b]) else None,
                             pcr=round(float(pcr.at[dt, b]), 2) if pd.notna(pcr.at[dt, b]) else None, flags=flags))
        res["bank_rally"][b] = rows
        print("B|", b, " ".join(f"{r['d'][5:]}:{r['px']}/oi{r['fut_oi_chg3']}/pi{r['put_itm_chg3']}/pcr{r['pcr']}{'/' + ','.join(r['flags']) if r['flags'] else ''}" for r in rows), flush=True)
    # which stocks fired SC / PW in the 10 sessions before 5 Nov 2026 (the rally's big day)
    pre = P.loc["2026-10-20":"2026-11-04"].index
    for name in ("SB short build-up", "SC short covering after short build-up", "PW ITM put writing, price flat", "PWb put writing broad + PCR up", "LB long build-up"):
        hits = {c: [str(d.date())[5:] for d in pre if bool(S[name].at[d, c])] for c in stocks}
        hits = {c: v for c, v in hits.items() if v}
        after = {c: round(float(P[c].iloc[-1] / P.at[pd.Timestamp("2026-11-04"), c] - 1) * 100, 1) for c in hits if pd.notna(P.at[pd.Timestamp("2026-11-04"), c])}
        res.setdefault("pre_rally_hits", {})[name] = dict(count=len(hits), median_gain_since_4nov=round(float(np.median(list(after.values()))), 1) if after else None,
                                                          all_fo_median=round(float((P[stocks].iloc[-1] / P[stocks].loc["2026-11-04"] - 1).median() * 100), 1), hits=hits)
        print("H|", name, len(hits), res["pre_rally_hits"][name]["median_gain_since_4nov"], res["pre_rally_hits"][name]["all_fo_median"], flush=True)
    os.makedirs("data/research", exist_ok=True)
    json.dump(res, open("data/research/fo_squeeze.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
