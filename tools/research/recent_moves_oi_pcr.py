"""Recent big moves: did futures OI build-up and a PCR rise show up BEFORE them? (19 Nov 2026, Amritpal: "why first you don't check
recent moves"). NSE F&O bhavcopy (UDiFF) Jul -> Nov 2026, every F&O stock + NIFTY / BANKNIFTY.
Move = a 10-session rise of >= 10% (stocks) / >= 4% (indices); start = the lowest close of the 5 sessions before the rise began.
For each move, the 10 sessions BEFORE the start: price change, futures OI change, PCR change; and the start -> +3 sessions.
Control = every other stock-day in the same window that was NOT followed by such a move.
A clue matters only if moves show it clearly more often than the control."""
import io
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36", "Referer": "https://www.nseindia.com/"}


def one(day):
    url = f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{day:%Y%m%d}_F_0000.csv.zip"
    for _ in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=40)
            if r.status_code == 404:
                return None
            if r.ok and r.content[:2] == b"PK":
                z = zipfile.ZipFile(io.BytesIO(r.content)); F = pd.read_csv(z.open(z.namelist()[0]))
                fut = F[F.FinInstrmTp.isin(["IDF", "STF"])]; op = F[F.FinInstrmTp.isin(["IDO", "STO"])]
                near = fut.sort_values("XpryDt").groupby("TckrSymb").first()
                und = near.UndrlygPric.where(near.UndrlygPric > 0, near.ClsPric)
                o = pd.DataFrame({"price": und, "oi": fut.groupby("TckrSymb").OpnIntrst.sum(),
                                  "put": op[op.OptnTp == "PE"].groupby("TckrSymb").OpnIntrst.sum(),
                                  "call": op[op.OptnTp == "CE"].groupby("TckrSymb").OpnIntrst.sum()})
                o["Date"] = day
                return o.reset_index().rename(columns={"TckrSymb": "sym"})
        except Exception:  # noqa: BLE001
            time.sleep(3)
    return None


def main():
    days = pd.bdate_range("2026-06-15", pd.Timestamp.today())
    with ThreadPoolExecutor(6) as ex:
        A = pd.concat([p for p in ex.map(one, days) if p is not None])
    P = A.pivot(index="Date", columns="sym", values="price").sort_index()
    OI = A.pivot(index="Date", columns="sym", values="oi").sort_index()
    PCR = (A.pivot(index="Date", columns="sym", values="put") / A.pivot(index="Date", columns="sym", values="call").replace(0, np.nan)).sort_index()
    print("days", len(P), P.index[0].date(), P.index[-1].date(), "symbols", P.shape[1], flush=True)
    rows = []
    n = len(P)
    for c in P.columns:
        p = P[c]
        thr = 0.04 if c in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50") else 0.10
        i = 15
        while i < n - 10:
            seg = p.iloc[i:i + 11]
            if pd.notna(seg.iloc[0]) and seg.iloc[1:].max() / seg.iloc[0] - 1 >= thr:
                s = i - 5 + int(np.nanargmin(p.iloc[i - 5:i + 1].values))       # start = low of the 5 sessions before
                if s >= 10:
                    b = s - 10
                    def ch(x, a, z):
                        return float(x.iloc[z] / x.iloc[a] - 1) * 100 if x.iloc[a] and pd.notna(x.iloc[a]) and pd.notna(x.iloc[z]) else np.nan
                    rows.append(dict(sym=c, start=str(P.index[s].date()), move=round(float(seg.iloc[1:].max() / p.iloc[s] - 1) * 100, 1),
                                     px_before=round(ch(p, b, s), 1), oi_before=round(ch(OI[c], b, s), 1),
                                     pcr_before=round(float(PCR[c].iloc[s] - PCR[c].iloc[b]), 2) if pd.notna(PCR[c].iloc[s]) and pd.notna(PCR[c].iloc[b]) else np.nan,
                                     pcr_at_start=round(float(PCR[c].iloc[s]), 2) if pd.notna(PCR[c].iloc[s]) else np.nan,
                                     oi_first3=round(ch(OI[c], s, min(s + 3, n - 1)), 1), pcr_first3=round(float(PCR[c].iloc[min(s + 3, n - 1)] - PCR[c].iloc[s]), 2) if pd.notna(PCR[c].iloc[s]) else np.nan))
                i += 15
            else:
                i += 1
    M = pd.DataFrame(rows)
    # control: random stock-days (every 5th session) not within 15 sessions before a move start of the same stock
    ctl = []
    starts = {(r.sym, r.start) for r in M.itertuples()}
    st_idx = {}
    for r in M.itertuples():
        st_idx.setdefault(r.sym, []).append(P.index.get_loc(pd.Timestamp(r.start)))
    for c in P.columns:
        for s in range(15, n - 10, 5):
            if any(0 <= k - s <= 15 or 0 <= s - k <= 10 for k in st_idx.get(c, [])):
                continue
            b = s - 10
            if pd.isna(P[c].iloc[s]) or pd.isna(P[c].iloc[b]) or not OI[c].iloc[b]:
                continue
            ctl.append(dict(px_before=(P[c].iloc[s] / P[c].iloc[b] - 1) * 100, oi_before=(OI[c].iloc[s] / OI[c].iloc[b] - 1) * 100,
                            pcr_before=PCR[c].iloc[s] - PCR[c].iloc[b], pcr_at_start=PCR[c].iloc[s]))
    K = pd.DataFrame(ctl)
    print("moves", len(M), "control", len(K), flush=True)
    tests = [("oi_before", ">", 10, "futures OI +10% or more in the 10 days before"),
             ("pcr_before", ">", 0.15, "PCR up 0.15+ in the 10 days before"),
             ("both", None, None, "BOTH (OI +10% and PCR +0.15)"),
             ("shortbu", None, None, "short build-up before (price down, OI +10%)"),
             ("shortbu_pcr", None, None, "short build-up + PCR up 0.15"),
             ("pcr_at_start", "<", 0.7, "PCR below 0.7 at the start (put side light)")]
    for D in (M, K):
        D["both"] = (D.oi_before > 10) & (D.pcr_before > 0.15)
        D["shortbu"] = (D.px_before < 0) & (D.oi_before > 10)
        D["shortbu_pcr"] = D.shortbu & (D.pcr_before > 0.15)
    for k, op, lv, label in tests:
        f = (lambda s: s > lv) if op == ">" else (lambda s: s < lv) if op == "<" else (lambda s: s.astype(bool))
        a, b = f(M[k]).mean() * 100, f(K[k]).mean() * 100
        print(f"C| {label}: moves {a:.0f}% vs control {b:.0f}%  (median moves {M[k].median() if op else '-'} vs control {K[k].median() if op else '-'})", flush=True)
    for c in ("oi_first3", "pcr_first3"):
        print("F|", c, "median during the first 3 days of the move:", M[c].median(), flush=True)
    M = M.sort_values("start")
    for r in M.itertuples():
        if r.sym in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY") or r.move >= 15:
            print("M|", r.sym, r.start, f"move +{r.move}%", f"before: px {r.px_before}% oi {r.oi_before}% pcr {r.pcr_before:+} (at start {r.pcr_at_start})",
                  f"first 3 days: oi {r.oi_first3}% pcr {r.pcr_first3:+}", flush=True)


if __name__ == "__main__":
    main()
