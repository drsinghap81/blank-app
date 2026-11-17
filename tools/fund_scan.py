"""ETFs and mutual funds for the Bottoms tab: distance from the all-time high, 'top-up zone' (20%+ below the high - the only
bottom rule that helped a SIP in the 2016-26 test, scratchpad etf/sip.py), 200-day average, RSI, returns, bottom patterns.
Writes data/scan/funds.json (rows) and data/scan/fund_charts.json (5 years of weekly closes per item, loaded on demand)."""
import concurrent.futures as cf, json, os, sys, time
from datetime import datetime, timezone
import numpy as np, pandas as pd, requests, yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mf_fetch import universe, hist  # noqa: E402
import pattern_scan as P  # noqa: E402
from cupclose import IX_DY_DEP, IX_WK_DEP, wd_closes, wd_short  # noqa: E402

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
           "EEM": "Emerging markets (iShares)", "INDA": "India (MSCI)", "EPI": "India earnings (WisdomTree)", "INDY": "India 50 (iShares)", "SMIN": "India small-cap (iShares)", "FLIN": "India (Franklin FTSE)", "GLIN": "India growth leaders (VanEck)", "NFTY": "India Nifty 50 equal weight (First Trust)", "INCO": "India consumer (Columbia)", "MCHI": "China", "KWEB": "China internet",
           "EWJ": "Japan", "EWZ": "Brazil", "EWG": "Germany", "EWU": "UK", "EWA": "Australia", "GLD": "Gold", "SLV": "Silver", "GDX": "Gold miners",
           "USO": "Crude oil", "DBC": "Commodities", "TLT": "US Treasuries 20y+", "IEF": "US Treasuries 7-10y", "SHY": "US Treasuries 1-3y",
           "LQD": "US investment-grade bonds", "HYG": "US high-yield bonds", "VNQ": "US REITs", "IBIT": "Bitcoin (iShares)"}
ASX_ETFS = {"VAS": "ASX 300 (Vanguard)", "A200": "ASX 200 (Betashares)", "IOZ": "ASX 200 (iShares)", "STW": "ASX 200 (SPDR)",
            "VHY": "ASX high yield", "MVW": "ASX equal weight", "ISO": "ASX small ords", "OZR": "ASX resources", "QFN": "ASX financials",
            "VGS": "World ex-Australia", "IWLD": "World ex-Australia (iShares)", "VGAD": "World ex-Aus, A$ hedged", "VEU": "All-world ex-US",
            "IVV": "S&P 500", "VTS": "US total market", "NDQ": "Nasdaq 100", "HNDQ": "Nasdaq 100, A$ hedged", "QUAL": "World quality", "MOAT": "US wide moat",
            "IHVV": "S&P 500, A$ hedged", "SEMI": "Global semiconductors", "HACK": "Global cybersecurity", "RBTZ": "Robotics & AI", "FANG": "FANG+",
            "ETHI": "Global sustainability leaders", "ASIA": "Asia technology", "VAE": "Asia ex-Japan", "IAA": "Asia 50", "VGE": "Emerging markets",
            "IEM": "Emerging markets (iShares)", "NDIA": "India (Global X)", "IIND": "India quality (Betashares)", "GRIN": "India growth leaders (VanEck)", "IAEF": "India Avenue equity (active)", "FIIN": "India (Fidelity, active)", "IZZ": "China large-cap", "CETF": "China A-shares",
            "IJP": "Japan", "IEU": "Europe 350", "VEQ": "Europe (Vanguard)", "F100": "FTSE 100", "VDHG": "Diversified high growth",
            "DHHF": "Diversified all growth", "VAP": "Australian property", "GOLD": "Gold (Perth Mint)", "QAU": "Gold, A$ hedged", "ETPMAG": "Silver",
            "VAF": "Australian bonds", "IAF": "Australian bonds (iShares)", "AAA": "Cash (high interest)"}
