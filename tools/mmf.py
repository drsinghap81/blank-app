"""US money-market fund assets ("cash on the sidelines") for the World page (21 Nov 2026, Amritpal: "Yes").

FRED (St. Louis Fed), public CSV:
  MMMFFAQ027S  Money Market Funds; Total Financial Assets, Level (Fed Z.1 Financial Accounts, quarterly, US$ millions) - the series in
               the reel; published ~10 weeks after each quarter; FRED dates a quarter by its first day (2026-04-01 = Apr-Jun 2026)
  WRMFNS + WIMFNS  retail + institutional money funds (weekly, US$ billions; ICI data via the Fed's H.6) - the timelier read
Context only, not a timing signal: balances grow with interest rates; record highs in 2023-25 came with rising stocks; big outflows
have usually followed rate cuts or a crisis rather than preceding rallies. Output data/scan/mmf.json."""
import io
import json
from datetime import date

import pandas as pd
import requests


def fred(sid):
    r = requests.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}", timeout=30)
    d = pd.read_csv(io.StringIO(r.text)); d.columns = ["Date", "v"]; d = d[pd.to_numeric(d.v, errors="coerce").notna()]
    return pd.Series(d.v.astype(float).values, index=pd.to_datetime(d.Date))


def main():
    out = dict(generated=str(date.today()), note=__doc__.split("\n\n")[0])
    try:
        q = fred("MMMFFAQ027S") / 1e6        # US$ trillions
        out["quarterly"] = dict(asof=str(q.index[-1].date()), tn=round(float(q.iloc[-1]), 2), yoy=round(float((q.iloc[-1] / q.iloc[-5] - 1) * 100), 1),
                                hist=[[str(i.date()), round(float(v), 2)] for i, v in q[q.index >= "2000-01-01"].items()])
    except Exception as e:  # noqa: BLE001
        print("quarterly fail", e)
    try:
        w = (fred("WRMFNS") + fred("WIMFNS")).dropna() / 1e3   # US$ trillions
        if (pd.Timestamp(date.today()) - w.index[-1]).days > 60:
            raise ValueError(f"weekly series stale (last {w.index[-1].date()}) - FRED stopped the H.6 weekly money-fund series")
        out["weekly"] = dict(asof=str(w.index[-1].date()), tn=round(float(w.iloc[-1]), 2), chg4w=round(float(w.iloc[-1] - w.iloc[-5]), 3),
                             yoy=round(float((w.iloc[-1] / w.iloc[-53] - 1) * 100), 1), hist=[[str(i.date()), round(float(v), 3)] for i, v in w.tail(104).items()])
    except Exception as e:  # noqa: BLE001
        print("weekly fail", e)
    json.dump(out, open("data/scan/mmf.json", "w"), separators=(",", ":"))
    print("mmf", {k: {kk: vv for kk, vv in v.items() if kk != "hist"} for k, v in out.items() if isinstance(v, dict)})


if __name__ == "__main__":
    main()
