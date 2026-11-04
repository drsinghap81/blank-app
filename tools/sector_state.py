"""Sector state for the ATH / IPO scans: is each stock's sector index in an uptrend and beating the market?

Data: NSE daily ind_close_all_DDMMYYYY.csv (all NSE indices). The cache data/scan/sector_hist.csv.gz keeps the
full daily history (from Nov 2015, the start of NSE's archive) of the sector, thematic and benchmark indices; each run
downloads only the missing days. Thematic indices (THEMATIC, the niftyindices.com list) get the same state plus
monthly-ATH status; some have gaps in NSE's archive before 2024 and seven started in 2025-26.
Tag per sector index (as of the last completed week / last close):
  leading : above a rising 30-week SMA (higher than 4 weeks earlier) AND 3-month return beats Nifty 500
  uptrend : above a rising 30-week SMA, not beating Nifty 500
  weak    : NOT above a rising 30-week SMA AND lagging Nifty 500   (ATH breakouts here won only 31% in the backtest)
  mixed   : not in an uptrend but beating Nifty 500
Backtest (project note claude/sector-indices.md): ATH breakouts win 54% when the sector is in an uptrend vs 40% when not,
31% in 'weak' sectors; average returns are NOT higher, so this is a tag, not a filter.
Relative strength (Amritpal, tested 1 Nov 2026): RS = (P/P[n])/(B/B[n]) - 1.
  sector RS: 126 days vs Nifty 50 (rs_6m, rs_6m_up = higher than 20 days ago)
  stock RS : 250 days vs its sector index, or Nifty 500 if the stock has no sector (computed in the scans via stock_rs)
  ATH backtest: sector RS>0 AND stock RS>0 ~+30%/trade vs ~+17%; 1-year stock RS<0 -> 30% win, +3%. The July-2024
  anchored length (~585 days) tested weaker and partly inverted.
Writes data/scan/sectors.json: {asof, indices: {name: {...}}, industries: {industry: index}, symbols: {symbol: industry}}."""
import glob
import io
import json
import os
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import requests

OUT = "data/scan/sectors.json"
CACHE = "data/scan/sector_hist.csv.gz"
MARKET = "NIFTY 500"
INDUSTRY_INDEX = {
    "Financial Services": "NIFTY FINANCIAL SERVICES", "Capital Goods": "NIFTY INFRASTRUCTURE", "Healthcare": "NIFTY PHARMA",
    "Automobile and Auto Components": "NIFTY AUTO", "Chemicals": "NIFTY COMMODITIES", "Fast Moving Consumer Goods": "NIFTY FMCG",
    "Information Technology": "NIFTY IT", "Consumer Services": "NIFTY INDIA CONSUMPTION", "Power": "NIFTY ENERGY",
    "Oil Gas & Consumable Fuels": "NIFTY ENERGY", "Metals & Mining": "NIFTY METAL", "Consumer Durables": "NIFTY INDIA CONSUMPTION",
    "Realty": "NIFTY REALTY", "Services": "NIFTY SERVICES SECTOR", "Construction": "NIFTY INFRASTRUCTURE",
    "Telecommunication": "NIFTY INFRASTRUCTURE", "Construction Materials": "NIFTY COMMODITIES",
    "Media Entertainment & Publication": "NIFTY MEDIA",
}
EXTRA = ["NIFTY BANK", "NIFTY PSU BANK", "NIFTY PRIVATE BANK", "NIFTY PSE", "NIFTY CPSE", "NIFTY OIL & GAS", "NIFTY HEALTHCARE INDEX",
         "NIFTY CONSUMER DURABLES", "NIFTY INDIA DEFENCE", "NIFTY CAPITAL MARKETS", "NIFTY INDIA RAILWAYS PSU", "NIFTY CHEMICALS",
         "NIFTY 50", "NIFTY MIDCAP 150", "NIFTY SMALLCAP 250"]