ASX_NO_TOPUP = {"GOLD", "QAU", "ETPMAG", "VAF", "IAF", "AAA"}; US_NO_TOPUP = {"GLD", "SLV", "GDX", "USO", "DBC", "TLT", "IEF", "SHY", "LQD", "HYG", "IBIT"}


def rsi(c, n=14):
    d = np.diff(c, prepend=c[0]); u = pd.Series(np.where(d > 0, d, 0.0)).ewm(alpha=1 / n, adjust=False).mean()
    v = pd.Series(np.where(d < 0, -d, 0.0)).ewm(alpha=1 / n, adjust=False).mean(); return float((100 - 100 / (1 + u / v.clip(lower=1e-12))).iloc[-1])


def ath_state(x):
    """Monthly ATH system on one series (daily OHLC; NAVs use the close for all four), same rules as tools/ath_scan.py:
    trigger = HIGH of the highest-monthly-close completed month; base = months since that month (>= 12 listed, >= 24 = tested);
    entry the first day the price trades above the trigger while the last completed week closed above a rising 30-week SMA
    (higher than 4 weeks earlier), at max(open, trigger); exit at the next open after a weekly close below the 30-week SMA.
    Returns the latest signal (last 18 months) or a 'near' state (within 5% below the trigger)."""
    x = x.dropna(subset=["Close"]); last = x.index[-1]
    if len(x) < 400:
        return None
    m = x.resample("ME").agg({"High": "max", "Close": "last"}).dropna()
    w = x.Close.resample("W-FRI").last().dropna(); sma = w.rolling(30).mean()
    cur_p = last.to_period("M"); done = m[m.index.to_period("M") < cur_p]
    o, h, c = x.Open.to_numpy(float), x.High.to_numpy(float), x.Close.to_numpy(float); d = x.index
    sig = None; pos = None; start = last - pd.DateOffset(months=18); after = -1
    months = [p for p in m.index.to_period("M") if p.to_timestamp() >= start.to_period("M").to_timestamp()]
    for p in months:
        prev = m[m.index.to_period("M") < p]
        if len(prev) < 13:
            continue
        a = int(np.argmax(prev.Close.to_numpy())); trig = float(prev.High.iloc[a]); base = len(prev) - a - 1 + 1
        days = np.flatnonzero(d.to_period("M") == p)
        for i in days:
            if pos is not None:
                break
            if i <= after:
                continue
            if base >= 12 and h[i] > trig:
                wk = w[w.index < d[i] - pd.Timedelta(days=d[i].weekday())]
                if len(wk) < 35:
                    break
                s_now, s_4 = sma.loc[wk.index[-1]], sma.loc[wk.index[-5]]
                if wk.iloc[-1] > s_now and s_now > s_4:
                    dep = float(prev.Close.iloc[a + 1:].min() / prev.Close.iloc[a] - 1) if a + 1 < len(prev) else 0.0
                    pos = dict(i=i, entry=float(max(o[i], trig)), trigger=trig, ath_month=str(prev.index[a].to_period("M")), base_months=int(base), depth=round(dep, 4))
                break
        if pos is not None:
            # walk weekly closes after entry
            for wd in w.index[w.index >= d[pos["i"]]]:
                if wd > last:
                    break
                if w.loc[wd] < sma.loc[wd]:
                    j = np.searchsorted(d, wd, side="right")
                    if j < len(d):
                        sig = dict(status="exited", date=str(d[pos["i"]].date()), exit_date=str(d[j].date()), exit_price=float(o[j]), **{k: v for k, v in pos.items() if k != "i"})
                    else:
                        sig = dict(status="exit next open", date=str(d[pos["i"]].date()), **{k: v for k, v in pos.items() if k != "i"})
                    break
            else:
                sig = dict(status="breakout" if d[pos["i"]].to_period("M") >= cur_p - 1 else "open", date=str(d[pos["i"]].date()), **{k: v for k, v in pos.items() if k != "i"})
            if sig and sig["status"] == "exited":
                pos = None; after = int(np.searchsorted(d, pd.Timestamp(sig["exit_date"])))
            else:
                break
    if sig and sig["status"] != "exited":
        sig["ret"] = float(c[-1] / sig["entry"] - 1); sig["sma30"] = float(sma.iloc[-1]); return sig
    # near: within 5% below the trigger, base >= 12, above a rising 30-week SMA
    a = int(np.argmax(done.Close.to_numpy())); trig = float(done.High.iloc[a]); base = len(done) - a
    if len(sma.dropna()) > 5 and base >= 12 and trig * 0.95 <= c[-1] <= trig and w.iloc[-1] > sma.iloc[-1] > sma.iloc[-5]:
        dep = float(done.Close.iloc[a + 1:].min() / done.Close.iloc[a] - 1) if a + 1 < len(done) else 0.0
        return dict(status="near", trigger=trig, ath_month=str(done.index[a].to_period("M")), base_months=int(base), depth=round(dep, 4),
                    gap_pct=float((trig / c[-1] - 1) * 100), sma30=float(sma.iloc[-1]))
    if sig:
        sig["ret"] = float(sig["exit_price"] / sig["entry"] - 1); return sig
    return None


