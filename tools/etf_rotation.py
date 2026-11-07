"""ETF rotation (core 4): each month hold the best 2 of NIFTYBEES / MID150BEES / GOLDBEES / MON100 by 3-month return;
a pick whose 3-month return is below cash (6.5%/yr -> LIQUIDBEES) is replaced by cash. Decided on the last close of each month,
traded at the next open. Backtest 2016-26 (indices / ETFs, scratchpad etf/): 17.7%/yr, worst monthly fall -12.8%
(Nifty 11.6%, -29%; 25% each static 18%, -16%). Output: data/scan/etf_rotation.json"""
import json, os
from datetime import datetime, timezone
import pandas as pd, yfinance as yf

ETF = {"NIFTYBEES": "Nifty 50", "MID150BEES": "Midcap 150", "GOLDBEES": "Gold", "MON100": "US Nasdaq 100"}
CASH = "LIQUIDBEES"; CASH_YR = 0.065; LOOK = 3; TOP = 2


def main(x=None):
    last_px = {}
    if x is None:
        x = yf.download([s + ".NS" for s in ETF], period="3y", interval="1d", auto_adjust=True, progress=False, group_by="column", threads=True)["Close"]
        x.columns = [c.replace(".NS", "") for c in x.columns]
        from session import drop_partial  # noqa: E402
        x = drop_partial(x, "NSE")
    print("rows per ETF:", x.notna().sum().to_dict(), flush=True)
    last_px = {k: float(v.dropna().iloc[-1]) for k, v in x.items() if v.notna().any()}
    if "MID150BEES" not in x or x["MID150BEES"].notna().sum() < 80:      # Yahoo history for MID150BEES is sparse:
        try:                                                               # rank midcaps on the index it tracks
            h = pd.read_csv("data/scan/sector_hist.csv.gz", index_col=0, parse_dates=True)
            m = h[h.INDEX == "NIFTY MIDCAP 150"].CLOSE.sort_index()
            x["MID150BEES"] = m.reindex(x.index).ffill(); print("MID150BEES ranked on NIFTY MIDCAP 150 index", flush=True)
        except Exception as e:  # noqa: BLE001
            print("midcap fallback failed", e)
    miss = [s for s in ETF if s not in x or x[s].notna().sum() < 80]
    if miss:
        raise SystemExit(f"no price history for {miss}")
    x = x[list(ETF)].dropna(how="all").ffill().dropna()
    last = x.index[-1]
    me = x.groupby(x.index.to_period("M")).tail(1)
    done = me if _month_end(last, x) else me.iloc[:-1]
    cash3 = (1 + CASH_YR) ** (LOOK / 12) - 1

    def pick(row_now, row_then):
        r = (row_now / row_then - 1).dropna().sort_values(ascending=False)
        top = list(r.index[:TOP]); hold = [s if r[s] > cash3 else CASH for s in top]
        return r, hold

    # history of monthly decisions + strategy returns from ETF prices
    hist = []
    for k in range(LOOK, len(done)):
        r, hold = pick(done.iloc[k], done.iloc[k - LOOK])
        nxt = done.iloc[k + 1] if k + 1 < len(done) else x.iloc[-1]
        ret = sum((nxt[s] / done.iloc[k][s] - 1) if s != CASH else (1 + CASH_YR) ** (1 / 12) - 1 for s in hold) / TOP
        hist.append(dict(month=str((done.index[k].to_period("M") + 1)), decided=str(done.index[k].date()), hold=hold,
                         ret_pct=round(ret * 100, 2), partial=k + 1 >= len(done)))
    r_now, hold_now = pick(done.iloc[-1], done.iloc[-1 - LOOK])           # this month's holdings
    r_prov, hold_prov = pick(x.iloc[-1], done.iloc[-LOOK])                 # if the month ended today
    prev = hist[-2]["hold"] if len(hist) >= 2 else []
    out = dict(generated=datetime.now(timezone.utc).isoformat(timespec="minutes"), asof=str(last.date()),
               rule=f"Each month-end: rank NIFTYBEES, MID150BEES, GOLDBEES, MON100 by {LOOK}-month return; hold the best {TOP} equally; "
                    f"a pick below cash ({CASH_YR*100:.1f}%/yr, {cash3*100:.1f}% over {LOOK} months) is held as LIQUIDBEES instead. Trade at the next open.",
               backtest="2016-26 (indices/ETFs, 0.2% per switch): 17.7%/yr, worst month-end fall -12.8%, 5-7 switches a year; 2016-21 19.0%, 2021-26 16.1%. "
                        "Nifty 50 11.6% / -29%; 25% each of the four, never rebalanced to picks: 18% / -16%.",
               names={**ETF, CASH: "Liquid (cash)"}, cash_3m_pct=round(cash3 * 100, 2),
               current=dict(month=hist[-1]["month"] if hist else None, decided=str(done.index[-1].date()), hold=hold_now,
                            ranks=[dict(sym=s, ret_3m_pct=round(v * 100, 2), beats_cash=bool(v > cash3)) for s, v in r_now.items()],
                            buy=sorted(set(hold_now) - set(prev)), sell=sorted(set(prev) - set(hold_now))),
               provisional=dict(asof=str(last.date()), hold=hold_prov,
                                ranks=[dict(sym=s, ret_3m_pct=round(v * 100, 2), beats_cash=bool(v > cash3)) for s, v in r_prov.items()]),
               prices={s: round(last_px[s], 2) for s in ETF if s in last_px and not (s == "MID150BEES" and last_px[s] > 1000)}, history=hist[-24:])
    os.makedirs("data/scan", exist_ok=True); json.dump(out, open("data/scan/etf_rotation.json", "w"), indent=0)
    print("asof", last.date(), "hold", hold_now, "provisional", hold_prov, "ranks", {d['sym']: d['ret_3m_pct'] for d in out['current']['ranks']})


def _month_end(day, x):
    """True when `day` is the last trading day of its month (a later date in the same month would otherwise exist)."""
    nxt = pd.bdate_range(day + pd.Timedelta(days=1), periods=1)[0]
    return nxt.month != day.month


if __name__ == "__main__":
    main()
