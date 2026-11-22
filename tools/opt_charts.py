"""ATM option charts + systems on the option premium (17 Nov 2026, Amritpal's request; WATCH ONLY - not backtested).

For every liquid F&O stock and the index options (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY):
  contract  = today's ATM strike (nearest to the near-month future's close) of whichever of the next two monthly expiries
              traded more ATM contracts over the last 5 sessions (at least 3 days left); CE and PE
  chart     = that contract's daily OHLC over its life (NSE F&O bhavcopy, EOD); days without a trade use the settle price
  liquid    = ATM CE + PE traded at least 200 contracts a day on average over the last 5 sessions
  systems on the premium chart (the same rules the app uses on stocks):
    9/21    : EMA 9 crossed above EMA 21 in the last 2 sessions and the close is above EMA 21
    breakout: close above the highest close of the previous 20 sessions
    TB      : close above the last top of the closing line (Top Bottom buy level)
    cup     : cup close - close above the highest high of the window, that high 20+ bars old, cup 15%+ deep (day cup close rule)
Cache: daily filtered bhavcopies in optcache/ (kept by the workflow's actions/cache).
Output: data/scan/optscan.json (list + signals) and data/scan/optcharts.json (bars, loaded on demand)."""
import io
import json
import os
import time
import zipfile
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import requests

CACHE = "optcache"; OUT = "data/scan"
IDX = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]
DAYS = 140                 # calendar days of history (monthly contracts live ~3 months)
MIN_VOL = 200
s = requests.Session()
s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
                  "Referer": "https://www.nseindia.com/"})