def mclose_state(x):
    """Month-end list (15 Nov 2026), same as tools/ath_scan.py: the last COMPLETED month CLOSED above the all-time HIGH price of
    all earlier months (wicks included, as on TradingView), after a base >= 12 months since that high.
    Long cup = base >= 36 months with a fall >= 30% inside it."""
    x = x.dropna(subset=["Close"])
    hi = x["High"].where(x["High"].notna(), x.Close) if "High" in x else x.Close
    mc = x.Close.resample("ME").last().dropna(); mh = hi.resample("ME").max().reindex(mc.index)
    lm = pd.Timestamp(datetime.now(timezone.utc).date()).to_period("M") - 1
    per = mc.index.to_period("M")
    if len(mc) < 14 or per[-1] < lm or lm not in set(per):
        return None
    i = list(per).index(lm); prior_h = mh.iloc[:i]; prior_c = mc.iloc[:i]
    if len(prior_h) < 13 or mc.iloc[i] <= prior_h.max():
        return None
    a = int(np.nanargmax(prior_h.to_numpy())); base = i - a
    if base < 12:
        return None
    old = float(prior_h.iloc[a]); dep = float(prior_c.iloc[a + 1:].min() / old - 1) if a + 1 < len(prior_c) else 0.0
    w = x.Close.resample("W-FRI").last().dropna(); w = w[w.index <= mc.index[i]]; sma = w.rolling(30).mean()
    rising = bool(len(sma.dropna()) > 5 and w.iloc[-1] > sma.iloc[-1] > sma.iloc[-5])
    return dict(month=str(lm), close_m=float(mc.iloc[i]), high_m=float(mh.iloc[i]), old_ath=old, ath_month=str(per[a]), base_months=int(base), depth=round(dep, 4),
                above_pct=round(float((mc.iloc[i] / old - 1) * 100), 2), sma_rising=rising, long_cup=bool(base >= 36 and dep <= -0.30))


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
        row["ath"] = ath_state(x) if kind != "debt" else None      # bond / cash ETFs have no cup-and-trend breakouts
    except Exception as e:  # noqa: BLE001
        row["ath"] = None; print("ath fail", key, str(e)[:80])
    try:
        row["mclose"] = mclose_state(x) if kind != "debt" else None
    except Exception as e:  # noqa: BLE001
        row["mclose"] = None; print("mclose fail", key, str(e)[:80])
    try:   # week / day cup closes for ETFs only (mutual funds trade once a day at NAV with exit loads: not for swing trades); index-style cups
        row["wclose"], row["dclose"] = wd_closes(x, IX_WK_DEP, IX_DY_DEP) if kind == "etf" else (None, None)
    except Exception as e:  # noqa: BLE001
        row["wclose"] = row["dclose"] = None; print("wd fail", key, str(e)[:80])
    try:   # support breaks under a falling 30-week SMA (watch only)
        row["wshort"], row["dshort"] = wd_short(x) if kind == "etf" else (None, None)
    except Exception as e:  # noqa: BLE001
        row["wshort"] = row["dshort"] = None; print("short fail", key, str(e)[:80])
    try:
        pr = P.scan(x.tail(750), key, name, "stock")
        if pr:
            row["pattern"] = dict(typ=pr["typ"], status=pr["status"], neck=pr["neck"], to_neck_pct=pr["to_neck_pct"], days_since=pr["days_since"], lows=pr.get("lows"))
    except Exception:  # noqa: BLE001
        pass
    w = s.resample("W-FRI").last().dropna().tail(260)
    return row, dict(t=[str(d.date()) for d in w.index], c=[round(float(v), 4) for v in w])

