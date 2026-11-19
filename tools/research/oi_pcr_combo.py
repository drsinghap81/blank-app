"""Futures OI build-up + rising PCR as an early buy clue (19 Nov 2026, Amritpal: "Future OI and rise in pcr are two clues").

Data: NSE F&O bhavcopy 2016 -> today (old format to Jul 2024, UDiFF after); per symbol per day: near-futures close, futures OI (all
expiries), put OI and call OI (all expiries) -> PCR. FII index-futures long% from NSE participant OI.
Signals at the close (one event per symbol per 10 sessions):
  OI   short build-up: in the last 10 sessions price fell >= 3% (index) / 5% (stock) while futures OI rose >= 10% / 15%
  PCR  PCR up >= 0.15 over 5 sessions (index) / >= 0.2 (stock)
  COMBO  PCR rise today AND an OI short build-up within the last 10 sessions    <- the idea
  COMBO+UP  COMBO and price above its close 3 sessions ago (squeeze already starting)
  FII  (indices) FII long% was < 25 within 10 sessions and rose >= 8 points in 5 sessions
Forward 5 / 10 / 20 sessions: index return (vs all days); stocks minus the average F&O stock that day.
Output: data/research/oi_pcr_combo.json"""
import io
import json
import os
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fii_oi_filter import fii_series  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36", "Referer": "https://www.nseindia.com/"}
IDX = ("NIFTY", "BANKNIFTY")


def get(url):
    for _ in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=40)
            if r.status_code == 404:
                return None
            if r.ok and r.content[:2] == b"PK":
                z = zipfile.ZipFile(io.BytesIO(r.content)); return pd.read_csv(z.open(z.namelist()[0]))
        except Exception:  # noqa: BLE001
            time.sleep(3)
    return None


