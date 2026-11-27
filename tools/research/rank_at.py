"""How the app's measures would have ranked given stocks on given past days (28 Nov 2026, Amritpal: "at this time, how were these
stocks ranked as per our app"). The app's files only start on 7 Nov 2026, so the measures are recomputed point in time:
  industry Pulse (tools/group_pulse.py rule: share of the group's liquid stocks 'trending' over the last 21 sessions; trending =
    weighted RPI > 100, EMA9 > EMA21, Stage 2 (close > rising SMA150), close >= 75% of the 52-week high) -> rank among groups,
  stock RS rating 1-99 (0.4 x 3m + 0.2 x 6m + 0.2 x 9m + 0.2 x 12m, ranked across liquid stocks), stock trending, trend template x/8.
Groups = today's NSE basic industries (+ the app's bank / auto / dairy splits) - membership is today's, a small look-ahead."""
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import flag_volume as FV  # noqa: E402

ASK = [("NTPC", "2026-01-29"), ("TATASTEEL", "2026-05-13"), ("WELENT", "2026-06-18"), ("PAGEIND", "2026-06-24"), ("TITAN", "2026-07-21"),
       ("HCG", "2026-08-10")]
SPLIT = {
    "Banks - PSU": ["SBIN", "BANKBARODA", "PNB", "CANBK", "UNIONBANK", "INDIANB", "BANKINDIA", "CENTRALBK", "IOB", "UCOBANK", "MAHABANK", "PSB", "IDBI"],
    "Banks - Private Large": ["HDFCBANK", "ICICIBANK", "KOTAKBANK", "AXISBANK", "INDUSINDBK"],
    "Auto - 2W/3W/EV": ["HEROMOTOCO", "BAJAJ-AUTO", "EICHERMOT", "TVSMOTOR", "TVSHLTD", "OLAELEC", "ATHERENERG", "ATULAUTO", "MERCURYEV"],
    "Auto - PV & Tractors": ["MARUTI", "M&M", "TMPV", "HYUNDAI", "ESCORTS", "VSTTILLERS"],
    "Auto - CV & Buses": ["TMCV", "ASHOKLEY", "SMLMAH", "FORCEMOT", "OLECTRA"],
}


def main():
    P = FV.load()
    C = pd.DataFrame({s: x.CLOSE for s, x in P.items()}).sort_index(); V = pd.DataFrame({s: x.VOL for s, x in P.items()}).reindex(C.index)
    B = yf.download("^NSEI", start="2015-01-01", auto_adjust=True, progress=False)["Close"].squeeze().dropna()
    B.index = pd.to_datetime(B.index).tz_localize(None); B = B.reindex(C.index).ffill()
    liq = ((C * V).rolling(60, min_periods=40).median() >= 2e7) & (C >= 50)
    rpi = lambda k: 100 * (C / C.shift(k)).div(B / B.shift(k), axis=0)  # noqa: E731
    w = (rpi(10) + rpi(63) + rpi(126)) / 3
    e9 = C.ewm(span=9, adjust=False).mean(); e21 = C.ewm(span=21, adjust=False).mean(); s150 = C.rolling(150).mean()
    s50 = C.rolling(50).mean(); s200 = C.rolling(200).mean()
    st2 = (C > s150) & (s150 > s150.shift(20)); hi52 = C.rolling(250, min_periods=120).max(); lo52 = C.rolling(250, min_periods=120).min()
    tr = (w > 100) & (e9 > e21) & st2 & (C >= 0.75 * hi52) & liq
    sh21 = tr.astype(float).rolling(21).mean()
    W = 0.4 * (C / C.shift(63) - 1) + 0.2 * (C / C.shift(126) - 1) + 0.2 * (C / C.shift(189) - 1) + 0.2 * (C / C.shift(252) - 1)
    RS = (W.where(liq).rank(axis=1, pct=True) * 98 + 1).round()
    u = pd.read_csv(os.path.join(HERE, "..", "..", "data", "universe", "nse_industry.csv"))
    grp = dict(zip(u.symbol, u.basic_industry))
    for g, ss in SPLIT.items():
        for s in ss:
            grp[s] = g
    for sym, d in ASK:
        d = pd.Timestamp(d)
        if sym not in C.columns or d not in C.index:
            print(f"R| {sym} {d.date()}: no data", flush=True); continue
        L = liq.loc[d]; mem = {}
        for s in C.columns:
            if L.get(s, False) and s in grp and np.isfinite(sh21.at[d, s]):
                mem.setdefault(grp[s], []).append(sh21.at[d, s])
        pulse = {g: np.mean(v) * 100 for g, v in mem.items() if len(v) >= 3}
        rk = sorted(pulse, key=lambda g: -pulse[g]); g = grp.get(sym)
        pos = rk.index(g) + 1 if g in rk else None
        c = C.at[d, sym]
        tt = int((c > s150.at[d, sym] and c > s200.at[d, sym])) + int(s150.at[d, sym] > s200.at[d, sym]) + int(s200.at[d, sym] > s200[sym].shift(21).at[d]) \
            + int(s50.at[d, sym] > s150.at[d, sym] and s50.at[d, sym] > s200.at[d, sym]) + int(c > s50.at[d, sym]) + int(c >= lo52.at[d, sym] * 1.3) \
            + int(c >= hi52.at[d, sym] * 0.75) + int((RS.at[d, sym] or 0) >= 70)
        print(f"R| {sym} {d.date()} | industry '{g}' Pulse {pulse.get(g, float('nan')):.0f} -> rank {pos} of {len(rk)} "
              f"(top {pos / len(rk) * 100:.0f}%) | stock RS {RS.at[d, sym]:.0f} | trending {bool(tr.at[d, sym])} | Stage 2 {bool(st2.at[d, sym])} | "
              f"trend template {tt}/8 | top 3 groups: {', '.join(f'{x} {pulse[x]:.0f}' for x in rk[:3])}", flush=True)


if __name__ == "__main__":
    main()
