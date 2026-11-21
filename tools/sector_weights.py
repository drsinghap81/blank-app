"""Sector weights for the rotation charts (21 Nov 2026, Amritpal: "it becomes important to weight it ... show bigger dots for high
weightage"). A sector that is a third of the index (US Technology) matters far more than one that is 2% (Utilities): when the big
one lags, the index falls and most other sectors look "Leading" only because they fall less.

Weight = the sector's share of the market's large-cap market value, from Yahoo market caps (data/scan/<mk>/fundamentals.json):
  NSE : Nifty 500 stocks (data/universe/nifty500.csv). The NSE sector indices on the chart overlap (Bank Nifty contains Pvt Bank and
        PSU Bank; Midcap 150 is a size slice), so each dot gets the market value of its own members, and a non-overlapping set of
        dots ("part": true - Fin Services, IT, Healthcare, FMCG, Auto, Metal, Oil & Gas, Realty, Media, Cons Durables, Infra, ...)
        is used for the weight-share line. Members: NSE basic industries (group_pulse 'nse'), nifty500 industry, theme lists.
  US  : S&P 500 sector weights as published for SPY (Yahoo / Morningstar fund data); the stock lists' own sector labels are not
        GICS (Google, Meta tagged Technology), which made Technology 43% instead of about a third
  ASX : S&P/ASX 200 sector weights for STW.AX (fallback: the 200 largest scanned stocks by asx_meta sector index)
  WSECT (world GICS sectors vs ACWI): ACWI's sector weights
  UK  : the 100 largest scanned UK stocks by the app's UK sector (Yahoo market caps fetched here)
Approximate (only stocks we scan, Yahoo caps, today's members); good for dot size and "how much of the market is leading", not
a precise index weight. Output: data/scan/sector_weights.json {mk: {name: {w: %, part: bool}}}"""
import json
import os
import re
from datetime import date

import pandas as pd

U = "data/universe/"


def caps(path):
    try:
        S = json.load(open(path))["s"]
    except Exception:  # noqa: BLE001
        return {}
    return {k: float(v["mc"]) for k, v in S.items() if v.get("mc")}


def pct(groups, total=None):
    tot = total or sum(groups.values()) or 1
    return {k: round(100 * v / tot, 2) for k, v in groups.items()}


def nse():
    mc = caps("data/scan/fundamentals.json")
    n5 = pd.read_csv(U + "nifty500.csv"); n5 = n5[n5.Symbol.isin(mc)]
    univ = set(n5.Symbol); tot = sum(mc[s] for s in univ)
    G = json.load(open("data/scan/group_pulse.json"))
    basic = {m["symbol"]: r["basic"] for r in G["nse"]["rows"] for m in r["members"]}
    ind = dict(zip(n5.Symbol, n5.Industry))
    theme = lambda f: set(pd.read_csv(U + "themes/" + f).Symbol) if os.path.exists(U + "themes/" + f) else set()  # noqa: E731
    size = lambda f: set(pd.read_csv(U + f).Symbol) if os.path.exists(U + f) else set()  # noqa: E731
    by_ind = lambda *xs: {s for s in univ if ind.get(s) in xs}  # noqa: E731
    by_basic = lambda pat: {s for s in univ if re.search(pat, basic.get(s, ""), re.I)}  # noqa: E731
    M = {  # dot -> members (approximate index membership within the Nifty 500)
        "Bank Nifty": by_basic(r"^(Private|Public) Sector Bank$"), "Pvt Bank": by_basic(r"^Private Sector Bank$"),
        "PSU Bank": by_basic(r"^Public Sector Bank$"), "Fin Services": by_ind("Financial Services"), "Capital Mkts": theme("capitalmarkets.csv"),
        "IT": by_ind("Information Technology"), "Pharma": by_basic(r"^Pharmaceuticals$"), "Healthcare": by_ind("Healthcare"),
        "FMCG": by_ind("Fast Moving Consumer Goods"), "Auto": by_ind("Automobile and Auto Components"), "Metal": by_ind("Metals & Mining"),
        "Energy": theme("energy.csv") or by_ind("Oil Gas & Consumable Fuels", "Power"), "Oil & Gas": by_ind("Oil Gas & Consumable Fuels"),
        "Realty": by_ind("Realty"), "Media": by_ind("Media Entertainment & Publication"),
        "Infra": theme("infrastructure.csv") or by_ind("Construction", "Power", "Telecommunication", "Capital Goods"),
        "Commodities": theme("commodities.csv"), "Cons Durables": by_ind("Consumer Durables"), "Consumption": theme("indiaconsumption.csv"),
        "Defence": theme("indiadefence.csv"), "CPSE": theme("cpse.csv"), "PSE": theme("pse.csv"), "MNC": theme("mnc.csv"),
        "Services": theme("servicessector.csv"), "Midcap 150": size("niftymidcap150.csv"), "Smallcap 250": size("niftysmallcap250.csv")}
    PART = {"Fin Services", "IT", "Healthcare", "FMCG", "Auto", "Metal", "Oil & Gas", "Realty", "Media", "Cons Durables"}
    out = {k: dict(w=round(100 * sum(mc[s] for s in (v & univ)) / tot, 2), n=len(v & univ), part=k in PART) for k, v in M.items()}
    print("NSE: Nifty 500 caps", len(univ), "| partition covers", round(sum(o["w"] for o in out.values() if o["part"]), 1), "%")
    return out


