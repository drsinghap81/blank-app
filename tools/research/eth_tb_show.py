"""ETH Top Bottom - chart markings + trade list for the last 3 years (28 Nov 2026, Amritpal: "show me top bottom markings on the
ETH chart for the last three years and an excel sheet recording each entry, SL points with dates").
Same engine and rules as the paper book (tools/paper_crypto_tb.py): Yahoo ETH-USD daily UTC candles (missing days rebuilt from
hourly), tops/bottoms = 1-day turns of the daily close, buffer 0.05%, entry-day stop 1% on the close, then the opposite system point
(never wider than 2%), breakeven after +2%, 0.1% cost a round trip. Starts flat 3 years ago. Prints R|J lines (JSON chunks)."""
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
import topbottom_backtest as tbb  # noqa: E402
import paper_crypto_tb as pc  # noqa: E402

SYM = os.environ.get("COIN", "ETH-USD")


def main():
    df = pc.bars(SYM)
    today = pd.Timestamp.utcnow().tz_localize(None).normalize()
    df = df[df.index < today]                                   # completed days only
    start = df.index[-1] - pd.DateOffset(years=3)
    c = df.Close.to_numpy(float)
    T, B, piv = tbb.confirmed_swings(c, 0.0)
    buf = lambda v: v * 0.0005  # noqa: E731
    out = dict(sym=SYM, start=str(start.date()), end=str(df.index[-1].date()))
    k0 = int(np.searchsorted(df.index, start))
    out["bars"] = [[str(d.date()), *[round(float(v), 2) for v in r]] for d, r in zip(df.index[k0:], df[["Open", "High", "Low", "Close"]].to_numpy()[k0:])]
    out["pivots"] = [dict(kind=k, day=str(df.index[pi].date()), confirmed=str(df.index[ci].date()), level=round(float(v), 2))
                     for ci, pi, k, v in piv if pi >= k0]
    idx = {d: i for i, d in enumerate(df.index)}
    for nm, long_only in (("both", False), ("buy", True)):
        p = tbb.Params(buffer_pct=0.05, buffer_pts=0, event_exit=False, long_only=long_only, start_flat_on=str(start.date()), **pc.RULES)
        t = tbb.run_live(df, p)
        t = t[pd.to_datetime(t.EntryDate) >= start]
        rows = []; eq = pc.CAP
        for r in t.to_dict("records"):
            i = idx[pd.Timestamp(r["EntryDate"])]; s = 1 if r["Side"] == "BUY" else -1; e = float(r["Entry"])
            d1 = e * (1 - s * 0.01)                               # entry-day stop (checked on the close)
            nxt = e * (1 - s * 0.02)                              # from the next day: opposite system point, max 2%
            if s > 0 and not np.isnan(B[i]):
                nxt = max(nxt, B[i] - buf(B[i]))
            if s < 0 and not np.isnan(T[i]):
                nxt = min(nxt, T[i] + buf(T[i]))
            ret = float(r["Pct"]) / 100 - pc.COST; pnl = eq * ret
            if not r["Open"]:
                eq += pnl
            rows.append(dict(side=r["Side"], signal=r["Signal"], entry_date=str(pd.Timestamp(r["EntryDate"]).date()), entry=round(e, 2),
                             sl_entry_day=round(d1, 2), sl_next_day=round(nxt, 2),
                             swing_top=None if np.isnan(T[i - 1]) else round(float(T[i - 1]), 2),
                             swing_bottom=None if np.isnan(B[i - 1]) else round(float(B[i - 1]), 2),
                             exit_date=str(pd.Timestamp(r["ExitDate"]).date()), exit=round(float(r["Exit"]), 2), reason=r["Reason"],
                             open=bool(r["Open"]), pct=round(ret * 100, 2), pnl=round(pnl, 2), equity=round(eq, 2)))
        out[nm] = rows
        z = [x for x in rows if not x["open"]]
        print(f"R| {nm}: {len(rows)} trades, won {sum(x['pct'] > 0 for x in z)}/{len(z)}, end equity {eq:.0f} from {pc.CAP:.0f}", flush=True)
    s = json.dumps(out, separators=(",", ":"))
    for k in range(0, len(s), 20000):
        print("R|J " + s[k:k + 20000], flush=True)
    print("R|END", flush=True)


if __name__ == "__main__":
    main()