# 15 Nov 2026: all liquid ETFs (NSE list, US listings) + UK/European UCITS ETFs, for the month-close and ATH lists.
# Charts for these go to data/scan/etf_charts/<key>.json (one small file each) to keep fund_charts.json light.
UCITS_ETFS = {"VUSA.L": "S&P 500 (Vanguard, dist)", "VUAG.L": "S&P 500 (Vanguard, acc)", "CSPX.L": "S&P 500 (iShares, acc)", "IUSA.L": "S&P 500 (iShares, dist)",
              "SWDA.L": "MSCI World (iShares)", "VWRL.L": "FTSE All-World (Vanguard, dist)", "VWRP.L": "FTSE All-World (Vanguard, acc)", "VEVE.L": "Developed world (Vanguard)",
              "VHVG.L": "Developed world (Vanguard, acc)", "EQQQ.L": "Nasdaq 100 (Invesco)", "CNDX.L": "Nasdaq 100 (iShares)", "ISF.L": "FTSE 100 (iShares)",
              "VUKE.L": "FTSE 100 (Vanguard)", "VMID.L": "FTSE 250 (Vanguard)", "CUKX.L": "FTSE 100 (iShares, acc)", "VFEM.L": "Emerging markets (Vanguard)",
              "EMIM.L": "Emerging markets IMI (iShares)", "VJPN.L": "Japan (Vanguard)", "VERX.L": "Europe ex-UK (Vanguard)", "VAPX.L": "Asia Pacific ex-Japan (Vanguard)",
              "IGLT.L": "UK gilts (iShares)", "INXG.L": "UK index-linked gilts", "SGLN.L": "Gold (iShares)", "PHAU.L": "Gold (WisdomTree)", "SSLN.L": "Silver (iShares)",
              "IITU.L": "US technology (iShares)", "INRG.L": "Clean energy (iShares)", "RBOT.L": "Robotics & automation (iShares)", "WTAI.L": "AI & innovation (WisdomTree)",
              "SMGB.L": "Semiconductors (VanEck)", "GDGB.L": "Gold miners (VanEck)", "SPY4.L": "S&P 400 mid cap (SPDR)", "R2US.L": "Russell 2000 (SPDR)",
              "SXLK.L": "US technology (SPDR)", "SXLF.L": "US financials (SPDR)", "SXLV.L": "US health care (SPDR)", "SXLE.L": "US energy (SPDR)", "SXLI.L": "US industrials (SPDR)",
              "SXLY.L": "US consumer discretionary (SPDR)", "SXLP.L": "US consumer staples (SPDR)", "SXLU.L": "US utilities (SPDR)", "SXLB.L": "US materials (SPDR)",
              "SXLC.L": "US communication services (SPDR)", "BTEK.L": "US biotech (iShares)", "NDIA.L": "India (iShares)", "FRIN.L": "India (Franklin)",
              "HMCH.L": "China (HSBC)", "IAPD.L": "Asia Pacific dividend (iShares)", "VGOV.L": "UK gilts (Vanguard)", "CSH2.L": "GBP cash (Lyxor/Amundi)",
              "ERNS.L": "GBP ultrashort bond (iShares)", "VAGS.L": "Global aggregate bonds (Vanguard)", "XDWT.L": "World IT (Xtrackers)", "HEAL.L": "Healthcare innovation (iShares)",
              "ISPY.L": "Cybersecurity (L&G)", "DFNS.L": "Defence (VanEck)", "NATO.L": "Defence (HANetf)", "COPX.L": "Copper miners (Global X)", "URNM.L": "Uranium miners (Sprott)",
              "EUNL.DE": "MSCI World (iShares, Xetra)", "SXR8.DE": "S&P 500 (iShares, Xetra)", "VWCE.DE": "FTSE All-World (Vanguard, Xetra)", "EXS1.DE": "DAX (iShares)",
              "SXRV.DE": "Nasdaq 100 (iShares, Xetra)", "IS3N.DE": "EM IMI (iShares, Xetra)", "EXSA.DE": "Stoxx Europe 600 (iShares)", "4GLD.DE": "Gold (Xetra-Gold)"}
