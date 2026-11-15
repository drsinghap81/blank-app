"""World stocks month-close check (15 Nov 2026): markets the main scans don't cover. For each liquid stock (about US$1 m a
day; India Rs 2 cr like the NSE scan): did the last COMPLETED month close above its old all-time-high monthly close after a
base of >= 12 months? Long cup = base >= 36 months with a fall >= 30% inside it. Same check as the Monthly ATH "Month
close" tab; information only, not tested in these markets.
Usage: python tools/world_mclose.py MARKET   (BSE, SME, JP, HK, CA, EU, KR, TW) -> data/scan/world/<MARKET>.json
Lists: BSE scrip list (BSE-only = ISIN not on NSE), NSE SME list, JPX, HKEX, TSX directory, Wikipedia index members
(Europe ex-UK), KRX, TWSE/TPEx. Prices: Yahoo (India: daily history with the split-gap fix; others: monthly bars)."""
import io, json, os, re, sys, time
from datetime import datetime, timezone
import numpy as np, pandas as pd, requests, yfinance as yf
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

M = sys.argv[1].upper()
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
      "Accept-Language": "en-US,en;q=0.9"}
NAME = dict(BSE="India · BSE-only", SME="India · NSE SME", JP="Japan", HK="Hong Kong", CA="Canada", EU="Europe (ex-UK)", KR="South Korea", TW="Taiwan")
# minimum average daily traded value (local currency), ~US$1 m; India Rs 2 cr as in the NSE scan
FLOOR = {".BO": 2e7, ".NS": 2e7, ".T": 1.5e8, ".HK": 8e6, ".TO": 1.4e6, ".KS": 1.4e9, ".KQ": 1.4e9, ".TW": 3e7, ".TWO": 3e7,
         ".DE": 1e6, ".PA": 1e6, ".AS": 1e6, ".MC": 1e6, ".MI": 1e6, ".BR": 1e6, ".HE": 1e6, ".LS": 1e6, ".IR": 1e6, ".VI": 1e6,
         ".SW": 1e6, ".ST": 1e7, ".OL": 1e7, ".CO": 7e6}
CUR = {".BO": "₹", ".NS": "₹", ".T": "¥", ".HK": "HK$", ".TO": "C$", ".KS": "₩", ".KQ": "₩", ".TW": "NT$", ".TWO": "NT$",
       ".SW": "CHF", ".ST": "SEK", ".OL": "NOK", ".CO": "DKK"}


def get(url, **kw):
    for k in range(3):
        try:
            r = requests.get(url, headers={**UA, **kw.pop("headers", {})}, timeout=60, **kw)
            if r.status_code == 200:
                return r
            print("HTTP", r.status_code, url[:90])
        except Exception as e:  # noqa: BLE001
            print("get fail", url[:80], str(e)[:60])
        time.sleep(3 + 5 * k)
    return None


def suffix(t):
    m = re.search(r"(\.[A-Z]+)$", t)
    return m.group(1) if m else ""


def lst_bse():
    nse = set()
    r = get("https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv", headers={"Referer": "https://www.nseindia.com/"})
    if r is not None:
        d = pd.read_csv(io.StringIO(r.text)); d.columns = [c.strip() for c in d.columns]; nse = set(d["ISIN NUMBER"].astype(str).str.strip())
    print("NSE ISINs", len(nse))
    out = {}
    r = get("https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w?Group=&Scripcode=&industry=&segment=Equity&status=Active",
            headers={"Referer": "https://www.bseindia.com/", "Origin": "https://www.bseindia.com", "Accept": "application/json, text/plain, */*"})
    try:
        d = pd.DataFrame(r.json()) if r is not None else pd.DataFrame()
        d = d[~d["ISIN_NUMBER"].astype(str).str.strip().isin(nse)]
        out = {f"{c}.BO": (str(s).strip(), str(n).strip().title()) for c, s, n in zip(d["SCRIP_CD"], d["scrip_id"], d["Scrip_Name"])}
    except Exception as e:  # noqa: BLE001
        print("BSE API list fail", str(e)[:60])
    if not out:   # fallback: the latest BSE equity bhavcopy (every traded scrip with its ISIN)
        for k in range(1, 10):
            dt = (pd.Timestamp.now(tz="Asia/Kolkata") - pd.Timedelta(days=k)).strftime("%Y%m%d")
            r = get(f"https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{dt}_F_0000.CSV", headers={"Referer": "https://www.bseindia.com/"})
            if r is None or b"ISIN" not in r.content[:2000]:
                continue
            d = pd.read_csv(io.StringIO(r.text)); d = d[~d["ISIN"].astype(str).str.strip().isin(nse)]
            if "SctySrs" in d:
                d = d[~d["SctySrs"].astype(str).str.strip().isin(["F", "G", "IF", "IT", "MF", "DB"])]
            out = {f"{c}.BO": (str(s).strip(), str(n).strip().title()) for c, s, n in zip(d["FinInstrmId"], d["TckrSymb"], d["FinInstrmNm"])}
            print("BSE list from bhavcopy", dt, len(out)); break
    if not out or not nse:
        raise RuntimeError("BSE or NSE list unavailable")
    return out


