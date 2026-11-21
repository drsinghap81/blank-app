"""PSU bank rally Nov 2026: what unusual showed up in the days before? (21 Nov 2026, Amritpal: "check a few days back what unusual
happened in related data for an early clue").

PSU Bank index began outperforming on 5 Nov 2026 (+3.1% vs Nifty +2.4%), then 9 / 11 Nov (+3.4%, +2.9%). Daily, 1 Sep -> 20 Nov 2026,
from NSE's public files (one fetch per day):
  sec_bhavdata_full (CM)  : close, traded value, delivery % per stock
  F&O bhavcopy (UDiFF)    : stock-futures OI (all expiries), stock-option call / put OI (PCR), futures close
  participant-wise OI     : FII long % in index futures and in stock futures
Groups: 12 PSU banks (NSE basic industry 'Public Sector Bank') vs 10 large private banks (control). Per group per day (equal weight):
  return; traded value vs its own Sep average (x); delivery % minus its Sep average (pts); futures OI change vs Sep end (%);
  share of F&O members with long build-up that day (price up, OI up); put-call OI ratio; cumulative OBV in Sep-average days.
Printed as a daily table from 13 Oct, plus per-stock values for the 5 days before 5 Nov. PILOT env = only 1-10 Sep + 27 Oct-6 Nov."""
import io
import os
import time
import zipfile
from datetime import date, timedelta

import numpy as np
import pandas as pd
import requests

PILOT = bool(os.environ.get("PILOT"))
H = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.nseindia.com/"}
PSU = ["SBIN", "PNB", "BANKBARODA", "CANBK", "UNIONBANK", "BANKINDIA", "INDIANB", "MAHABANK", "IOB", "UCOBANK", "CENTRALBK", "PSB"]
PVT = ["HDFCBANK", "ICICIBANK", "KOTAKBANK", "AXISBANK", "INDUSINDBK", "FEDERALBNK", "IDFCFIRSTB", "BANDHANBNK", "RBLBANK", "AUBANK"]
ALL = PSU + PVT


def get(url):
    for _ in range(3):
        try:
            r = requests.get(url, headers=H, timeout=40)
            if r.status_code == 404:
                return None
            if r.status_code == 200 and len(r.content) > 200:
                return r.content
        except Exception:  # noqa: BLE001
            pass
        time.sleep(2)
    return None


