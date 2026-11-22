"""FII cash flows - daily (market) and fortnightly by sector (22 Nov 2026, Amritpal: "have you considered FII investment into
indices, stocks, all assets yet?" -> "yes do it").

Data (NSDL FPI monitor, public):
  daily  Archive.aspx, one request per month -> 'Equity / Stock Exchange' net investment (Rs cr) per reporting date. The reporting
         date covers trades up to the previous session, so a value is used from the NEXT session on (no look-ahead).
  sector StaticReports/Fortnightly_Sector_wise_FII_Investment_Data/*.html -> equity net investment in the fortnight and equity
         AUC per sector. Old (to ~2023) GICS-like names are mapped to NSE's macro sectors. Used from 7 calendar days after the
         fortnight end (publication lag).
Prices: Nifty 50 (Yahoo); NSE macro-sector indices = turnover-weighted (60-day median value) daily returns of the liquid NSE
stocks in each macro sector (group_pulse NSE map, today's members -> survivors), 2015-26.
Tests
  A  Nifty next 5 / 20 / 60 sessions by FII flow state: 5- and 20-day net sums ranked against the past 250 sessions (no
     look-ahead); heavy selling = bottom 20%, heavy buying = top 20%. Newest first.
  B  9/21 live book (10 positions, 1% risk, 3-month ranking) skipping new buys while the 20-day FII flow is in its bottom 20%;
     and while the 5-day flow is negative. (engine: tools/research/morning_check.run, gate = market-wide flow state)
  C  Sectors: rank by fortnight equity net investment / equity AUC; next 2 / 4 / 8 weeks of the sector index vs the average
     sector; top-3 minus bottom-3; portfolio holding the top 3 FII-bought sectors (fortnightly) vs all sectors equal weight.
PILOT env = 2023-26 only, 150 stocks. Output data/research/fii_test(_pilot).json + fii_daily.csv / fii_sector.csv"""
import io
import json
import os
import re
import sys
import time
from datetime import date, timedelta

import numpy as np
import pandas as pd
import requests
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..")); sys.path.insert(0, HERE)

PILOT = bool(os.environ.get("PILOT"))
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
BASE = "https://www.fpi.nsdl.co.in/web/"
S = requests.Session(); S.headers.update({"User-Agent": UA})
START = date(2023, 1, 1) if PILOT else date(2015, 1, 1)


def get(u, **kw):
    for k in range(4):
        try:
            r = S.post(u, timeout=60, **kw) if "data" in kw else S.get(u, timeout=60, **kw)
            if r.status_code == 200:
                return r
        except Exception as e:  # noqa: BLE001
            print("retry", u[-60:], e)
        time.sleep(3 * (k + 1))
    return None