def lst_sme():
    r = get("https://nsearchives.nseindia.com/emerge/corporates/content/SME_EQUITY_L.csv", headers={"Referer": "https://www.nseindia.com/"})
    d = pd.read_csv(io.StringIO(r.text)); d.columns = [c.strip() for c in d.columns]
    nc = next(c for c in d.columns if "NAME" in c.upper())
    return {f"{s.strip()}.NS": (s.strip(), str(n).strip().title()) for s, n in zip(d["SYMBOL"], d[nc])}


def lst_jp():
    r = None
    for u in ("https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xls",
              "https://www.jpx.co.jp/english/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_e.xls"):
        r = get(u)
        if r is not None:
            break
    if r is None:     # the file's path changes: find the link on the list pages
        for pgu in ("https://www.jpx.co.jp/markets/statistics-equities/misc/01.html", "https://www.jpx.co.jp/english/markets/statistics-equities/misc/01.html"):
            pg = get(pgu); m = re.search(r'href="([^"]+\.xlsx?)"', pg.text) if pg is not None else None
            if m:
                r = get("https://www.jpx.co.jp" + m.group(1) if m.group(1).startswith("/") else m.group(1))
                if r is not None:
                    break
    if r is None:
        raise RuntimeError("JPX list unavailable")
    d = pd.read_excel(io.BytesIO(r.content)); cols = [str(c) for c in d.columns]
    if "Local Code" in cols:
        seg, code, name, ok = "Section/Products", "Local Code", "Name (English)", r"(Prime|Standard|Growth).*Domestic|Domestic.*(Prime|Standard|Growth)"
    else:
        seg, code, name, ok = "市場・商品区分", "コード", "銘柄名", r"(プライム|スタンダード|グロース).*内国株式"
    d = d[d[seg].astype(str).str.contains(ok, regex=True)]
    return {f"{c}.T": (str(c), str(n)) for c, n in zip(d[code], d[name])}


def lst_hk():
    r = get("https://www.hkex.com.hk/eng/services/trading/securities/securitieslists/ListOfSecurities.xlsx")
    d = pd.read_excel(io.BytesIO(r.content), skiprows=2)
    d = d[d["Category"].astype(str).str.strip() == "Equity"]
    return {f"{int(c):04d}.HK": (f"{int(c):04d}", str(n).strip()) for c, n in zip(d["Stock Code"], d["Name of Securities"])}


def lst_ca():
    out = {}
    r = get("https://www.tsx.com/json/company-directory/search/tsx/%5E*")
    for co in (r.json().get("results") or []) if r is not None else []:
        for ins in co.get("instruments") or [{"symbol": co.get("symbol"), "name": co.get("name")}]:
            s = str(ins.get("symbol") or "")
            if s and re.fullmatch(r"[A-Z]+(\.[A-Z])?", s):
                out[s.replace(".", "-") + ".TO"] = (s, ins.get("name") or co.get("name") or "")
    return out


EU_PAGES = {"DAX": ".DE", "MDAX": ".DE", "SDAX": ".DE", "TecDAX": ".DE", "CAC_40": ".PA", "SBF_120": ".PA", "AEX_index": ".AS", "AMX_index": ".AS",
            "Swiss_Market_Index": ".SW", "SMI_MID": ".SW", "IBEX_35": ".MC", "FTSE_MIB": ".MI", "OMX_Stockholm_30": ".ST", "OBX_Index": ".OL",
            "OMX_Copenhagen_25": ".CO", "OMX_Helsinki_25": ".HE", "BEL_20": ".BR", "PSI-20": ".LS", "ISEQ_20": ".IR", "Austrian_Traded_Index": ".VI"}