def day(d):
    out = {}
    b = get(f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{d:%d%m%Y}.csv")
    if not b:
        return None
    cm = pd.read_csv(io.BytesIO(b)); cm.columns = [c.strip() for c in cm.columns]
    cm = cm[cm.SERIES.astype(str).str.strip() == "EQ"]; cm["SYMBOL"] = cm.SYMBOL.str.strip(); cm = cm.set_index("SYMBOL")
    for s in ALL:
        if s in cm.index:
            r = cm.loc[s]
            out[s] = dict(close=float(r.CLOSE_PRICE), val=float(r.TURNOVER_LACS) * 1e5,
                          dp=pd.to_numeric(str(r.DELIV_PER).strip(), errors="coerce"))
    z = get(f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000.csv.zip")
    if z and z[:2] == b"PK":
        f = pd.read_csv(zipfile.ZipFile(io.BytesIO(z)).open(zipfile.ZipFile(io.BytesIO(z)).namelist()[0]))
        f = f[f.TckrSymb.isin(ALL)]
        fut = f[f.FinInstrmTp == "STF"].groupby("TckrSymb").OpnIntrst.sum()
        opt = f[f.FinInstrmTp == "STO"].groupby(["TckrSymb", "OptnTp"]).OpnIntrst.sum().unstack()
        for s in ALL:
            if s in out:
                out[s]["foi"] = float(fut.get(s, np.nan))
                if opt is not None and s in opt.index:
                    ce, pe = opt.loc[s].get("CE", np.nan), opt.loc[s].get("PE", np.nan)
                    out[s]["pcr"] = float(pe / ce) if ce else np.nan
    p = get(f"https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_{d:%d%m%Y}.csv")
    fii = {}
    if p:
        try:
            t = pd.read_csv(io.BytesIO(p), skiprows=1); t.columns = [c.strip() for c in t.columns]
            r = t[t.iloc[:, 0].astype(str).str.strip().str.upper() == "FII"].iloc[0]
            fl, fs = float(r["Future Index Long"]), float(r["Future Index Short"]); sl, ss = float(r["Future Stock Long"]), float(r["Future Stock Short"])
            fii = dict(fii_idx_long=round(fl / (fl + fs) * 100, 1), fii_stk_long=round(sl / (sl + ss) * 100, 1))
        except Exception as e:  # noqa: BLE001
            print("participant parse", d, e)
    return out, fii


def main():
    start, end = date(2026, 9, 1), date(2026, 11, 20)
    want = None
    if PILOT:
        want = {start + timedelta(k) for k in range(10)} | {date(2026, 10, 27) + timedelta(k) for k in range(11)}
    rows, F = {}, {}
    d = start
    while d <= end:
        if d.weekday() < 5 and (want is None or d in want):
            r = day(d)
            if r:
                rows[pd.Timestamp(d)], F[pd.Timestamp(d)] = r
            time.sleep(0.4)
        d += timedelta(1)
    print("R| sessions", len(rows), min(rows).date(), "->", max(rows).date(), flush=True)
    recs = [dict(date=t, sym=s, **v) for t, x in rows.items() for s, v in x.items()]
    D = pd.DataFrame(recs).sort_values(["sym", "date"])
    g = D.groupby("sym")
    D["ret"] = g.close.pct_change() * 100
    D["foi_chg"] = g.foi.pct_change() * 100
    D["lb"] = (D.ret > 0) & (D.foi_chg > 0)
    base = D[D.date < "2026-10-01"].groupby("sym").agg(val0=("val", "mean"), dp0=("dp", "mean"))
    D = D.join(base, on="sym")
    D["valx"] = D.val / D.val0; D["dp_d"] = D.dp - D.dp0
    D["obv"] = np.sign(D.ret.fillna(0)) * D.val / D.val0
    D["obv_c"] = D.groupby("sym").obv.cumsum()
    D["grp"] = np.where(D.sym.isin(PSU), "PSU", "PVT")
    sep_end = D[D.date < "2026-10-01"].groupby("sym").foi.last()
    D["foi_vs_sep"] = (D.foi / D.sym.map(sep_end) - 1) * 100
    A = D.groupby(["date", "grp"]).agg(ret=("ret", "mean"), valx=("valx", "median"), dp_d=("dp_d", "mean"), foi=("foi_vs_sep", "mean"),
                                       lb=("lb", "mean"), pcr=("pcr", "median"), obv=("obv_c", "mean")).unstack()
    fii = pd.DataFrame(F).T
    show = A.loc["2026-10-13":] if not PILOT else A
    print("R| daily, PSU vs private banks (ret %, value x Sep avg, delivery pts vs Sep, futures OI % vs Sep end, long build-up share, PCR, cum OBV)", flush=True)
    for t, r in show.iterrows():
        f = fii.loc[t] if t in fii.index else {}
        print(f"R| {t.date()} PSU ret {r[('ret','PSU')]:+.2f} val {r[('valx','PSU')]:.2f}x deliv {r[('dp_d','PSU')]:+.1f} futOI {r[('foi','PSU')]:+.1f}% "
              f"LB {r[('lb','PSU')] * 100:.0f}% PCR {r[('pcr','PSU')]:.2f} OBV {r[('obv','PSU')]:+.1f} | PVT ret {r[('ret','PVT')]:+.2f} val {r[('valx','PVT')]:.2f}x "
              f"deliv {r[('dp_d','PVT')]:+.1f} futOI {r[('foi','PVT')]:+.1f}% LB {r[('lb','PVT')] * 100:.0f}% PCR {r[('pcr','PVT')]:.2f} OBV {r[('obv','PVT')]:+.1f} | "
              f"FII idx long {f.get('fii_idx_long', np.nan)} stk long {f.get('fii_stk_long', np.nan)}", flush=True)
    pre = D[(D.date >= "2026-10-28") & (D.date <= "2026-11-04") & D.sym.isin(PSU)]
    print("R| per PSU bank, 28 Oct - 4 Nov (before the breakout) vs Sep:", flush=True)
    for s, x in pre.groupby("sym"):
        print(f"R|   {s}: ret {x.ret.sum():+.1f}% value {x.valx.mean():.2f}x deliv {x.dp_d.mean():+.1f} pts futOI {x.foi_vs_sep.iloc[-1]:+.1f}% vs Sep end, "
              f"PCR {x.pcr.iloc[-1]:.2f}, long build-up days {int(x.lb.sum())}/{len(x)}", flush=True)
    D.to_csv("/tmp/psu_lookback.csv", index=False)


if __name__ == "__main__":
    main()