def by_meta(meta, fund, top, names):
    mc = caps(fund)
    m = pd.read_csv(meta); m = m[m.symbol.isin(mc)].copy(); m["mc"] = m.symbol.map(mc)
    m = m.sort_values("mc", ascending=False).head(top); tot = m.mc.sum()
    g = m.groupby("sector_index").mc.sum()
    return {names[k]: dict(w=round(float(100 * v / tot), 2), n=int((m.sector_index == k).sum()), part=True) for k, v in g.items() if k in names}


MS = {"technology": "Technology", "financial_services": "Financials", "healthcare": "Health Care", "energy": "Energy",
      "industrials": "Industrials", "consumer_cyclical": "Cons Discretionary", "consumer_defensive": "Cons Staples", "utilities": "Utilities",
      "basic_materials": "Materials", "realestate": "Real Estate", "communication_services": "Communication"}


def fund_sectors(tick, rename=None):
    """sector weights of an index ETF (Yahoo / Morningstar) -> {our name: %}"""
    import yfinance as yf
    w = yf.Ticker(tick).funds_data.sector_weightings or {}
    tot = sum(float(v) for v in w.values()) or 1
    out = {}
    for k, v in w.items():
        nm = MS.get(k)
        if nm:
            nm = (rename or {}).get(nm, nm)
            out[nm] = dict(w=round(100 * float(v) / tot, 2), part=True)
    return out


def uk():
    import yfinance as yf
    G = json.load(open("data/scan/uk/group_pulse.json"))
    syms = sorted({m["symbol"] for r in G["rows"] for m in r.get("members", [])})
    mc = {}
    for s_ in syms:
        try:
            v = yf.Ticker(s_ + ".L").fast_info.get("market_cap") or yf.Ticker(s_ + ".L").fast_info.get("marketCap")
            if v:
                mc[s_] = float(v)
        except Exception:  # noqa: BLE001
            pass
    print("UK caps", len(mc), "of", len(syms))
    if not mc:
        return {}
    norm = lambda x: re.sub(r"\s+", " ", (x or "").replace("&", "and")).strip().lower()  # noqa: E731
    sec_names = {norm(s["sector"]): s["sector"] for s in G.get("sectors", [])}
    rows = [(m["symbol"], r.get("sector")) for r in G["rows"] for m in r.get("members", [])]
    D = pd.DataFrame(rows, columns=["sym", "sec"]).drop_duplicates("sym"); D = D[D.sym.isin(mc)]; D["mc"] = D.sym.map(mc)
    D = D.sort_values("mc", ascending=False).head(100); tot = D.mc.sum()
    g = D.groupby("sec").mc.sum()
    return {sec_names.get(norm(k), k): dict(w=round(float(100 * v / tot), 2), n=int((D.sec == k).sum()), part=True) for k, v in g.items()}


_EUROPE_UNUSED = {"United Kingdom", "France", "Germany", "Switzerland", "Netherlands", "Sweden", "Denmark", "Italy", "Spain", "Finland", "Belgium",
          "Norway", "Ireland", "Austria", "Portugal", "Poland", "Greece", "Czech Republic", "Hungary"}
EM = {"China", "Taiwan", "India", "Korea (South)", "Brazil", "Saudi Arabia", "South Africa", "Mexico", "Indonesia", "Thailand", "Malaysia",
      "United Arab Emirates", "Qatar", "Kuwait", "Poland", "Turkey", "Philippines", "Chile", "Greece", "Peru", "Hungary", "Czech Republic",
      "Colombia", "Egypt"}


