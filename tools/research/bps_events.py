"""Bull put spread test, step 1 (17 Nov 2026): support touches in an uptrend on F&O stocks, 2017 - Nov 2026, plus matched
random uptrend days (control), and the option-data windows to fetch (data/optwin_put.csv -> fetch_optstk.py with OPT_TYPE=PE).
Events: swing-low LEVEL touches and support LINE touches (app rules, research/level_reaction.py), trend = close > 200-day
and 50-day > 200-day. Control: random uptrend days of the same stocks, pretend support at the same % below the close as a
random real touch. Output: data/research/bps_events.csv."""
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(__file__))
import level_reaction as R  # noqa: E402

rng = np.random.default_rng(11)


def main():
    syms = pd.read_csv("data/universe/fno_stocks.csv").Symbol.tolist()
    ev = []
    for k in range(0, len(syms), 50):
        batch = [s + ".NS" for s in syms[k:k + 50]]
        D = yf.download(batch, start="2015-06-01", interval="1d", auto_adjust=False, group_by="ticker", progress=False, threads=True)
        for s in batch:
            try:
                df = D[s].dropna(subset=["Close"])
            except Exception:  # noqa: BLE001
                continue
            if len(df) >= 400:
                ev += R.scan(s[:-3], df)
        print("done", k + 50, len(ev), flush=True)
    E = pd.DataFrame(ev)
    E = E[(E.d >= "2017-01-01") & (E.side == "sup") & (E.trend == 1)]
    T = E[E.kind.isin(["level", "line"])].copy()
    T["dist"] = T.close / T.L - 1
    C = E[E.kind == "control"].sample(n=min(4000, (E.kind == "control").sum()), random_state=5).copy()
    C["dist"] = rng.choice(T.dist.clip(0, 0.03).values, size=len(C))
    C["L"] = C.close / (1 + C.dist)
    out = pd.concat([T, C])[["sym", "d", "kind", "L", "close", "dist", "nth"]]
    os.makedirs("data/research", exist_ok=True)
    out.to_csv("data/research/bps_events.csv", index=False)
    w = out.assign(start=out.d, end=(pd.to_datetime(out.d) + pd.Timedelta(days=62)).dt.date.astype(str))[["sym", "start", "end"]]
    w["sys"] = "BPS"
    if not os.environ.get("KEEP_WIN"):
        w.to_csv("data/optwin_put.csv", index=False)
    print(out.kind.value_counts().to_dict())


if __name__ == "__main__":
    main()