EXTRA_DEBT = r"(?i)gilt|treasur|bond|cash|liquid|g-?sec|sdl|bharat bond|money market|ultrashort|aggregate|t-?bill|overnight|floating|income|duration|govt|government|corporate"


def _hist(tick, period):
    try:
        return yf.download(tick, period=period, interval="1d", auto_adjust=False, progress=False, group_by="column", threads=True)
    except Exception as e:  # noqa: BLE001
        print("download fail", period, len(tick), str(e)[:60]); return None


def extra_etfs(rows, have):
    import io, re
    H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36", "Referer": "https://www.nseindia.com/"}
    lists = []
    try:   # India: NSE's ETF list
        r = requests.get("https://nsearchives.nseindia.com/content/equities/eq_etfseclist.csv", headers=H, timeout=30)
        d = pd.read_csv(io.StringIO(r.content.decode("utf-8", "ignore"))); d.columns = [c.strip().lower() for c in d.columns]
        sc = next(c for c in d.columns if "symbol" in c); nc = next((c for c in d.columns if "underlying" in c), next(c for c in d.columns if "name" in c))
        L = {str(s).strip(): str(n).strip() for s, n in zip(d[sc], d[nc]) if str(s).strip() not in ETFS}
        lists.append(("IN", {k + ".NS": v for k, v in L.items()}, 5e6, "NSE")); print("NSE ETF list", len(L))
    except Exception as e:  # noqa: BLE001
        print("NSE ETF list fail", str(e)[:80])
    try:   # US: every listed ETF (nasdaqtrader directories)
        U = {}
        for u, sc in (("https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt", "Symbol"), ("https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt", "ACT Symbol")):
            r = requests.get(u, timeout=30); d = pd.read_csv(io.StringIO(r.text), sep="|")
            d = d[(d["ETF"] == "Y") & (d["Test Issue"] == "N")]
            U.update({str(s): str(n) for s, n in zip(d[sc], d["Security Name"]) if isinstance(s, str) and re.fullmatch(r"[A-Z]{1,5}", s) and s not in US_ETFS
                      and not re.search(r"(?i)\b(daily|[1-5](\.\d+)?x|ultra(pro)?|leveraged|inverse|bear|short|option income|covered call|buffer|yieldmax)\b", str(n))})
        lists.append(("US", U, 1e7, "US")); print("US ETF list", len(U))
    except Exception as e:  # noqa: BLE001
        print("US ETF list fail", str(e)[:80])
    lists.append(("UK", UCITS_ETFS, 0, "UK"))
    from session import drop_partial
    os.makedirs(f"{OUT}/etf_charts", exist_ok=True); keep = set()
    for mkt, L, minval, ses in lists:
        tick = list(L); ok = []
        if minval:   # liquidity screen on the last 3 months, then full history for the liquid ones
            for a in range(0, len(tick), 200):
                dd = _hist(tick[a:a + 200], "3mo")
                if dd is None or dd.empty:
                    continue
                for t in tick[a:a + 200]:
                    try:
                        v = float((dd["Close"][t] * dd["Volume"][t]).tail(60).mean())
                        if v >= minval:
                            ok.append(t)
                    except Exception:  # noqa: BLE001
                        pass
        else:
            ok = tick
        print(mkt, "liquid ETFs", len(ok), "of", len(tick), flush=True); n1 = len(rows)
        for a in range(0, len(ok), 100):
            dd = _hist(ok[a:a + 100], "max")
            if dd is None or dd.empty:
                continue
            for t in ok[a:a + 100]:
                try:
                    x = pd.DataFrame({c: dd[c][t] for c in ("Open", "High", "Low", "Close")}).dropna(subset=["Close"])
                    if not len(x):
                        continue
                    x = drop_partial(x, ses)
                    if mkt == "IN":   # Yahoo NSE history can miss ETF splits: cut before a >40% one-day jump (US/UK are adjusted)
                        j = np.flatnonzero(np.abs(np.diff(np.log(x.Close.to_numpy()))) > 0.4)
                        if len(j):
                            x = x.iloc[j[-1] + 1:]
                    sym = t[:-3] if mkt == "IN" else t
                    key = sym if mkt == "IN" else f"{mkt}:{sym}"
                    if key in have:
                        continue
                    nm = L[t]
                    kind = "debt" if re.search(EXTRA_DEBT, nm) else "etf"
                    r, ch = metrics(x.Close, key, nm, kind, "ETF", x, market=mkt, no_topup={key})
                    if r:
                        r["symbol"] = sym; r["extra"] = True; rows.append(r); have.add(key)
                        fn = key.replace(":", "_").replace("/", "_"); keep.add(fn + ".json")
                        json.dump(ch, open(f"{OUT}/etf_charts/{fn}.json", "w"), separators=(",", ":"))
                except Exception as e:  # noqa: BLE001
                    print("fail", mkt, t, str(e)[:60])
        print(mkt, "extra ETFs", len(rows) - n1, flush=True)
    if keep:
        for f in os.listdir(f"{OUT}/etf_charts"):
            if f not in keep:
                os.remove(f"{OUT}/etf_charts/{f}")