# every index on niftyindices.com "Thematic Indices" (names as in NSE's daily ind_close_all file), 5 Nov 2026
THEMATIC = ["NIFTY AI CATALYSTS", "NIFTY INDIA CORPORATE GROUP INDEX - ADITYA BIRLA GROUP", "NIFTY CAPITAL MARKETS", "NIFTY COMMODITIES",
            "NIFTY CONGLOMERATE 50", "NIFTY CORE HOUSING", "NIFTY CPSE", "NIFTY ENERGY", "NIFTY EV & NEW AGE AUTOMOTIVE", "NIFTY HOUSING",
            "NIFTY100 ESG", "NIFTY100 ENHANCED ESG", "NIFTY100 ESG SECTOR LEADERS", "NIFTY INDIA CONSUMPTION", "NIFTY INDIA DEFENCE",
            "NIFTY INDIA DEFENCE EQUAL WEIGHT", "NIFTY INDIA DIGITAL", "NIFTY INDIA INFRASTRUCTURE & LOGISTICS", "NIFTY INDIA INTERNET",
            "NIFTY INDIA MANUFACTURING", "NIFTY INDIA NEW AGE CONSUMPTION", "NIFTY INDIA RAILWAYS PSU", "NIFTY INDIA TOURISM",
            "NIFTY INDIA SELECT 5 CORPORATE GROUPS (MAATR)", "NIFTY INFRASTRUCTURE", "NIFTY INDIA CORPORATE GROUP INDEX - MAHINDRA GROUP",
            "NIFTY IPO", "NIFTY MIDCAP LIQUID 15", "NIFTY MIDSMALL INDIA CONSUMPTION", "NIFTY MNC", "NIFTY MOBILITY", "NIFTY PSE",
            "NIFTY REITS & INVITS", "NIFTY REITS & INVITS 90:10", "NIFTY RURAL", "NIFTY NON-CYCLICAL CONSUMER", "NIFTY SERVICES SECTOR",
            "NIFTY SHARIAH 25", "NIFTY SMALL FINANCE BANKS & MICROFINANCE INSTITUTIONS", "NIFTY SUGAR & ETHANOL",
            "NIFTY INDIA CORPORATE GROUP INDEX - TATA GROUP", "NIFTY INDIA CORPORATE GROUP INDEX - TATA GROUP 25% CAP",
            "NIFTY TRANSPORTATION & LOGISTICS", "NIFTY100 LIQUID 15", "NIFTY50 SHARIAH", "NIFTY500 SHARIAH",
            "NIFTY500 MULTICAP INDIA MANUFACTURING 50:30:20", "NIFTY500 MULTICAP INFRASTRUCTURE 50:30:20", "NIFTY500 AHIMSA",
            "NIFTY SME EMERGE", "NIFTY WAVES"]
s = requests.Session()
s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
                  "Referer": "https://www.nseindia.com/"})


def day_file(d):
    for u in ("https://nsearchives.nseindia.com/content/indices/ind_close_all_{d:%d%m%Y}.csv",
              "https://archives.nseindia.com/content/indices/ind_close_all_{d:%d%m%Y}.csv"):
        try:
            r = s.get(u.format(d=d), timeout=25)
            if r.status_code == 200 and b"Index" in r.content[:200]:
                x = pd.read_csv(io.BytesIO(r.content)); x.columns = [c.strip() for c in x.columns]
                col = lambda k: next(c for c in x.columns if k.lower() in c.lower())  # noqa: E731
                return pd.DataFrame({"Date": d.date(), "INDEX": x[col("Index Name")].astype(str).str.strip().str.upper(),
                                     "CLOSE": pd.to_numeric(x[col("Clos")], errors="coerce")})
        except Exception:  # noqa: BLE001
            time.sleep(1)
    return None


def load_hist(today):
    have = pd.read_csv(CACHE, parse_dates=["Date"]) if os.path.exists(CACHE) else pd.DataFrame(columns=["Date", "INDEX", "CLOSE"])
    start = (have.Date.max() + pd.Timedelta(days=1)) if len(have) else pd.Timestamp(today) - pd.Timedelta(days=560)
    new = []
    for d in pd.bdate_range(start, today):
        x = day_file(d)
        if x is not None:
            new.append(x)
        time.sleep(0.2)
    H = pd.concat([have] + new) if new else have
    H["Date"] = pd.to_datetime(H.Date)
    H = H.drop_duplicates(["Date", "INDEX"]).sort_values(["INDEX", "Date"])
    keep = set(INDUSTRY_INDEX.values()) | set(EXTRA) | set(THEMATIC) | {MARKET}
    H = H[H.INDEX.isin(keep)]
    H.to_csv(CACHE, index=False)
    print("index history rows", len(H), "new days", len(new), flush=True)
    return H


SEC_RS_N, STOCK_RS_N, RS_RISE = 126, 250, 20   # backtest: sector RS 3-6 m vs Nifty 50 and stock RS 1 y vs its sector work best


