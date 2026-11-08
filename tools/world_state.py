"""World indices for the top-down view: trend, relative strength and monthly-ATH status (Yahoo daily, full history).

Per index (as of the last completed week / last close):
  tag        : leading / uptrend / mixed / weak - same rule as sectors (above a RISING 30-week SMA; 3-month return vs
               MSCI World (URTH ETF))
  rs_6m      : 126-day RS vs MSCI World (URTH), rs_6m_up = higher than 20 trading days ago
  ATH month  : like the stock system - trigger = HIGH of the highest-closing completed month; base_months = its age;
               crossed = price traded above the trigger this month or last; ath_breakout = crossed with base >= 24 months
Risk-on (used by the top-down score) = S&P 500 AND MSCI World both above a rising 30-week SMA.
Writes data/scan/world.json and data/scan/world_hist.csv.gz (daily closes, for backtests)."""
import json
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

OUT = "data/scan/world.json"
HIST = "data/scan/world_hist.csv.gz"
WORLD = {  # ticker: (name, region)
    "^GSPC": ("S&P 500", "US"), "^NDX": ("Nasdaq 100", "US"), "^DJI": ("Dow Jones", "US"), "^RUT": ("Russell 2000", "US"),
    "^GDAXI": ("DAX", "Europe"), "^FTSE": ("FTSE 100", "Europe"), "^STOXX50E": ("Euro Stoxx 50", "Europe"),
    "^N225": ("Nikkei 225", "Asia"), "^HSI": ("Hang Seng", "Asia"), "000001.SS": ("Shanghai Composite", "Asia"),
    "^KS11": ("KOSPI", "Asia"), "^AXJO": ("ASX 200", "Asia"),
    "URTH": ("MSCI World (ETF)", "Global"), "EEM": ("MSCI Emerging Markets (ETF)", "Global"),
    "^NSEI": ("Nifty 50", "India"), "^CRSLDX": ("Nifty 500", "India"),
}
BENCH = "URTH"
RS_N, RS_RISE = 126, 20


def download():
    import yfinance as yf
    frames = []
    for t in WORLD:
        for _ in range(3):
            try:
                x = yf.download(t, period="max", interval="1d", auto_adjust=False, progress=False)
                if x is not None and len(x):
                    x.columns = [c[0] if isinstance(c, tuple) else c for c in x.columns]
                    x = x[["Open", "High", "Low", "Close"]].dropna(subset=["Close"])
                    x["TICKER"] = t; x.index.name = "Date"
                    frames.append(x.reset_index()); break
            except Exception as e:  # noqa: BLE001
                print("retry", t, e); time.sleep(5)
        time.sleep(1)
    H = pd.concat(frames)
    H["Date"] = pd.to_datetime(H.Date).dt.tz_localize(None).dt.normalize()
    H.to_csv(HIST, index=False)
    return H


def state(x, bench_close, today):
    c = x.Close; h = x.High.where(x.High > 0, c)
    if len(c) < 200:
        return None
    wk = c.groupby(c.index.to_period("W-FRI")).last()
    if c.index[-1].weekday() != 4 and (today - c.index[-1].date()).days < 3:
        wk = wk.iloc[:-1]
    sma = wk.rolling(30, min_periods=30).mean()
    up = bool(wk.iloc[-1] > sma.iloc[-1] and sma.iloc[-1] > sma.iloc[-5])
    j = pd.concat([c, bench_close], axis=1, join="inner").dropna()
    r3 = float(c.iloc[-1] / c.iloc[-64] - 1)
    b3 = float(j.iloc[-1, 1] / j.iloc[-64, 1] - 1) if len(j) > 64 else np.nan
    beat = bool(r3 > b3) if np.isfinite(b3) else False
    tag = "leading" if up and beat else "uptrend" if up else "mixed" if beat else "weak"
    rs = (j.iloc[:, 0] / j.iloc[:, 0].shift(RS_N)) / (j.iloc[:, 1] / j.iloc[:, 1].shift(RS_N)) - 1 if len(j) > RS_N + RS_RISE else None
    rs_now = float(rs.iloc[-1]) if rs is not None else np.nan
    rs_up = bool(rs.iloc[-1] > rs.iloc[-1 - RS_RISE]) if rs is not None else None
    mon = c.index.to_period("M")
    M = pd.DataFrame({"h": h.groupby(mon).max(), "c": c.groupby(mon).last()})
    done = M.iloc[:-1]
    best_m = done.c.idxmax()
    trig = float(done.h.loc[best_m]); base = int((M.index[-1] - best_m).n)
    cur_hi = float(M.h.iloc[-1]); last_hi = float(M.h.iloc[-2]) if len(M) > 1 else np.nan
    crossed = bool(cur_hi > trig)
    # the cross may have happened last month (then last month is the new ATH month): look one month back too
    prev = M.iloc[:-2]
    if len(prev):
        pb = prev.c.idxmax(); ptrig = float(prev.h.loc[pb]); pbase = int((M.index[-2] - pb).n)
        crossed_last = bool(last_hi > ptrig)
    else:
        ptrig, pbase, crossed_last = np.nan, 0, False
    brk = (crossed and base >= 24) or (crossed_last and pbase >= 24)
    return dict(close=float(c.iloc[-1]), sma30=float(sma.iloc[-1]), up=up, ret_3m=r3 * 100,
                vs_world_3m=(r3 - b3) * 100 if np.isfinite(b3) else None, tag=tag,
                rs_6m=rs_now * 100 if np.isfinite(rs_now) else None, rs_6m_up=rs_up,
                from_high=float(c.iloc[-1] / c.max() - 1) * 100, ath_trigger=trig, ath_month=str(best_m), base_months=base,
                crossed=crossed or crossed_last, ath_breakout=bool(brk), since=str(c.index[0].date()))


def main():
    today = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).date()
    H = download()
    G = {t: g.set_index("Date").sort_index() for t, g in H.groupby("TICKER")}
    b = G[BENCH].Close if BENCH in G else None
    out = {}
    for t, (name, region) in WORLD.items():
        if t not in G or b is None:
            continue
        st = state(G[t], b, today)
        if st:
            out[t] = dict(name=name, region=region, **st)
    risk_on = bool(out.get("^GSPC", {}).get("up") and out.get("URTH", {}).get("up"))
    res = dict(generated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), asof=str(pd.Series([g.index[-1].date() for g in G.values()]).mode().max()), benchmark="MSCI World (URTH)", risk_on=risk_on, indices=out)
    fix = lambda v: {k: fix(x) for k, x in v.items()} if isinstance(v, dict) else (None if isinstance(v, float) and not np.isfinite(v) else v)  # noqa: E731
    json.dump(fix(res), open(OUT, "w"), indent=0, allow_nan=False)
    print("world indices", len(out), "risk-on", risk_on)
    for t, v in out.items():
        print(f"  {v['name']:28s} {v['tag']:8s} RS6m {v['rs_6m'] if v['rs_6m'] is None else round(v['rs_6m'], 1)} from high {v['from_high']:.1f}% "
              f"base {v['base_months']}m {'ATH BREAKOUT' if v['ath_breakout'] else ''}")


if __name__ == "__main__":
    main()
