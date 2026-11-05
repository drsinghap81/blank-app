"""US / ASX version of sector_state.py: trend + RS of the broad, sector and theme indices (Yahoo, full history), and the
stock -> sector / theme map used by the ATH and IPO scans. Usage: python global_state.py US|ASX
Writes data/scan/<mkt>/sectors.json (same keys as the NSE file, so tag_for / stock_rs / topdown work unchanged),
data/scan/<mkt>/sector_hist.csv.gz (daily closes) and refreshes data/universe/<mkt>_meta.csv (weekly, or when missing).
Tag rule as NSE: leading = above a rising 30-week SMA and 3-month return beats the market (S&P 500 / S&P/ASX 200);
RS 6 m vs the same benchmark."""
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from global_sectors import CFG, US_SECTOR_OF, fetch_meta, index_tickers  # noqa: E402
from sector_state import THEME_EXCLUDE, shortlist, slug, state, write_index_charts  # noqa: E402,F401

MKT = sys.argv[1] if len(sys.argv) > 1 else "US"
D = f"data/scan/{MKT.lower()}"
META = f"data/universe/{MKT.lower()}_meta.csv"


def download(tickers):
    import yfinance as yf
    fr = []
    for t in tickers:
        for _ in range(3):
            try:
                x = yf.download(t, period="max", interval="1d", auto_adjust=True, progress=False)
                if x is not None and len(x):
                    x.columns = [c[0] if isinstance(c, tuple) else c for c in x.columns]
                    fr.append(pd.DataFrame({"Date": pd.to_datetime(x.index).tz_localize(None).normalize(), "INDEX": t,
                                            "CLOSE": x.Close.values})); break
            except Exception as e:  # noqa: BLE001
                print("retry", t, e); time.sleep(5)
        time.sleep(0.5)
    return pd.concat(fr).dropna() if fr else pd.DataFrame(columns=["Date", "INDEX", "CLOSE"])


def meta():
    fresh = os.path.exists(META) and (time.time() - os.path.getmtime(META)) < 6 * 86400 and datetime.utcnow().weekday() != 0
    if not fresh:
        try:
            m = fetch_meta(MKT)
            if len(m) > 300:
                m.to_csv(META, index=False); print("meta refreshed", len(m))
        except Exception as e:  # noqa: BLE001
            print("meta fetch failed, keeping old:", e)
    return pd.read_csv(META) if os.path.exists(META) else pd.DataFrame(columns=["symbol", "sector", "industry", "sector_index", "theme"])


def main():
    os.makedirs(D, exist_ok=True)
    c = CFG[MKT]
    today = datetime.now(timezone.utc).date()
    H = download(index_tickers(MKT))
    H.to_csv(f"{D}/sector_hist.csv.gz", index=False)
    P = H.pivot_table(index="Date", columns="INDEX", values="CLOSE", aggfunc="last").sort_index()
    b = P[c["bench"]].dropna()
    mret = float(b.iloc[-1] / b.iloc[-64] - 1)
    idx = {}
    for k in P.columns:
        st = state(P[k], mret, b)
        if st:
            st["name"] = {**c["broad"], **c["sectors"], **c["themes"]}.get(k, k)
            st["shortlist"] = shortlist(st); st["slug"] = slug(k)
            idx[k] = st
    m = meta()
    m = m.dropna(subset=["symbol"])
    if MKT == "US":
        symbols = {s: sec for s, sec in zip(m.symbol, m.sector) if isinstance(sec, str) and sec in US_SECTOR_OF}
        industries = dict(US_SECTOR_OF)
    else:
        symbols = {s: g for s, g, ix in zip(m.symbol, m.industry, m.sector_index) if isinstance(ix, str)}
        industries = {g: ix for g, ix in zip(m.industry, m.sector_index) if isinstance(ix, str)}
    themes = {s: [t] for s, t in zip(m.symbol, m.theme) if isinstance(t, str)}
    out = dict(generated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), asof=str(P.index[-1].date()), market=c["market"], bench=c["bench"], indices=idx, industries=industries,
               symbols=symbols, themes=themes, broad=[k for k in c["broad"] if k in idx], sectors=[k for k in c["sectors"] if k in idx],
               thematic=[k for k in c["themes"] if k in idx], thematic_new=[k for k in c["themes"] if k not in idx],
               names={**c["broad"], **c["sectors"], **c["themes"]})
    fix = lambda v: {k: fix(x) for k, x in v.items()} if isinstance(v, dict) else (None if isinstance(v, float) and not np.isfinite(v) else v)  # noqa: E731
    json.dump(fix(out), open(f"{D}/sectors.json", "w"), indent=0, allow_nan=False)
    write_index_charts(P, idx, f"{D}/index_charts")
    print(MKT, "indices", len(idx), "stocks with sector", len(symbols), "with theme", len(themes), "asof", out["asof"], today)
    for k in out["sectors"] + out["thematic"]:
        v = idx[k]; print(f"  {v['name']:28s} {v['tag']:8s} RS6m {v['rs_6m'] if v['rs_6m'] is None else round(v['rs_6m'], 1)}")


if __name__ == "__main__":
    main()
