"""ETFs and mutual funds for the Bottoms tab: distance from the all-time high, 'top-up zone' (20%+ below the high - the only
bottom rule that helped a SIP in the 2016-26 test, scratchpad etf/sip.py), 200-day average, RSI, returns, bottom patterns.
Writes data/scan/funds.json (rows) and data/scan/fund_charts.json (5 years of weekly closes per item, loaded on demand)."""
import concurrent.futures as cf, json, os, sys, time
from datetime import datetime, timezone
import numpy as np, pandas as pd, requests, yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mf_fetch import universe, hist  # noqa: E402
import pattern_scan as P  # noqa: E402

OUT = "data/scan"
ETFS = {"NIFTYBEES": "Nifty 50", "SETFNIF50": "Nifty 50 (SBI)", "JUNIORBEES": "Nifty Next 50", "MID150BEES": "Nifty Midcap 150",
        "MIDCAPETF": "Nifty Midcap 150 (Mirae)", "SMALLCAP": "Nifty Smallcap 250", "BANKBEES": "Nifty Bank", "PSUBNKBEES": "Nifty PSU Bank",
        "ITBEES": "Nifty IT", "PHARMABEES": "Nifty Pharma", "HEALTHIETF": "Nifty Healthcare", "AUTOBEES": "Nifty Auto",
        "INFRABEES": "Nifty Infrastructure", "CONSUMBEES": "Nifty Consumption", "CPSEETF": "CPSE", "MODEFENCE": "Nifty India Defence",
        "MOM100": "Nifty Midcap 100 (Motilal)", "MOMOMENTUM": "Nifty 200 Momentum 30", "ALPHA": "Nifty Alpha 50", "LOWVOLIETF": "Nifty 100 Low Vol 30",
        "NV20BEES": "Nifty 50 Value 20", "GOLDBEES": "Gold", "SILVERBEES": "Silver", "MON100": "US Nasdaq 100", "MAFANG": "US FANG+",
        "MONQ50": "US Nasdaq Q-50", "HNGSNGBEES": "Hang Seng", "GILT5YBEES": "5-yr G-Sec", "LTGILTBEES": "Long G-Sec"}
NO_TOPUP = {"GOLDBEES", "SILVERBEES", "GILT5YBEES", "LTGILTBEES", "MON100", "MAFANG", "MONQ50", "HNGSNGBEES"}
# top-up hurt on gold; not meant for debt; international ETFs swing with their premium to NAV (overseas-investment caps), not tested
INTL = {"MON100", "MAFANG", "MONQ50", "HNGSNGBEES"}
TOPUP = 20.0
# US ETFs (tradeable from Australia via moomoo/most brokers) and ASX ETFs incl. ASX-listed global ETFs
US_ETFS = {"SPY": "S&P 500", "QQQ": "Nasdaq 100", "DIA": "Dow Jones 30", "IWM": "Russell 2000 (small caps)", "VTI": "US total market",
           "RSP": "S&P 500 equal weight", "MDY": "S&P MidCap 400", "SCHD": "US dividend", "MTUM": "US momentum", "QUAL": "US quality",
           "USMV": "US min volatility", "XLK": "Technology", "XLF": "Financials", "XLV": "Health care", "XLE": "Energy", "XLI": "Industrials",
           "XLY": "Consumer discretionary", "XLP": "Consumer staples", "XLU": "Utilities", "XLB": "Materials", "XLRE": "Real estate",
           "XLC": "Communication services", "SMH": "Semiconductors", "IBB": "Biotech", "ARKK": "ARK Innovation", "ICLN": "Clean energy",
           "URA": "Uranium", "ITA": "Aerospace & defence", "VEA": "Developed ex-US", "EFA": "EAFE developed", "VWO": "Emerging markets",
           "EEM": "Emerging markets (iShares)", "INDA": "India (MSCI)", "EPI": "India earnings (WisdomTree)", "MCHI": "China", "KWEB": "China internet",
           "EWJ": "Japan", "EWZ": "Brazil", "EWG": "Germany", "EWU": "UK", "EWA": "Australia", "GLD": "Gold", "SLV": "Silver", "GDX": "Gold miners",
           "USO": "Crude oil", "DBC": "Commodities", "TLT": "US Treasuries 20y+", "IEF": "US Treasuries 7-10y", "SHY": "US Treasuries 1-3y",
           "LQD": "US investment-grade bonds", "HYG": "US high-yield bonds", "VNQ": "US REITs", "IBIT": "Bitcoin (iShares)"}