def one(day):
    if day < pd.Timestamp("2024-07-08"):
        mon = f"{day:%b}".upper()
        F = get(f"https://archives.nseindia.com/content/historical/DERIVATIVES/{day:%Y}/{mon}/fo{day:%d}{mon}{day:%Y}bhav.csv.zip")
        if F is None:
            return None
        F.columns = [c.strip() for c in F.columns]
        F = F.rename(columns={"INSTRUMENT": "it", "SYMBOL": "sym", "EXPIRY_DT": "exp", "OPTION_TYP": "ot", "CLOSE": "close", "OPEN_INT": "oi"})
        F["exp"] = pd.to_datetime(F.exp, format="%d-%b-%Y", errors="coerce")
        fut = F[F.it.isin(["FUTIDX", "FUTSTK"])]; op = F[F.it.isin(["OPTIDX", "OPTSTK"])]
    else:
        F = get(f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{day:%Y%m%d}_F_0000.csv.zip")
        if F is None:
            return None
        F = F.rename(columns={"FinInstrmTp": "it", "TckrSymb": "sym", "XpryDt": "exp", "OptnTp": "ot", "ClsPric": "close", "OpnIntrst": "oi"})
        F["exp"] = pd.to_datetime(F.exp, errors="coerce")
        fut = F[F.it.isin(["IDF", "STF"])]; op = F[F.it.isin(["IDO", "STO"])]
    near = fut.sort_values("exp").groupby("sym").close.first()
    out = pd.DataFrame({"price": near, "fut_oi": fut.groupby("sym").oi.sum(),
                        "put": op[op.ot.astype(str).str.strip() == "PE"].groupby("sym").oi.sum(),
                        "call": op[op.ot.astype(str).str.strip() == "CE"].groupby("sym").oi.sum()})
    out["Date"] = day
    return out.reset_index().rename(columns={"index": "sym"})


def events(mask, P, horizon, ex=None):
    """one event per symbol per 10 sessions; returns array of forward values"""
    vals, dates = [], {}
    f = ex if ex is not None else (P.shift(-horizon) / P - 1)
    pos = {d: i for i, d in enumerate(P.index)}
    for c in mask.columns:
        last = -99
        for d in mask.index[mask[c].fillna(False).values]:
            i = pos[d]
            if i - last >= 10:
                v = f.at[d, c]
                if pd.notna(v):
                    vals.append(v); dates.setdefault(c, []).append(str(d.date()))
                last = i
    return np.array(vals), dates


def summ(v):
    return dict(n=len(v), avg=round(float(v.mean() * 100), 2) if len(v) else None, median=round(float(np.median(v) * 100), 2) if len(v) else None,
                win=round(float((v > 0).mean() * 100)) if len(v) else None)


def main():
    days = pd.bdate_range("2016-01-01", pd.Timestamp.today())
    with ThreadPoolExecutor(8) as ex:
        parts = [p for p in ex.map(one, days) if p is not None]
    A = pd.concat(parts, ignore_index=True)
    A["sym"] = A.sym.astype(str).str.strip()
    A = A.groupby(["Date", "sym"]).sum(numeric_only=True).reset_index() if A.duplicated(["Date", "sym"]).any() else A
    print("days by year", A.groupby(A.Date.dt.year).Date.nunique().to_dict(), flush=True)
    print("days", A.Date.nunique(), "symbols", A.sym.nunique(), A.Date.min().date(), A.Date.max().date(), flush=True)
    P = A.pivot(index="Date", columns="sym", values="price").sort_index()
    OI = A.pivot(index="Date", columns="sym", values="fut_oi").sort_index()
    PCR = (A.pivot(index="Date", columns="sym", values="put") / A.pivot(index="Date", columns="sym", values="call").replace(0, np.nan)).sort_index()
    # contracts that roll / symbol changes create jumps; ignore OI changes beyond +-60% as data breaks
    r10 = P / P.shift(10) - 1; o10 = (OI / OI.shift(10).replace(0, np.nan) - 1).where(lambda x: x.abs() < 0.6)
    p5 = PCR - PCR.shift(5); r3 = P / P.shift(3) - 1
    res = dict(method=__doc__, days=int(A.Date.nunique()))

    # ---------- indices
    F = fii_series(); fl = F.long.reindex(P.index).ffill()
    fii = ((fl.rolling(10, min_periods=1).min() < 25) & (fl - fl.shift(5) >= 8))
    for ix in IDX:
        sb = (r10[ix] <= -0.03) & (o10[ix] >= 0.10)
        sbr = sb.rolling(10, min_periods=1).max().astype(bool)
        pr = p5[ix] >= 0.15
        S = {"all days": P[ix].notna(), "OI short build-up": sb, "PCR rise": pr, "COMBO": pr & sbr, "COMBO+UP": pr & sbr & (r3[ix] > 0), "FII long turning up": fii}
        res[ix] = {}
        for k, m in S.items():
            res[ix][k] = {}
            for h in (5, 10, 20):
                v, dts = events(pd.DataFrame({ix: m}), P[[ix]], h) if k != "all days" else ((P[ix].shift(-h) / P[ix] - 1).dropna().values, {})
                res[ix][k][h] = summ(np.asarray(v))
                if h == 10 and k not in ("all days",):
                    res[ix][k]["dates"] = dts.get(ix, [])[-25:]
            print("I|", ix, k, {h: res[ix][k][h] for h in (5, 10, 20)}, flush=True)
            if k in ("COMBO", "COMBO+UP", "FII long turning up"):
                print("D|", ix, k, res[ix][k].get("dates"), flush=True)

    # ---------- stocks (minus the average F&O stock)
    st = [c for c in P.columns if c not in IDX and c not in ("FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "NIFTYIT", "CNXIT", "BANKEX", "NIFTYINFRA", "NIFTYMID50", "CNXPSE", "CNXINFRA")]
    sb = (r10[st] <= -0.05) & (o10[st] >= 0.15)
    sbr = sb.rolling(10, min_periods=1).max().fillna(0).astype(bool)
    pr = (p5[st] >= 0.2) & (PCR[st].shift(5) > 0.2)
    S = {"OI short build-up": sb, "PCR rise": pr, "COMBO": pr & sbr, "COMBO+UP": pr & sbr & (r3[st] > 0)}
    res["stocks"] = {}
    for h in (5, 10, 20):
        f = P[st].shift(-h) / P[st] - 1
        f = f.where(f.abs() < 0.6)                      # splits / bonus in futures prices
        exr = f.sub(f.mean(axis=1), axis=0)
        for k, m in S.items():
            v, dts = events(m, P[st], h, exr)
            res["stocks"].setdefault(k, {})[h] = summ(v)
    for k in S:
        print("S|", k, res["stocks"][k], flush=True)
    # by year for COMBO stocks, 10 sessions
    f = P[st].shift(-10) / P[st] - 1; f = f.where(f.abs() < 0.6); exr = f.sub(f.mean(axis=1), axis=0)
    m = S["COMBO"]; by = {}
    for y in sorted(set(P.index.year)):
        mm = m[m.index.year == y]
        v, _ = events(mm, P[st].loc[mm.index], 10, exr.loc[mm.index])
        by[str(y)] = summ(v)
    res["stocks"]["COMBO_by_year_10d"] = by
    print("Y|", by, flush=True)
    os.makedirs("data/research", exist_ok=True)
    json.dump(res, open("data/research/oi_pcr_combo.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
