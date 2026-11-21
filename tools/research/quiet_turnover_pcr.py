"""Part B of the quiet-turnover test (21 Nov 2026): add the option put-call ratio and FII positioning (NSE F&O data, Jul 2024 -> today).

Per NSE sector of F&O stocks (3+ F&O members), daily from NSE's public files:
  CM bhavcopy -> closes and traded value; F&O bhavcopy -> stock-option put and call OI summed over members (PCR = puts / calls);
  participant-wise OI -> FII long % in index futures.
Weekly (Friday close): turnover x (last 5 sessions vs the 60 before), 10-session return, PCR now minus 10 sessions ago.
Sets: quiet turnover (x >= 1.5, flat +-3%) | + PCR up >= 0.10 | + FII index long < 20% | PCR up alone | all.
Outcomes: next 4 / 8 weeks vs Nifty, reaching Leading within 4 / 8 weeks (weekly RRG as the app). PILOT env = last 70 sessions (coverage).
Output data/research/quiet_turnover_pcr.json"""
import io
import json
import os
import sys
import time
import zipfile
from datetime import date, timedelta

import numpy as np
import pandas as pd
import requests
import yfinance as yf

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nse_bhav  # noqa: E402
from quiet_turnover import st  # noqa: E402

PILOT = bool(os.environ.get("PILOT"))
H = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.nseindia.com/"}
CACHE = "/tmp/nse_fo2"


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