ASX_ETFS = {"VAS": "ASX 300 (Vanguard)", "A200": "ASX 200 (Betashares)", "IOZ": "ASX 200 (iShares)", "STW": "ASX 200 (SPDR)",
            "VHY": "ASX high yield", "MVW": "ASX equal weight", "ISO": "ASX small ords", "OZR": "ASX resources", "QFN": "ASX financials",
            "VGS": "World ex-Australia", "IWLD": "World ex-Australia (iShares)", "VGAD": "World ex-Aus, A$ hedged", "VEU": "All-world ex-US",
            "IVV": "S&P 500", "VTS": "US total market", "NDQ": "Nasdaq 100", "HNDQ": "Nasdaq 100, A$ hedged", "QUAL": "World quality", "MOAT": "US wide moat",
            "IHVV": "S&P 500, A$ hedged", "SEMI": "Global semiconductors", "HACK": "Global cybersecurity", "RBTZ": "Robotics & AI", "FANG": "FANG+",
            "ETHI": "Global sustainability leaders", "ASIA": "Asia technology", "VAE": "Asia ex-Japan", "IAA": "Asia 50", "VGE": "Emerging markets",
            "IEM": "Emerging markets (iShares)", "NDIA": "India (Global X)", "IIND": "India quality (Betashares)", "IZZ": "China large-cap", "CETF": "China A-shares",
            "IJP": "Japan", "IEU": "Europe 350", "VEQ": "Europe (Vanguard)", "F100": "FTSE 100", "VDHG": "Diversified high growth",
            "DHHF": "Diversified all growth", "VAP": "Australian property", "GOLD": "Gold (Perth Mint)", "QAU": "Gold, A$ hedged", "ETPMAG": "Silver",
            "VAF": "Australian bonds", "IAF": "Australian bonds (iShares)", "AAA": "Cash (high interest)"}
ASX_NO_TOPUP = {"GOLD", "QAU", "ETPMAG", "VAF", "IAF", "AAA"}; US_NO_TOPUP = {"GLD", "SLV", "GDX", "USO", "DBC", "TLT", "IEF", "SHY", "LQD", "HYG", "IBIT"}


def rsi(c, n=14):
    d = np.diff(c, prepend=c[0]); u = pd.Series(np.where(d > 0, d, 0.0)).ewm(alpha=1 / n, adjust=False).mean()
    v = pd.Series(np.where(d < 0, -d, 0.0)).ewm(alpha=1 / n, adjust=False).mean(); return float((100 - 100 / (1 + u / v.clip(lower=1e-12))).iloc[-1])


def metrics(s, key, name, kind, cat, ohlc=None, market="IN", no_topup=NO_TOPUP):
    s = s.dropna(); s = s[s > 0]
    if len(s) < 260:
        return None, None
    c = s.to_numpy(float); hi_i = int(np.argmax(c)); last = s.index[-1]
    ret = lambda d: float((c[-1] / s.loc[:last - pd.Timedelta(days=d)].iloc[-1] - 1) * 100) if s.index[0] <= last - pd.Timedelta(days=d) else None
    sma200 = float(pd.Series(c).rolling(200).mean().iloc[-1])
    below = float((1 - c[-1] / c[hi_i]) * 100)
    row = dict(key=key, name=name, kind=kind, category=cat, close=float(c[-1]), asof=str(last.date()), high=float(c[hi_i]), high_date=str(s.index[hi_i].date()),
               below_high_pct=round(below, 2), low_52w=float(s.loc[last - pd.Timedelta(days=365):].min()), above_200=bool(c[-1] > sma200), sma200=round(sma200, 2),
               rsi=round(rsi(c), 1), r1m=ret(30), r3m=ret(91), r1y=ret(365), r3y_cagr=None,
               topup=bool(below >= TOPUP and key not in no_topup and kind != "debt"), intl=market == "IN" and key in INTL, market=market, pattern=None)
    if s.index[0] <= last - pd.Timedelta(days=3 * 365):
        row["r3y_cagr"] = float(((c[-1] / s.loc[:last - pd.Timedelta(days=3 * 365)].iloc[-1]) ** (1 / 3) - 1) * 100)
    x = ohlc if ohlc is not None else pd.DataFrame({"Open": s, "High": s, "Low": s, "Close": s})
    try:
        pr = P.scan(x.tail(750), key, name, "stock")
        if pr:
            row["pattern"] = dict(typ=pr["typ"], status=pr["status"], neck=pr["neck"], to_neck_pct=pr["to_neck_pct"], days_since=pr["days_since"])
    except Exception:  # noqa: BLE001
        pass
    w = s.resample("W-FRI").last().dropna().tail(260)
    return row, dict(t=[str(d.date()) for d in w.index], c=[round(float(v), 4) for v in w])