def rs_now(a, b, n):
    """RS = (a_t/a_t-n)/(b_t/b_t-n) - 1 on aligned daily closes; returns (rs_now, rs 20 days ago)."""
    j = pd.concat([a, b], axis=1, join="inner").dropna()
    if len(j) < n + RS_RISE + 1:
        return np.nan, np.nan
    r = (j.iloc[:, 0] / j.iloc[:, 0].shift(n)) / (j.iloc[:, 1] / j.iloc[:, 1].shift(n)) - 1
    return float(r.iloc[-1]), float(r.iloc[-1 - RS_RISE])


def state(c, mret, n50=None):
    c = c.dropna()
    if len(c) < 160:            # < ~8 months of data: too new for the 30-week SMA / 6-month RS
        return None
    wk = c.groupby(c.index.to_period("W-FRI")).last()
    if c.index[-1].weekday() != 4:           # current week not finished: use completed weeks only
        wk = wk.iloc[:-1]
    sma = wk.rolling(30, min_periods=30).mean()
    up = bool(wk.iloc[-1] > sma.iloc[-1] and sma.iloc[-1] > sma.iloc[-5])
    r3 = float(c.iloc[-1] / c.iloc[-64] - 1) if len(c) > 64 else np.nan
    rs = r3 - mret if np.isfinite(r3) and np.isfinite(mret) else np.nan
    beat = bool(rs > 0) if np.isfinite(rs) else False
    tag = "leading" if up and beat else "uptrend" if up else "mixed" if beat else "weak"
    srs, srs0 = rs_now(c, n50, SEC_RS_N) if n50 is not None else (np.nan, np.nan)
    # monthly ATH status on closes (the file has closes only): highest completed-month close and its age
    mc = c.groupby(c.index.to_period("M")).last()
    done = mc.iloc[:-1] if len(mc) > 1 else mc
    best_m = done.idxmax() if len(done) else None
    base_m = int((mc.index[-1] - best_m).n) if best_m is not None else None
    ath_close = float(done.max()) if len(done) else np.nan
    return dict(close=float(c.iloc[-1]), sma30=float(sma.iloc[-1]), up=up, ret_3m=r3 * 100, vs_market_3m=rs * 100,
                from_high=float(c.iloc[-1] / c.max() - 1) * 100, tag=tag, since=str(c.index[0].date()),
                years=round((c.index[-1] - c.index[0]).days / 365.25, 1),
                ath_month=str(best_m) if best_m is not None else None, ath_month_close=ath_close, base_months=base_m,
                above_ath_month=bool(c.iloc[-1] > ath_close) if np.isfinite(ath_close) else None,
                rs_6m=srs * 100 if np.isfinite(srs) else None, rs_6m_up=bool(srs > srs0) if np.isfinite(srs) and np.isfinite(srs0) else None)


def main():
    today = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).date()
    H = load_hist(today)
    P = H.pivot(index="Date", columns="INDEX", values="CLOSE").sort_index()
    m = P[MARKET].dropna() if MARKET in P else pd.Series(dtype=float)
    mret = float(m.iloc[-1] / m.iloc[-64] - 1) if len(m) > 64 else np.nan
    idx = {}
    n50 = P["NIFTY 50"].dropna() if "NIFTY 50" in P else None
    for name in P.columns:
        st = state(P[name], mret, n50)
        if st:
            idx[name] = st
    sym = {}
    for f in glob.glob("data/universe/nifty*.csv") + glob.glob("data/universe/fno_stocks.csv"):
        try:
            u = pd.read_csv(f)
            if {"Symbol", "Industry"} <= set(u.columns):
                sym.update(dict(zip(u.Symbol.astype(str).str.strip(), u.Industry.astype(str).str.strip())))
        except Exception:  # noqa: BLE001
            pass
    themes = {}
    try:
        T = pd.read_csv("data/universe/themes.csv")
        T = T[~T.Theme.isin(THEME_EXCLUDE)]
        themes = T.groupby(T.Symbol.astype(str).str.strip()).Theme.apply(lambda v: sorted(set(v))).to_dict()
    except Exception:  # noqa: BLE001
        pass
    out = dict(asof=str(P.index[-1].date()) if len(P) else str(today), market=MARKET, indices=idx, industries=INDUSTRY_INDEX, symbols=sym,
               themes=themes,
               thematic=[k for k in THEMATIC if k in idx], thematic_new=[k for k in THEMATIC if k not in idx])
    fix = lambda v: {k: fix(x) for k, x in v.items()} if isinstance(v, dict) else (None if isinstance(v, float) and not np.isfinite(v) else v)  # noqa: E731
    json.dump(fix(out), open(OUT, "w"), indent=0, allow_nan=False)
    print("sectors", len(idx), "symbols with industry", len(sym))
    for k in sorted(set(INDUSTRY_INDEX.values())):
        if k in idx:
            print(f"  {k:28s} {idx[k]['tag']:8s} vs market {idx[k]['vs_market_3m']:+.1f}%  RS 6m vs Nifty 50 {idx[k]['rs_6m'] if idx[k]['rs_6m'] is None else round(idx[k]['rs_6m'], 1)}")