def fo(d):
    os.makedirs(CACHE, exist_ok=True); p = f"{CACHE}/{d:%Y%m%d}.pkl"
    if os.path.exists(p):
        return pd.read_pickle(p)
    z = get(f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000.csv.zip")
    if not z or z[:2] != b"PK":
        return None
    zf = zipfile.ZipFile(io.BytesIO(z)); b = pd.read_csv(zf.open(zf.namelist()[0]))
    o = b[b.FinInstrmTp == "STO"].groupby(["TckrSymb", "OptnTp"]).OpnIntrst.sum().unstack().fillna(0)
    o.to_pickle(p); return o


def fii(d):
    p = get(f"https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_{d:%d%m%Y}.csv")
    if not p:
        return np.nan
    try:
        t = pd.read_csv(io.BytesIO(p), skiprows=1); t.columns = [c.strip() for c in t.columns]
        r = t[t.iloc[:, 0].astype(str).str.strip().str.upper() == "FII"].iloc[0]
        a, b = float(r["Future Index Long"]), float(r["Future Index Short"]); return a / (a + b) * 100
    except Exception:  # noqa: BLE001
        return np.nan


def main():
    G = json.load(open("data/scan/group_pulse.json"))
    SEC = {m["symbol"]: r.get("sector") for r in G["nse"]["rows"] for m in r["members"]}
    end = date.today(); start = max(date(2024, 7, 8), end - timedelta(days=105 if PILOT else 900))
    CE, PE, CL, VAL, F = {}, {}, {}, {}, {}
    d = start; n = 0
    while d <= end:
        if d.weekday() < 5:
            o = fo(d)
            if o is not None:
                c = nse_bhav.bhav(d)
                if c is not None:
                    t = pd.Timestamp(d); CE[t] = o.get("CE"); PE[t] = o.get("PE"); CL[t] = c.Close; VAL[t] = c.Close * c.Volume; F[t] = fii(d); n += 1
                    if n % 50 == 0:
                        print("sessions", n, d, flush=True)
            time.sleep(0.3)
        d += timedelta(1)
    CE, PE, CL, VAL = (pd.DataFrame(x).T.sort_index() for x in (CE, PE, CL, VAL)); F = pd.Series(F).sort_index()
    fno = [s for s in CE.columns if s in CL.columns and SEC.get(s)]
    secs = {}
    for s in fno:
        secs.setdefault(SEC[s], []).append(s)
    secs = {k: v for k, v in secs.items() if len(v) >= 3}
    print(f"R| sessions {len(CL)} ({CL.index[0].date()} -> {CL.index[-1].date()}), F&O stocks {len(fno)}, sectors {len(secs)}; FII long% "
          f"min {F.min():.1f} max {F.max():.1f} now {F.iloc[-1]:.1f}", flush=True)
    nif = yf.download("^NSEI", start=str(CL.index[0].date() - timedelta(days=10)), auto_adjust=True, progress=False)["Close"].squeeze()
    nif.index = pd.to_datetime(nif.index).tz_localize(None); nif = nif.reindex(CL.index).ffill()
    ret = CL.pct_change(fill_method=None).clip(-0.3, 0.3)
    P, T, R = {}, {}, {}
    for k, m in secs.items():
        P[k] = (1 + ret[m].mean(axis=1).fillna(0)).cumprod(); T[k] = VAL[m].sum(axis=1, min_count=1)
        R[k] = PE[m].sum(axis=1) / CE[m].sum(axis=1).replace(0, np.nan)
    P, T, R = pd.DataFrame(P), pd.DataFrame(T), pd.DataFrame(R)
    tx = T.rolling(5).mean() / T.shift(5).rolling(60, min_periods=40).mean(); r10 = (P / P.shift(10) - 1) * 100; dp = R - R.shift(10)
    W = P.resample("W-FRI").last(); NW = nif.resample("W-FRI").last()
    RS = 100 * W.div(NW, axis=0); ratio = 100 * RS / RS.rolling(10).mean(); mom = (100 * ratio / ratio.shift(1)).rolling(3).mean()
    Q = pd.DataFrame(np.where(ratio >= 100, np.where(mom >= 100, "L", "W"), np.where(mom >= 100, "I", "G")), index=W.index, columns=W.columns).where(ratio.notna() & mom.notna())
    f4 = (W.shift(-4) / W - 1).sub(NW.shift(-4) / NW - 1, axis=0) * 100; f8 = (W.shift(-8) / W - 1).sub(NW.shift(-8) / NW - 1, axis=0) * 100
    txw, r10w, dpw, Rw = (x.resample("W-FRI").last() for x in (tx, r10, dp, R)); Fw = F.resample("W-FRI").last()
    rows = []
    for t in W.index:
        for k in W.columns:
            if pd.isna(Q.at[t, k]) or pd.isna(txw.at[t, k]) or pd.isna(f4.at[t, k]) or pd.isna(dpw.at[t, k]):
                continue
            fut = Q[k].loc[t:]
            rows.append(dict(w=t, g=k, q=Q.at[t, k], tx=txw.at[t, k], r10=r10w.at[t, k], dpcr=dpw.at[t, k], pcr=Rw.at[t, k], fii=Fw.get(t, np.nan),
                             f4=f4.at[t, k], f8=f8.at[t, k] if pd.notna(f8.at[t, k]) else np.nan,
                             L4=bool((fut.iloc[1:5] == "L").any()), L8=bool((fut.iloc[1:9] == "L").any())))
    X = pd.DataFrame(rows)
    print("R| sector-weeks", len(X), flush=True)
    last_w = W.index[-1]
    now = [(k, round(float(tx.iloc[-1][k]), 2), round(float(r10.iloc[-1][k]), 1), round(float(R.iloc[-1][k]), 2), round(float(dp.iloc[-1][k]), 2)) for k in P.columns]
    print("R| now (turnover x, 10-day %, PCR, PCR change 10d):", sorted(now, key=lambda z: -z[1]), flush=True)
    if PILOT or not len(X):
        return
    quiet = (X.tx >= 1.5) & (X.r10.abs() <= 3); pup = X.dpcr >= 0.10
    sets = {"all": X.index == X.index, "quiet turnover": quiet, "quiet turnover + PCR up >= 0.10": quiet & pup,
            "quiet turnover + PCR up + FII index long < 20%": quiet & pup & (X.fii < 20), "PCR up >= 0.10 alone": pup,
            "PCR up + flat (any turnover)": pup & (X.r10.abs() <= 3), "FII index long < 20% (all sectors)": X.fii < 20}
    res = dict(method=__doc__, sets={k: st(X[m]) for k, m in sets.items()})
    for k, v in res["sets"].items():
        print(f"R| {k}: {v}", flush=True)
    os.makedirs("data/research", exist_ok=True)
    json.dump(res, open("data/research/quiet_turnover_pcr.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