def main():
    os.makedirs(OUT, exist_ok=True); rows, charts = [], {}
    # ETFs
    dd = yf.download([k + ".NS" for k in ETFS], period="max", interval="1d", auto_adjust=False, progress=False, group_by="column", threads=True)
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
            dd2 = yf.download([k + suf for k in lst], period="max", interval="1d", auto_adjust=False, progress=False, group_by="column", threads=True)
        except Exception as e:  # noqa: BLE001
            print("download fail", mkt, e); continue
        n1 = len(rows)
        for k, nm in lst.items():
            try:
                x = pd.DataFrame({c: dd2[c][k + suf] for c in ("Open", "High", "Low", "Close")}).dropna(subset=["Close"])
                x = drop_partial(x, "US" if mkt == "US" else "ASX")   # Yahoo adjusts US/ASX splits: keep full history (real crashes are real)
                kind = "debt" if any(w in nm for w in ("Treasur", "bonds", "Cash")) else "etf"
                r, ch = metrics(x.Close, f"{mkt}:{k}", nm, kind, "ETF", x, market=mkt, no_topup=nt | {f"{mkt}:{z}" for z in nt})
                if r:
                    r["symbol"] = k; rows.append(r); charts[r["key"]] = ch
                else:
                    print("skip", mkt, k, len(x))
            except Exception as e:  # noqa: BLE001
                print("fail", mkt, k, str(e)[:60])
        print(mkt, "etfs", len(rows) - n1, flush=True)
    try:
        extra_etfs(rows, {r["key"] for r in rows})
    except Exception as e:  # noqa: BLE001
        print("extra ETFs fail", str(e)[:120])
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
                   ath_note="Monthly ATH rules on ETFs and funds (2016-26 tests): Indian mutual funds 3-8%/yr vs 11-14% buy-and-hold (few signals, "
                            "whipsaw exits and exit loads); US and ASX stocks showed no edge with these rules; ETFs not separately tested. Watch only.",
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