def load_bench():
    """Daily closes of the sector indices + Nifty 500 from the cache (for stock RS in the scans)."""
    try:
        H = pd.read_csv(CACHE, parse_dates=["Date"])
        return H.pivot_table(index="Date", columns="INDEX", values="CLOSE", aggfunc="last").sort_index()
    except Exception:  # noqa: BLE001
        return None


def stock_rs(symbol, close, sec, bench):
    """1-year RS of a stock vs its sector index (Nifty 500 if it has none). Young stocks (IPOs) use what history they have
    (>= 63 days). Returns dict(rs_bench, stock_rs, stock_rs_up) or {}."""
    if bench is None or close is None or not len(close):
        return {}
    _, ix, _ = tag_for(symbol, sec) if sec else (None, None, None)
    b = ix if ix and ix in bench else MARKET
    if b not in bench:
        return {}
    c = close.copy(); ci = pd.to_datetime(c.index)
    c.index = (ci.tz_localize(None) if ci.tz is not None else ci).normalize()
    n = min(STOCK_RS_N, len(c.dropna()) - RS_RISE - 1)
    if n < 63:
        return {}
    r, r0 = rs_now(c, bench[b], n)
    if not np.isfinite(r):
        return {}
    return dict(rs_bench=b, stock_rs=r * 100, stock_rs_up=bool(r > r0) if np.isfinite(r0) else None, stock_rs_days=int(n))


# themes that say nothing about the business (ownership group, ethics screen, liquidity, exchange board)
THEME_EXCLUDE = {"NIFTY500 AHIMSA", "NIFTY SME EMERGE", "NIFTY MIDCAP LIQUID 15", "NIFTY100 LIQUID 15", "NIFTY CONGLOMERATE 50",
                 "NIFTY INDIA SELECT 5 CORPORATE GROUPS (MAATR)"}


def topdown(df, sec):
    """Top-down columns for scan rows (needs sector_rs / stock_rs already set):
    theme / theme_rs = member theme with the best 6-month RS vs Nifty 50; td_score = count of sector RS > 0, theme RS > 0,
    stock RS > 0; aligned = sector RS > 0 AND stock RS > 0 (the pair that lifted ATH breakouts in the 2017-26 test)."""
    ix = sec.get("indices") or {}; th = sec.get("themes") or {}
    best = []
    for s_ in df.symbol:
        v = [(t, (ix.get(t) or {}).get("rs_6m")) for t in th.get(s_, []) if t not in THEME_EXCLUDE]
        v = [x for x in v if x[1] is not None]
        best.append(max(v, key=lambda x: x[1]) if v else (None, None))
    df["theme"] = [b[0] for b in best]; df["theme_rs"] = [b[1] for b in best]
    pos = lambda c: pd.to_numeric(df[c], errors="coerce").gt(0) if c in df else pd.Series(False, index=df.index)  # noqa: E731
    df["td_score"] = pos("sector_rs").astype(int) + pos("theme_rs").astype(int) + pos("stock_rs").astype(int)
    df["aligned"] = pos("sector_rs") & pos("stock_rs")
    return df


def tag_for(symbol, sec):
    """Helper for the scans: (industry, index, tag) or (None, None, None)."""
    ind = (sec.get("symbols") or {}).get(symbol)
    if not ind:
        return None, None, None
    ix = (sec.get("industries") or {}).get(ind)
    st = (sec.get("indices") or {}).get(ix) if ix else None
    return ind, ix, (st or {}).get("tag")


if __name__ == "__main__":
    main()