def fetch(d):
    p = os.path.join(CACHE, f"{d:%Y%m%d}.csv.gz")
    if os.path.exists(p):
        return pd.read_csv(p, parse_dates=["EXPIRY"]) if os.path.getsize(p) > 30 else None
    b = None
    for _ in range(3):
        try:
            r = s.get(f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000.csv.zip", timeout=40)
            if r.status_code == 200 and r.content[:2] == b"PK":
                z = zipfile.ZipFile(io.BytesIO(r.content)); b = pd.read_csv(z.open(z.namelist()[0])); break
            if r.status_code == 404:
                break
        except Exception:  # noqa: BLE001
            time.sleep(2)
    if b is None:
        if d < date.today():                       # holiday / weekend: remember it
            open(p, "w").close()
        return None
    b = b[b.FinInstrmTp.isin(["STO", "STF", "IDO", "IDF"])]
    x = pd.DataFrame({"SYMBOL": b.TckrSymb.astype(str), "INST": b.FinInstrmTp.map({"STO": "OPT", "IDO": "OPT", "STF": "FUT", "IDF": "FUT"}),
                      "EXPIRY": pd.to_datetime(b.XpryDt), "STRIKE": b.StrkPric, "TYPE": b.OptnTp, "OPEN": b.OpnPric, "HIGH": b.HghPric,
                      "LOW": b.LwPric, "CLOSE": b.ClsPric, "SETTLE": b.SttlmPric, "OI": b.OpnIntrst, "VOL": b.TtlTradgVol,
                      "LOT": b.get("NewBrdLotQty")})
    keep = []
    for u, g in x.groupby("SYMBOL"):
        f = g[g.INST == "FUT"].sort_values("EXPIRY")
        if f.empty:
            continue
        ref = float(f.CLOSE.iloc[0]); o = g[g.INST == "OPT"]
        ex = pd.Series(sorted(o.EXPIRY.unique()))
        if not len(ex):
            continue
        mon = ex.groupby(ex.dt.to_period("M")).max().tolist()[:3]          # monthly expiries only
        keep += [f.head(2), o[o.EXPIRY.isin(mon) & o.STRIKE.between(ref * 0.88, ref * 1.12)]]
    r = pd.concat(keep); r.insert(0, "Date", pd.Timestamp(d)); r.to_csv(p, index=False)
    return r


def ema(v, n):
    k = 2 / (n + 1); e = v[0]; out = []
    for x in v:
        e = x * k + e * (1 - k); out.append(e)
    return out


def last_top(c):
    """latest top of the closing line known at the last bar (1-day turns, as Top Bottom)"""
    top = None
    for i in range(1, len(c) - 1):
        if c[i] > c[i - 1] and c[i] >= c[i + 1]:
            top = (i, c[i])
    return top


def systems(c, h=None):
    sig = []
    n = len(c)
    if h is not None:
        from cupclose import cupclose
        r_ = cupclose(np.asarray(h, float), np.asarray(c, float), 250, 20, -0.15)     # day cup close rule on the premium
        if r_:
            sig.append(f"cup close (rim {round(r_[1], 2)}, {r_[2]} bars, {abs(round(r_[3] * 100, 1))}% deep)")
    if n >= 25:
        e9, e21 = ema(c, 9), ema(c, 21)
        if any(e9[i] > e21[i] and e9[i - 1] <= e21[i - 1] for i in (n - 1, n - 2)) and c[-1] > e21[-1]:
            sig.append("9/21 cross up")
        if c[-1] > max(c[-21:-1]):
            sig.append("20-day high close")
    if n >= 16:                                                       # 18 Nov 2026: RSI(14) crossing above 60
        d_ = np.diff(np.asarray(c, float)); g, l_ = np.maximum(d_, 0), np.maximum(-d_, 0); ag, al = g[:14].mean(), l_[:14].mean(); rs = []
        for i in range(14, len(d_)):
            ag = (ag * 13 + g[i]) / 14; al = (al * 13 + l_[i]) / 14; rs.append(100.0 if al == 0 else 100 - 100 / (1 + ag / al))
        if len(rs) >= 2 and rs[-1] > 60 >= rs[-2]:
            sig.append("RSI 60 cross")
    lt = last_top(c[:-1]) if n >= 5 else None
    if lt and c[-1] > lt[1] and c[-2] <= lt[1]:
        sig.append("Top Bottom buy (close above last top)")
    return sig, (round(lt[1], 2) if lt else None)


def main():
    os.makedirs(CACHE, exist_ok=True)
    today = datetime.now(timezone.utc).date()
    D = []
    for k in range(DAYS, -1, -1):
        d = today - timedelta(days=k)
        if d.weekday() < 5:
            x = fetch(d)
            if x is not None and len(x):
                D.append(x)
    X = pd.concat(D); X["Date"] = pd.to_datetime(X.Date)
    last = X.Date.max(); print("days", X.Date.nunique(), "last", last.date(), flush=True)
    for f in os.listdir(CACHE):                                        # drop cache older than the window
        if f < f"{today - timedelta(days=DAYS + 10):%Y%m%d}":
            os.remove(os.path.join(CACHE, f))
    try:
        fno = set(pd.read_csv("data/universe/fno_stocks.csv").Symbol)
    except Exception:  # noqa: BLE001
        fno = None
    T = X[X.Date == last]; rows, charts = [], {}
    for sym, g in T.groupby("SYMBOL"):
        if sym not in IDX and fno is not None and sym not in fno:
            continue
        f = g[g.INST == "FUT"].sort_values("EXPIRY")
        if f.empty:
            continue
        F = float(f.CLOSE.iloc[0]); lot = f.LOT.iloc[0]
        o = g[g.INST == "OPT"]
        exps = [e for e in sorted(o.EXPIRY.unique()) if (pd.Timestamp(e) - last).days >= 3][:2]
        last5 = sorted(X.Date.unique())[-5:]; best = None
        for e in exps:                                  # the more traded of the next two monthlies (what traders actually use)
            oe = o[o.EXPIRY == e]
            if oe.empty:
                continue
            k = float(min(oe.STRIKE.unique(), key=lambda v: abs(v - F)))
            H = X[(X.SYMBOL == sym) & (X.INST == "OPT") & (X.EXPIRY == e) & (X.STRIKE == k)]
            v5 = H[H.Date.isin(last5)].groupby("Date").VOL.sum().reindex(last5).fillna(0).mean()
            if best is None or v5 > best[0]:
                best = (v5, e, k, H)
        if best is None:
            continue
        v5, e, k, H = best
        if v5 < MIN_VOL:
            continue
        Fs = X[(X.SYMBOL == sym) & (X.INST == "FUT")].sort_values(["Date", "EXPIRY"]).groupby("Date").CLOSE.first()
        row = dict(symbol=sym, kind="index" if sym in IDX else "stock", fut=round(F, 2), expiry=str(pd.Timestamp(e).date()), strike=k,
                   lot=None if pd.isna(lot) else int(lot), dte=(pd.Timestamp(e) - last).days, atm_vol5=int(v5))
        ch = dict(t=[str(d.date()) for d in Fs.index], f=[round(float(v), 2) for v in Fs.values])
        for typ in ("CE", "PE"):
            S = H[H.TYPE == typ].sort_values("Date")
            if len(S) < 3:
                continue
            traded = S.VOL > 0
            c = np.where(traded, S.CLOSE, S.SETTLE).astype(float)
            o_ = np.where(traded, S.OPEN, c); h_ = np.where(traded, S.HIGH, c); l_ = np.where(traded, S.LOW, c)
            sig, top = systems(list(c), list(h_))
            row[typ.lower()] = dict(close=round(c[-1], 2), chg=round((c[-1] / c[-2] - 1) * 100, 1) if c[-2] else None, signals=sig, top=top,
                                    bars=len(c), value_lot=round(c[-1] * (row["lot"] or 0)), oi=int(S.OI.iloc[-1]), vol=int(S.VOL.iloc[-1]))
            ch[typ.lower()] = dict(t=[str(d.date()) for d in S.Date], o=[round(float(v), 2) for v in o_], h=[round(float(v), 2) for v in h_],
                                   l=[round(float(v), 2) for v in l_], c=[round(float(v), 2) for v in c], v=[int(v) for v in S.VOL])
        if "ce" in row or "pe" in row:
            rows.append(row); charts[sym] = ch
    rows.sort(key=lambda r: (r["kind"] != "index", -r["atm_vol5"]))
    json.dump(dict(asof=str(last.date()), generated=datetime.now(timezone.utc).isoformat(timespec="minutes"), rules=__doc__, rows=rows),
              open(f"{OUT}/optscan.json", "w"), separators=(",", ":"))
    json.dump(charts, open(f"{OUT}/optcharts.json", "w"), separators=(",", ":"))
    print("rows", len(rows), "with signals", sum(1 for r in rows for t in ("ce", "pe") if r.get(t, {}).get("signals")), flush=True)
    pcr_file(X, last)
    try:
        oi_build_file(X)
    except Exception as e:  # noqa: BLE001
        print("oi build failed", e)


def oi_build_file(X):
    """22 Nov 2026 (Amritpal: "add speculation"): futures positioning per F&O stock / index - the classic OI reading. Futures OI summed
    over the near two expiries; price = near-future close. Over the last 5 sessions (and today): OI up + price up = long build-up,
    OI up + price down = short build-up, OI down + price up = short covering, OI down + price down = long unwinding; |OI change| < 3%
    = no clear change. Earlier tests (quiet-turnover, sector OI, money-flow) found these readings add little on their own - context only."""
    F = X[X.INST == "FUT"]
    oi = F.groupby(["SYMBOL", "Date"]).OI.sum().unstack("SYMBOL").sort_index()
    px = F.sort_values("EXPIRY").groupby(["SYMBOL", "Date"]).CLOSE.first().unstack("SYMBOL").sort_index()
    if len(oi) < 6:
        return
    def lab(dp, do):
        if abs(do) < 3:
            return None
        return ("long build-up" if dp > 0 else "short build-up") if do > 0 else ("short covering" if dp > 0 else "long unwinding")
    out = {}
    for sym in oi.columns:
        o, p = oi[sym].dropna(), px[sym].dropna()
        if len(o) < 6 or len(p) < 6 or o.iloc[-6] <= 0 or o.iloc[-2] <= 0:
            continue
        do5, dp5 = (o.iloc[-1] / o.iloc[-6] - 1) * 100, (p.iloc[-1] / p.iloc[-6] - 1) * 100
        do1, dp1 = (o.iloc[-1] / o.iloc[-2] - 1) * 100, (p.iloc[-1] / p.iloc[-2] - 1) * 100
        out[sym] = dict(s5=lab(dp5, do5), oi5=round(float(do5), 1), px5=round(float(dp5), 1), s1=lab(dp1, do1), oi1=round(float(do1), 1), px1=round(float(dp1), 1))
    json.dump(dict(asof=str(oi.index[-1].date()), rule=oi_build_file.__doc__, rows=out), open(f"{OUT}/oi_build.json", "w"), separators=(",", ":"))
    print("oi build", len(out), pd.Series([v["s5"] for v in out.values()]).value_counts().to_dict(), flush=True)


def pcr_file(X, last):
    """18 Nov 2026: put/call OI ratio per F&O stock / index as a GUIDE on every trade (tested 2020-26: the top fifth of PCR beat the
    bottom fifth in every year, +1.5% vs +0.4% over 10 days; not a system, no filter). Near monthly expiry with >= 3 days left,
    strikes within +-10% of the near future. q = today's quintile among all F&O names (5 = highest PCR); d5 = change over 5 sessions."""
    O = X[X.INST == "OPT"]; Fu = X[X.INST == "FUT"].sort_values("EXPIRY").groupby(["SYMBOL", "Date"]).CLOSE.first().rename("F")
    O = O.join(Fu, on=["SYMBOL", "Date"])
    O = O[(O.EXPIRY - O.Date).dt.days >= 3]
    ne = O.groupby(["SYMBOL", "Date"]).EXPIRY.transform("min"); O = O[(O.EXPIRY == ne) & (O.STRIKE.between(O.F * 0.90, O.F * 1.10))]
    T = O.pivot_table(index=["SYMBOL", "Date"], columns="TYPE", values="OI", aggfunc="sum")
    T = T[(T.get("CE", 0) > 0)]; T["PCR"] = T["PE"] / T["CE"]
    P = T.PCR.unstack("SYMBOL").sort_index()
    days = list(P.index)
    if not days:
        return
    now = P.iloc[-1].dropna(); prev = P.iloc[-6] if len(P) >= 6 else None
    q = pd.qcut(now.rank(method="first"), 5, labels=False) + 1
    out = {}
    for sym, v in now.items():
        d5 = None if prev is None or pd.isna(prev.get(sym)) else round(float(v - prev[sym]), 3)
        out[sym] = dict(pcr=round(float(v), 3), q=int(q[sym]), d5=d5)
    json.dump(dict(asof=str(pd.Timestamp(days[-1]).date()), rule="Put/call OI ratio, near monthly, strikes +-10%. q 5 = highest fifth of F&O names "
                   "today (tested: highest fifth beat the lowest by about 1% over 10 days, every year 2020-26). Guide only.", rows=out),
              open(f"{OUT}/pcr.json", "w"), separators=(",", ":"))
    print("pcr rows", len(out), flush=True)
    # 18 Nov 2026: daily quintiles for the last 30 sessions (backtests use the PREVIOUS session's quintile, known before the open)
    H = {}
    for d in days[-30:]:
        row = P.loc[d].dropna()
        if len(row) < 25:
            continue
        qq = pd.qcut(row.rank(method="first"), 5, labels=False) + 1
        H[str(pd.Timestamp(d).date())] = {k: int(v) for k, v in qq.items()}
    json.dump(H, open(f"{OUT}/pcr_hist.json", "w"), separators=(",", ":"))


if __name__ == "__main__":
    main()