def main():
    os.makedirs(OUT, exist_ok=True); rows, charts = [], {}
    # ETFs
    dd = yf.download([k + ".NS" for k in ETFS], period="max", interval="1d", auto_adjust=True, progress=False, group_by="column", threads=True)
    from session import drop_partial
    for k, nm in ETFS.items():
        try:
            x = pd.DataFrame({c: dd[c][k + ".NS"] for c in ("Open", "High", "Low", "Close")}).dropna(subset=["Close"])
            x = drop_partial(x, "NSE")
            # Yahoo ETF history has split jumps (e.g. N100 -> MON100 1:10); cut history before any >40% one-day move
            j = np.flatnonzero(np.abs(np.diff(np.log(x.Close.to_numpy()))) > 0.4)
            if len(j):
                x = x.iloc[j[-1] + 1:]
            r, ch = metrics(x.Close, k, nm, "debt" if "G-Sec" in nm else "etf", "ETF", x)
            if r:
                rows.append(r); charts[k] = ch
            else:
                print("skip etf", k, len(x))
        except Exception as e:  # noqa: BLE001
            print("etf fail", k, e)
    print("etfs", len(rows), flush=True)
    # US and ASX ETFs (keys prefixed so they never clash with Indian symbols / AMFI codes)
    for mkt, lst, suf, nt in (("US", US_ETFS, "", US_NO_TOPUP), ("AU", ASX_ETFS, ".AX", ASX_NO_TOPUP)):
        try:
            dd2 = yf.download([k + suf for k in lst], period="max", interval="1d", auto_adjust=True, progress=False, group_by="column", threads=True)
        except Exception as e:  # noqa: BLE001
            print("download fail", mkt, e); continue
        n1 = len(rows)
        for k, nm in lst.items():
            try:
                x = pd.DataFrame({c: dd2[c][k + suf] for c in ("Open", "High", "Low", "Close")}).dropna(subset=["Close"])
                x = drop_partial(x, "US" if mkt == "US" else "ASX")
                j = np.flatnonzero(np.abs(np.diff(np.log(x.Close.to_numpy()))) > 0.4)
                if len(j):
                    x = x.iloc[j[-1] + 1:]
                kind = "debt" if any(w in nm for w in ("Treasur", "bonds", "Cash")) else "etf"
                r, ch = metrics(x.Close, f"{mkt}:{k}", nm, kind, "ETF", x, market=mkt, no_topup=nt | {f"{mkt}:{z}" for z in nt})
                if r:
                    r["symbol"] = k; rows.append(r); charts[r["key"]] = ch
                else:
                    print("skip", mkt, k, len(x))
            except Exception as e:  # noqa: BLE001
                print("fail", mkt, k, str(e)[:60])
        print(mkt, "etfs", len(rows) - n1, flush=True)
    # mutual funds (equity + index, direct growth)
    u = universe(); print("funds in universe", len(u), flush=True); n0 = len(rows)
    def one(r):
        h = hist(int(r.code)); time.sleep(0.1)
        if h is None:
            return None
        s = h.set_index("Date").nav.sort_index(); s = s[~s.index.duplicated(keep="last")]
        if s.index[-1] < pd.Timestamp.now() - pd.Timedelta(days=10):
            return None
        return metrics(s, str(int(r.code)), r.name, "fund", r.category)
    with cf.ThreadPoolExecutor(4) as ex:
        for res in ex.map(one, u.itertuples()):
            if res and res[0]:
                rows.append(res[0]); charts[res[0]["key"]] = res[1]
    print("funds", len(rows) - n0, flush=True)
    for r in rows:
        for k, v in list(r.items()):
            if isinstance(v, float):
                r[k] = round(v, 2)
    rows.sort(key=lambda r: -r["below_high_pct"])
    json.dump(dict(generated=datetime.now(timezone.utc).isoformat(timespec="minutes"), topup_pct=TOPUP,
                   backtest_global="US/ASX SIP test 2005-26 (same rules): 20%-below top-up vs plain SIP: S&P 500 +0.2%/yr, Nasdaq 100 -0.5%, "
                                   "Russell 2000 +0.3%, ASX 200 +0.1%; 30% trigger: S&P -0.7%, Nasdaq -0.9%. Essentially no gain outside India.",
                   backtest="SIP test 2016-26 (same total money, 50% of each SIP kept in a liquid fund and deployed when the index is 20-30% "
                            "below its high): Nifty +0.6 to +1.7%/yr XIRR, Midcap 150 +0.2 to +1.5%, Smallcap 250 +0.2%; gold worse with every rule; "
                            "shallower triggers (10% below the high, below the 200-day average) added nothing. Bottom patterns: no edge (watch only).",
                   rows=rows), open(f"{OUT}/funds.json", "w"), separators=(",", ":"))
    json.dump(charts, open(f"{OUT}/fund_charts.json", "w"), separators=(",", ":"))
    print("rows", len(rows), "top-up", sum(r["topup"] for r in rows), "patterns", sum(bool(r["pattern"]) for r in rows),
          "size KB", os.path.getsize(f"{OUT}/funds.json") // 1024, os.path.getsize(f"{OUT}/fund_charts.json") // 1024)


if __name__ == "__main__":
    main()