def daily():
    u = BASE + "Reports/Archive.aspx"; rows = {}
    m = date(START.year, START.month, 1); today = date.today()
    while m <= today:
        nxt = date(m.year + (m.month == 12), m.month % 12 + 1, 1); last = min(nxt - timedelta(days=1), today)
        r = get(u)
        if r is None:
            m = nxt; continue
        f = {k: v for k, v in re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', r.text)}
        dv = last.strftime("%d-%b-%Y")
        data = {k: f.get(k, "") for k in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION")}
        data.update(__EVENTTARGET="btnSubmit1", __EVENTARGUMENT="", txtDate=dv, hdnDate=dv)
        p = get(u, data=data)
        got = 0
        if p is not None:
            try:
                T = [t for t in pd.read_html(io.StringIO(p.text)) if t.shape[1] >= 6 and t.shape[0] > 5]
                t = max(T, key=len); t = t.ffill()
                for i in range(len(t)):
                    a = [str(v) for v in t.iloc[i].tolist()]
                    if len(a) >= 6 and a[1].strip().lower() == "equity" and "stock exchange" in a[2].lower():
                        try:
                            n = a[5].replace(",", "").strip(); v = float(n.strip("()")) * (-1 if n.startswith("(") or n.startswith("-") and False else 1)
                            if n.startswith("-"):
                                v = float(n)
                            rows[pd.Timestamp(a[0])] = v; got += 1
                        except Exception:  # noqa: BLE001
                            pass
            except Exception as e:  # noqa: BLE001
                print("R| daily table parse", m, e)
        if p is not None and not got:
            tx = re.sub(r"<[^>]+>", " ", p.text); tx = re.sub(r"\s+", " ", tx).replace("&nbsp;", " ")
            # each reporting date block starts with the date, then 'Equity Stock Exchange purchases sales net'
            for d_, b, s_, n in re.findall(r"(\d{2}-[A-Za-z]{3}-\d{4}) Equity Stock Exchange ([\d,.]+) ([\d,.]+) (\(?[\d,.]+\)?)", tx):
                v = float(n.strip("()").replace(",", "")) * (-1 if n.startswith("(") else 1)
                rows[pd.Timestamp(d_)] = v
        print("R| daily", m, len(rows), flush=True)
        m = nxt; time.sleep(1)
    return pd.Series(rows).sort_index()


OLD = {"automobiles&autocomponents": "Automobile and Auto Components", "totalfinancialservices": "Financial Services",
       "financialservices": "Financial Services", "capitalgoods": "Capital Goods", "chemicals&petrochemicals": "Chemicals",
       "chemicals": "Chemicals", "coal": "Oil Gas & Consumable Fuels", "commercialservices&supplies": "Services",
       "constructionmaterials": "Construction Materials", "construction": "Construction", "consumerdurables": "Consumer Durables",
       "diversified": "Diversified", "diversifiedconsumerservices": "Consumer Services", "food,beverages&tobacco": "Fast Moving Consumer Goods",
       "householdandpersonalproducts": "Fast Moving Consumer Goods", "household&personalproducts": "Fast Moving Consumer Goods",
       "fastmovingconsumergoods": "Fast Moving Consumer Goods", "forestmaterials": "Forest Materials", "generalindustrials": "Capital Goods",
       "hardwaretechnology&equipment": "Information Technology", "healthcareequipment&supplies": "Healthcare", "healthcareservices": "Healthcare",
       "pharmaceuticals&biotechnology": "Healthcare", "healthcare": "Healthcare", "hotels,restaurants&tourism": "Consumer Services",
       "consumerservices": "Consumer Services", "media": "Media Entertainment & Publication", "media,entertainment&publication": "Media Entertainment & Publication",
       "metals&mining": "Metals & Mining", "oil&gas": "Oil Gas & Consumable Fuels", "oil,gas&consumablefuels": "Oil Gas & Consumable Fuels",
       "realty": "Realty", "retailing": "Consumer Services", "software&services": "Information Technology", "informationtechnology": "Information Technology",
       "telecomservices": "Telecommunication", "telecommunicationsequipment": "Telecommunication", "telecommunication": "Telecommunication",
       "textiles,apparels&accessories": "Textiles", "textiles": "Textiles", "transportation": "Services", "services": "Services",
       "utilities": "Power", "power": "Power", "automobileandautocomponents": "Automobile and Auto Components"}
SKIP = {"banks", "otherfinancialservices", "airlines", "logistics", "marineport&services", "roads&highways", "shipping", "surfacetransportation",
        "transportrelatedservices", "sovereign", "others", "grandtotal", "sectors", "nan"}


def norm(x):
    return re.sub(r"\d+$", "", re.sub(r"\s+", "", str(x).lower()))


def sectors():
    r = get(BASE + "Reports/FPI_Fortnightly_Selection.aspx")
    files = re.findall(r'<option[^>]*value="~/StaticReports/Fortnightly_Sector_wise_FII_Investment_Data/([^"]+)"', r.text) if r else []
    out = []
    for fn in files:
        m = re.search(r"FIIInvestSector_([A-Za-z]+)(\d{1,2})(\d{4})", fn)
        if not m:
            continue
        mon = m.group(1)[:3]
        try:
            dend = pd.Timestamp(f"{m.group(2)} {mon} {m.group(3)}")
        except Exception:  # noqa: BLE001
            continue
        if dend.date() < START:
            continue
        h = get(BASE + "StaticReports/Fortnightly_Sector_wise_FII_Investment_Data/" + fn)
        if h is None:
            continue
        try:
            T = pd.read_html(io.StringIO(h.text)); big = max(T, key=lambda x: x.shape[0] * x.shape[1])
        except Exception as e:  # noqa: BLE001
            print("R| parse fail", fn, e); continue
        hdr = [" ".join(str(big.iat[i, j]) for i in range(min(4, len(big)))) for j in range(big.shape[1])]
        eq = lambda j, key: key in hdr[j] and "INR" in hdr[j] and "Equity" in hdr[j] and "Mutual" not in hdr[j]  # noqa: E731
        net_cols = [j for j in range(big.shape[1]) if eq(j, "Net Investment")]
        auc_cols = [j for j in range(big.shape[1]) if eq(j, "AUC")]
        if not net_cols or not auc_cols:
            print("R| columns not found", fn); continue
        nc, ac0 = net_cols[-1], auc_cols[0]
        agg = {}
        for i in range(len(big)):
            nm = norm(big.iat[i, 1])
            if nm in SKIP or nm not in OLD:
                continue
            try:
                nv = float(str(big.iat[i, nc]).replace(",", "")); av = float(str(big.iat[i, ac0]).replace(",", ""))
            except Exception:  # noqa: BLE001
                continue
            s_ = OLD[nm]; a = agg.setdefault(s_, [0.0, 0.0]); a[0] += nv; a[1] += av
        for s_, (nv, av) in agg.items():
            out.append(dict(end=dend, sector=s_, net=nv, auc=av))
        print("R| sector", fn, len(agg), flush=True); time.sleep(0.5)
    return pd.DataFrame(out)


def report_w(eq, bull=None):
    eq = eq.dropna(); end = eq.index[-1]; yrs = (end - eq.index[0]).days / 365.25; o = {}
    o["CAGR"] = round((float(eq.iloc[-1] / eq.iloc[0]) ** (1 / max(yrs, 0.1)) - 1) * 100, 1)
    o["max DD"] = round(float((eq / eq.cummax() - 1).min()) * 100, 1)
    for y in (1, 2, 3, 5):
        e = eq[eq.index >= end - pd.DateOffset(years=y)]
        if len(e) > 3:
            o[f"{y}y"] = round((float(e.iloc[-1] / e.iloc[0]) ** (1 / y) - 1) * 100, 1)
    yr = eq.resample("YE").last(); yr = pd.concat([eq.iloc[:1], yr]).pct_change().dropna()
    o["years"] = {str(k.year): round(v * 100, 1) for k, v in sorted(yr.items(), reverse=True)}
    return o


def main():
    res = dict(method=__doc__)
    F = daily(); os.makedirs("data/research", exist_ok=True); F.to_csv("data/research/fii_daily" + ("_pilot" if PILOT else "") + ".csv")
    print("R| daily rows", len(F), F.index.min(), F.index.max(), "last", F.tail(3).to_dict(), flush=True)
    nif = yf.download("^NSEI", start=str(START - timedelta(days=400)), auto_adjust=True, progress=False)["Close"].squeeze().dropna()
    nif.index = pd.to_datetime(nif.index).tz_localize(None)
    # A: flow state known at the next session
    f = F.reindex(nif.index).fillna(0.0).shift(1)
    f5, f20 = f.rolling(5).sum(), f.rolling(20).sum()
    pr = lambda x: x.rolling(250, min_periods=120).apply(lambda w: (w[:-1] < w[-1]).mean(), raw=True)  # noqa: E731
    p5, p20 = pr(f5), pr(f20)
    fw = {h: nif.shift(-h) / nif - 1 for h in (5, 20, 60)}
    A = {}
    for nm, P in (("5-day flow", p5), ("20-day flow", p20)):
        for lab, msk in (("heavy selling (bottom 20%)", P < 0.2), ("middle", (P >= 0.2) & (P <= 0.8)), ("heavy buying (top 20%)", P > 0.8), ("all days", P.notna())):
            o = {}
            for h, R in fw.items():
                v = R[msk & R.notna()]
                o[f"{h}d"] = dict(n=int(len(v)), avg=round(float(v.mean()) * 100, 2) if len(v) else None, up=round(float((v > 0).mean()) * 100) if len(v) else None)
                for y in (1, 2, 3, 5):
                    vv = v[v.index >= v.index.max() - pd.DateOffset(years=y)] if len(v) else v
                    o[f"{h}d"][f"last {y}y"] = round(float(vv.mean()) * 100, 2) if len(vv) else None
            A[f"{nm} | {lab}"] = o
            print(f"R| A {nm} | {lab} | {o}", flush=True)
    res["A_nifty"] = A
    # C: sectors
    SEC = sectors(); SEC.to_csv("data/research/fii_sector" + ("_pilot" if PILOT else "") + ".csv", index=False)
    print("R| sector rows", len(SEC), SEC.end.min() if len(SEC) else None, SEC.end.max() if len(SEC) else None, sorted(SEC.sector.unique()) if len(SEC) else None, flush=True)
    G = json.load(open("data/scan/group_pulse.json"))["nse"]["rows"]
    s2m = {}
    for r in G:
        for m in r["members"]:
            if m.get("liquid"):
                s2m[m["symbol"]] = r.get("sector") or r.get("macro")   # NSE sector names = NSDL sector names
    syms = sorted(s2m)
    if PILOT:
        syms = syms[:400]
    C, V = {}, {}
    for a in range(0, len(syms), 100):
        ch = [s + ".NS" for s in syms[a:a + 100]]
        try:
            d = yf.download(ch, start=str(START - timedelta(days=200)), interval="1d", progress=False, group_by="column", auto_adjust=True, threads=True)
            for t in ch:
                if t in d["Close"].columns and d["Close"][t].notna().sum() > 100:
                    C[t[:-3]] = d["Close"][t]; V[t[:-3]] = d["Volume"][t]
        except Exception as e:  # noqa: BLE001
            print("dl", e)
        time.sleep(2)
    C = pd.DataFrame(C).sort_index(); C.index = pd.to_datetime(C.index).tz_localize(None); V = pd.DataFrame(V).reindex(C.index)
    ret = C.pct_change(fill_method=None).clip(-0.3, 0.3); w = (C * V).rolling(60, min_periods=20).median().shift(1)
    SI = {}
    for sec in sorted(set(s2m.values())):
        m = [s for s in C.columns if s2m.get(s) == sec]
        if len(m) >= 3:
            ww = w[m].where(ret[m].notna()); SI[sec] = (1 + (ret[m] * ww).sum(axis=1) / ww.sum(axis=1).replace(0, np.nan)).fillna(1).cumprod()
    SI = pd.DataFrame(SI)
    print("R| sector indices", list(SI.columns), flush=True)
    res["C_sectors"] = {}
    if len(SEC):
        SEC["intensity"] = SEC.net / SEC.auc.replace(0, np.nan) * 100
        piv = SEC.pivot_table(index="end", columns="sector", values="intensity").sort_index()
        piv = piv[[c for c in piv.columns if c in SI.columns]]
        dec = [SI.index[SI.index.searchsorted(e + pd.Timedelta(days=7))] if SI.index.searchsorted(e + pd.Timedelta(days=7)) < len(SI) else None for e in piv.index]
        out = {k: [] for k in ("top3", "bottom3", "spread", "ic")}; fwd = {}
        for hw in (2, 4, 8):
            tops, bots, sp, ics = [], [], [], []
            for e, d0 in zip(piv.index, dec):
                if d0 is None:
                    continue
                i0 = SI.index.get_loc(d0); i1 = i0 + hw * 5
                if i1 >= len(SI):
                    continue
                r = SI.iloc[i1] / SI.iloc[i0] - 1; x = piv.loc[e].dropna(); r = r[x.index].dropna(); x = x[r.index]
                if len(x) < 8:
                    continue
                ex = r - r.mean(); o = x.sort_values()
                tops.append((d0, float(ex[o.index[-3:]].mean()))); bots.append((d0, float(ex[o.index[:3]].mean())))
                ics.append((d0, float(pd.Series(x).rank().corr(pd.Series(r).rank()))))
            T = pd.Series(dict(tops)); Bt = pd.Series(dict(bots)); I = pd.Series(dict(ics))
            def win(s_, y):
                return round(float(s_[s_.index >= s_.index.max() - pd.DateOffset(years=y)].mean()) * 100, 2) if len(s_) else None
            fwd[f"{hw}w"] = dict(n=int(len(T)), top3=round(float(T.mean()) * 100, 2) if len(T) else None, bottom3=round(float(Bt.mean()) * 100, 2) if len(Bt) else None,
                                 spread=round(float((T - Bt).mean()) * 100, 2) if len(T) else None, rank_corr=round(float(I.mean()), 3) if len(I) else None,
                                 top3_beat=round(float((T > 0).mean()) * 100) if len(T) else None,
                                 **{f"spread last {y}y": win(T - Bt, y) for y in (1, 2, 3, 5)})
            print(f"R| C sectors {hw}w | {fwd[f'{hw}w']}", flush=True)
        res["C_sectors"]["forward"] = fwd
        # portfolio: hold the top 3 FII-bought sectors from each decision date to the next
        eqs = {"top 3 FII-bought sectors": [], "bottom 3": [], "all sectors equal": []}
        val = {k: 1.0 for k in eqs}; dates = [d for d in dec if d is not None]
        for k_, (e, d0) in enumerate([(e, d) for e, d in zip(piv.index, dec) if d is not None]):
            d1 = dates[k_ + 1] if k_ + 1 < len(dates) else SI.index[-1]
            if d1 <= d0:
                continue
            r = SI.loc[d1] / SI.loc[d0] - 1; x = piv.loc[e].dropna(); r = r[x.index].dropna(); x = x[r.index]
            if len(x) < 8:
                continue
            o = x.sort_values()
            for nm_, sel in (("top 3 FII-bought sectors", o.index[-3:]), ("bottom 3", o.index[:3]), ("all sectors equal", o.index)):
                val[nm_] *= (1 + float(r[sel].mean())) * (1 - 0.002); eqs[nm_].append((d1, val[nm_]))
        res["C_sectors"]["portfolio"] = {k: report_w(pd.Series(dict(v))) for k, v in eqs.items() if len(v) > 5}
        for k, v in res["C_sectors"]["portfolio"].items():
            print(f"R| C portfolio {k} | {v}", flush=True)
        last = piv.iloc[-1].dropna().sort_values()
        res["C_sectors"]["latest"] = dict(fortnight=str(piv.index[-1].date()), top=[(k, round(v, 2)) for k, v in last[-5:][::-1].items()],
                                          bottom=[(k, round(v, 2)) for k, v in last[:5].items()])
        print("R| latest", res["C_sectors"]["latest"], flush=True)
    # B: 9/21 gate on the market-wide FII flow state
    try:
        from trend_bt_global import load
        import morning_check as MC
        import ath_red_skip as AR
        d, _ = load("NSE")
        if PILOT:
            keep = sorted(d.SYMBOL.unique())[:150]; d = d[d.SYMBOL.isin(keep)]
        d = d.sort_values(["SYMBOL", "Date"]).reset_index(drop=True)
        d["r63"] = d.groupby("SYMBOL").CLOSE.transform(lambda s: s / s.shift(63) - 1)
        P20 = p20.reindex(d.Date.values).values; F5 = f5.reindex(d.Date.values).values
        d["g_not_sell"] = ~(P20 < 0.2); d["g_f5pos"] = ~(F5 < 0)
        bull = nif > nif.rolling(200).mean(); B = {}
        for nm, gate in (("baseline (live)", None), ("skip while 20-day FII flow in bottom 20%", "g_not_sell"), ("skip while 5-day FII flow negative", "g_f5pos")):
            eq, T = MC.run(d, 10, 0.01, "r63", gate=gate, start=str(max(START, date(2016, 6, 1))))
            rp = AR.report(eq, bull); rp["trades"] = len(T); rp["avg trade"] = round(float(T.ret.mean() * 100), 2) if len(T) else None
            B[nm] = rp; print(f"R| B 9/21 | {nm} | {rp}", flush=True)
        res["B_921"] = B
    except Exception as e:  # noqa: BLE001
        print("R| B failed", e, flush=True)
    json.dump(res, open("data/research/fii_test" + ("_pilot" if PILOT else "") + ".json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