def lst_eu():
    out = {}
    for page, suf in EU_PAGES.items():
        r = get(f"https://en.wikipedia.org/wiki/{page}")
        if r is None:
            continue
        try:
            tabs = pd.read_html(io.StringIO(r.text))
        except Exception:  # noqa: BLE001
            continue
        for tb in tabs:
            cols = [str(c) for c in tb.columns]
            tc = next((c for c in cols if re.search(r"(?i)ticker|symbol", c)), None)
            nc = next((c for c in cols if re.search(r"(?i)company|name|constituent", c)), None)
            if tc is None or len(tb) < 8:
                continue
            for tk, nm in zip(tb[tc], tb[nc] if nc else tb[tc]):
                tk = str(tk).split(":")[-1].strip().split(" ")[0].upper()
                if not tk or tk == "NAN" or len(tk) > 12:
                    continue
                y = tk if re.search(r"\.[A-Z]{1,3}$", tk) else tk + suf
                out.setdefault(y, (tk.split(".")[0], str(nm)))
            break
        print(page, len(out))
    return out


def lst_kr():
    out = {}
    for mt, suf in (("stockMkt", ".KS"), ("kosdaqMkt", ".KQ")):
        r = get(f"https://kind.krx.co.kr/corpgeneral/corpList.do?method=download&marketType={mt}")
        if r is None:
            continue
        r.encoding = "euc-kr"
        d = pd.read_html(io.StringIO(r.text), converters={"종목코드": str})[0]
        out.update({f"{str(c).zfill(6)}{suf}": (str(c).zfill(6), str(n)) for c, n in zip(d["종목코드"], d["회사명"])})
    return out


def lst_tw():
    out = {}
    for mode, suf in ((2, ".TW"), (4, ".TWO")):
        r = get(f"https://isin.twse.com.tw/isin/C_public.jsp?strMode={mode}")
        if r is None:
            continue
        r.encoding = "big5"
        d = pd.read_html(io.StringIO(r.text))[0]
        d.columns = d.iloc[0]; d = d.iloc[1:]
        c0 = d.columns[0]; cfi = next((c for c in d.columns if "CFI" in str(c)), None)
        for v, k in zip(d[c0].astype(str), d[cfi].astype(str) if cfi else [""] * len(d)):
            m = re.match(r"^(\d{4})\s+(.+)$", v.replace("　", " "))
            if m and (not cfi or k.startswith("ES")):
                out[m.group(1) + suf] = (m.group(1), m.group(2).strip())
    return out


LISTS = dict(BSE=lst_bse, SME=lst_sme, JP=lst_jp, HK=lst_hk, CA=lst_ca, EU=lst_eu, KR=lst_kr, TW=lst_tw)


def dl(tick, **kw):
    for k in range(3):
        try:
            return yf.download(tick, auto_adjust=False, progress=False, group_by="column", threads=True, **kw)
        except Exception as e:  # noqa: BLE001
            print("yf retry", str(e)[:60]); time.sleep(10 + 10 * k)
    return None


def col(dd, f, t):
    try:
        return dd[f][t] if isinstance(dd.columns, pd.MultiIndex) else dd[f]
    except Exception:  # noqa: BLE001
        return None


def check(mc, w, lm):
    """mc: monthly closes (PeriodIndex), w: weekly closes up to the month end."""
    mc = mc.dropna()
    if not len(mc) or mc.index[-1] != lm or len(mc) < 14:
        return None
    prior = mc.iloc[:-1]
    if mc.iloc[-1] <= prior.max():
        return None
    a = int(np.argmax(prior.to_numpy())); base = len(prior) - a
    if base < 12:
        return None
    old = float(prior.iloc[a]); dep = float(prior.iloc[a + 1:].min() / old - 1) if a + 1 < len(prior) else 0.0
    sma = w.rolling(30).mean()
    rising = bool(len(sma.dropna()) > 5 and w.iloc[-1] > sma.iloc[-1] > sma.iloc[-5])
    return dict(month=str(lm), close_m=float(mc.iloc[-1]), old_ath=old, ath_month=str(prior.index[a]), base_months=int(base), depth=round(dep, 4),
                above_pct=round(float((mc.iloc[-1] / old - 1) * 100), 2), sma_rising=rising, long_cup=bool(base >= 36 and dep <= -0.30))