def world():
    """21 Nov 2026 (Amritpal: "I can't see bigger dots" on the world map -> "size every market"): each market's share of world stocks
    = MSCI ACWI country weights from the iShares ACWI product page (country table). Markets the table folds into "Other" are scaled
    from the matching iShares fund through a country both tables list: Emerging markets + Brazil via EEM (by India, China, Taiwan,
    Korea), Hong Kong via EPP (by Australia), Europe via IEUR (by UK, France, Germany, Switzerland, Netherlands).
    US Nasdaq 100 = Nasdaq-100 market value (QQQ's top-10 holdings / their weights) over the US market (3,000 largest US caps), times
    the US weight; US small caps = US stocks ranked 1,001-3,000 by market cap (Russell 2000 rule), same scaling.
    Bonds, gold, oil, the dollar and Bitcoin are not world stocks: no weight (hollow dots)."""
    import re as _re
    import requests
    H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}

    def table(path):
        t = requests.get(f"https://www.ishares.com/us/products/{path}", headers=H, timeout=60).text
        rows = _re.findall(r'_ws-colType[^"]*">([^<]+)</td><td class="_ws-colFund[^"]*">(-?[\d.]+)%', t)
        out = {}
        for k, v in rows:
            out.setdefault(k.strip(), float(v))   # first table on the page = countries (sectors use other names)
        return out
    A = table("239600/ishares-msci-acwi-etf")
    if len(A) < 8:
        raise RuntimeError(f"ACWI country table not found ({len(A)} rows)")

    def scale(T, keys):
        r = [A[k] / T[k] for k in keys if A.get(k) and T.get(k)]
        return sum(r) / len(r) if r else None
    EMt, EPPt, EUt = table("239637/ishares-msci-emerging-markets-etf"), table("239674/ishares-msci-pacific-ex-japan-etf"), table("264617/ishares-core-msci-europe-etf")
    EAt = table("239623/ishares-msci-eafe-etf")   # developed ex-US/Canada: Australia, Hong Kong, Netherlands live here
    if len(EAt) > 5:
        A.update({k: v * scale(EAt, ["Japan", "United Kingdom", "France", "Germany", "Switzerland"]) for k, v in EAt.items() if k not in A and k in ("Australia", "Hong Kong", "Netherlands")})
    em = scale(EMt, ["India", "China", "Taiwan", "Korea (South)"]); px = scale(EPPt, ["Australia"])
    eu = scale(EUt, ["United Kingdom", "France", "Germany", "Switzerland", "Netherlands"])
    g = lambda k: A.get(k, 0.0)  # noqa: E731
    m = {"US S&P 500": g("United States"), "UK": g("United Kingdom"), "Germany": g("Germany"), "Japan": g("Japan"), "China": g("China"),
         "India": g("India"), "Australia": g("Australia"), "Korea": g("Korea (South)"), "Taiwan": g("Taiwan"), "Canada": g("Canada")}
    if em:
        m["Emerging mkts"] = 100 * em; m["Brazil"] = EMt.get("Brazil", 0) * em
    if A.get("Hong Kong"):
        m["Hong Kong"] = A["Hong Kong"]
    elif px:
        m["Hong Kong"] = EPPt.get("Hong Kong", 0) * px
    if eu:
        m["Europe"] = 100 * eu
    try:
        import yfinance as yf
        mc = caps("data/scan/us/fundamentals.json"); us = sorted(mc.values(), reverse=True)[:3000]; ust = sum(us)
        th = yf.Ticker("QQQ").funds_data.top_holdings
        hw = {str(sym): float(r.iloc[-1]) for sym, r in th.iterrows()}
        if "GOOG" in hw and "GOOGL" in hw:   # two share classes, one company market cap
            hw["GOOGL"] += hw.pop("GOOG")
        cov = sum(w for s_, w in hw.items() if s_ in mc)
        if cov > 0.2:
            ndx = sum(mc[s_] for s_ in hw if s_ in mc) / cov
            m["US Nasdaq 100"] = m["US S&P 500"] * min(1.0, ndx / ust)
        m["US small caps"] = m["US S&P 500"] * sum(us[1000:3000]) / ust
    except Exception as e:  # noqa: BLE001
        print("US slices", e)
    print("ACWI table", A, "| scales em/px/eu", em, px, eu)
    part = {"US S&P 500", "Japan", "China", "Hong Kong", "India", "Australia", "Korea", "Taiwan", "Brazil", "Canada", "Europe"}
    return {k: dict(w=round(float(v), 2), part=k in part) for k, v in m.items() if v and v > 0}


def main():
    import sys
    sys.path.insert(0, "tools")
    from world_sector_rrg import CFG
    out = dict(generated=str(date.today()), method=__doc__.split("\n\n")[1].split("Output:")[0].strip())
    out["NSE"] = nse()
    out["US"] = fund_sectors("SPY")
    try:
        out["ASX"] = fund_sectors("STW.AX", {"Technology": "Info Tech", "Real Estate": "A-REITs"})
    except Exception as e:  # noqa: BLE001
        print("ASX fund data failed", e); out["ASX"] = {}
    if len(out["ASX"]) < 8:
        out["ASX"] = by_meta(U + "asx_meta.csv", "data/scan/asx/fundamentals.json", 200, CFG["ASX"]["names"])
    out["WSECT"] = fund_sectors("ACWI", {"Technology": "Info Tech"})
    out["UK"] = uk()
    try:
        out["WORLD"] = world()
    except Exception as e:  # noqa: BLE001
        print("world weights failed", e); out["WORLD"] = {}
    for k in ("NSE", "US", "ASX", "WSECT", "UK", "WORLD"):
        print("R|", k, len(out[k]), sorted(((float(v["w"]), n) for n, v in out[k].items()), reverse=True)[:11])
    if os.environ.get("PILOT"):
        print("JSON|" + json.dumps(out, separators=(",", ":"), default=float))
        return
    json.dump(out, open("data/scan/sector_weights.json", "w"), separators=(",", ":"), default=float)


if __name__ == "__main__":
    main()