def main():
    L = LISTS[M]()
    print(M, "listed", len(L), flush=True)
    tick = list(L); lm = pd.Timestamp(datetime.now(timezone.utc).date()).to_period("M") - 1
    me = lm.to_timestamp(how="end")
    liq = {}
    for a in range(0, len(tick), 200):           # 1) liquidity over the 60 trading days to the month-end
        ch = tick[a:a + 200]; dd = dl(ch, start=(me - pd.Timedelta(days=100)).strftime("%Y-%m-%d"), end=(me + pd.Timedelta(days=1)).strftime("%Y-%m-%d"), interval="1d")
        if dd is None or dd.empty:
            continue
        for t in ch:
            c, v = col(dd, "Close", t), col(dd, "Volume", t)
            if c is None or v is None:
                continue
            val = float((c * v).dropna().tail(60).mean()) if (c * v).notna().sum() >= 20 else 0.0
            if val >= FLOOR.get(suffix(t), 1e6):
                liq[t] = val
        time.sleep(1)
    print(M, "liquid", len(liq), flush=True)
    rows = []; ok = list(liq); n_hist = n_cur = n_new = 0
    india = M in ("BSE", "SME")
    if india:
        from adjust import fix_gaps
    for a in range(0, len(ok), 40):              # 2) history for the liquid ones
        ch = ok[a:a + 40]
        dd = dl(ch, period="max", interval="1d")     # daily for every market: Yahoo's monthly bars can be wrong
        if dd is None or dd.empty:
            continue
        for t in ch:
            try:
                if india:
                    x = pd.DataFrame({f: col(dd, f, t) for f in ("Open", "High", "Low", "Close", "Volume")}).dropna(subset=["Close"])
                    x = x[x.Close > 0]
                    if len(x) < 300:
                        continue
                    o_, h_, l_, c_, v_ = fix_gaps(x.Open, x.High, x.Low, x.Close, x.Volume)
                    c = pd.Series(np.asarray(c_, float), index=x.index)
                    mc = c.groupby(c.index.to_period("M")).last(); mc = mc[mc.index <= lm]
                    w = c[c.index <= me].resample("W-FRI").last().dropna()
                    last = float(c.iloc[-1])
                else:
                    c = col(dd, "Close", t)
                    if c is None:
                        continue
                    c = c.dropna(); c = c[c > 0]
                    if len(c) < 300:
                        continue
                    mc = c.groupby(c.index.to_period("M")).last(); mc = mc[mc.index <= lm]
                    w = c[c.index <= me].resample("W-FRI").last().dropna()
                    last = float(c.iloc[-1])
                if t in os.environ.get("WM_DEBUG", "2480.TW").split(","):
                    print("DEBUG", t, "top monthly closes:", mc.sort_values().tail(5).round(2).to_dict(), "last", mc.tail(3).round(2).to_dict())
                n_hist += int(len(mc.dropna()) >= 14); n_cur += int(len(mc.dropna()) > 0 and mc.dropna().index[-1] == lm)
                m_ = mc.dropna()
                n_new += int(len(m_) >= 14 and m_.index[-1] == lm and m_.iloc[-1] > m_.iloc[:-1].max())   # new closing high, any base
                r = check(mc, w, lm)
                if r:
                    sym, nm = L[t]
                    rows.append(dict(ticker=t, symbol=sym, name=nm, market=M, cur=CUR.get(suffix(t), "€"), close=last,
                                     since_pct=round((last / r["close_m"] - 1) * 100, 2), value_m=round(liq[t] / 1e6, 2), **r))
            except Exception as e:  # noqa: BLE001
                print("fail", t, str(e)[:60])
        time.sleep(1)
    rows.sort(key=lambda r: (-r["long_cup"], -r["base_months"]))
    if M in ("JP", "KR", "TW"):     # English names from Yahoo (the exchange lists are in the local language)
        for r in rows:
            try:
                inf = yf.Ticker(r["ticker"]).info
                en = inf.get("longName") or inf.get("shortName")
                if en:
                    r["local_name"] = r["name"]; r["name"] = en
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.5)
    os.makedirs("data/scan/world", exist_ok=True)
    json.dump(dict(market=M, name=NAME[M], month=str(lm), generated=datetime.now(timezone.utc).isoformat(timespec="minutes"),
                   listed=len(L), liquid=len(liq), with_history=n_hist, with_last_month=n_cur, new_high_any_base=n_new, rows=rows), open(f"data/scan/world/{M}.json", "w"), separators=(",", ":"))
    print(M, "history >= 14 months", n_hist, "last month present", n_cur, "new closing high (any base)", n_new, "month-close rows", len(rows), [r["symbol"] for r in rows[:15]])


if __name__ == "__main__":
    main()
