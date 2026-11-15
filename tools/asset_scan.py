"""Other assets (15 Nov 2026): commodities, currencies, crypto and world indices with the month-close ATH check used for
stocks and ETFs. For each: last completed monthly close vs the old all-time-high monthly close, base (months since that
high), the fall inside the base, and the 30-week SMA trend. Yahoo data; commodity futures are front-month continuous
contracts (not roll-adjusted), so long-run levels are approximate. Not tested as a trading system. -> data/scan/assets.json"""
import json, os, sys, time
from datetime import datetime, timezone
import numpy as np, pandas as pd, yfinance as yf
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fund_scan import mclose_state  # noqa: E402
from cupclose import IX_DY_DEP, IX_WK_DEP, wd_closes  # noqa: E402

A = {
    "Metals": {"GC=F": "Gold", "SI=F": "Silver", "PL=F": "Platinum", "PA=F": "Palladium", "HG=F": "Copper", "ALI=F": "Aluminium"},
    "Energy": {"CL=F": "Crude oil (WTI)", "BZ=F": "Crude oil (Brent)", "NG=F": "Natural gas", "HO=F": "Heating oil", "RB=F": "Gasoline"},
    "Agriculture": {"ZC=F": "Corn", "ZW=F": "Wheat", "ZS=F": "Soybeans", "ZM=F": "Soybean meal", "ZL=F": "Soybean oil", "KC=F": "Coffee",
                    "CC=F": "Cocoa", "SB=F": "Sugar", "CT=F": "Cotton", "OJ=F": "Orange juice", "LE=F": "Live cattle", "HE=F": "Lean hogs"},
    "Currencies": {"DX-Y.NYB": "US dollar index", "USDINR=X": "US dollar in rupees", "EURUSD=X": "Euro in US$", "GBPUSD=X": "Pound in US$",
                   "AUDUSD=X": "Australian dollar in US$", "USDJPY=X": "US dollar in yen", "USDCNY=X": "US dollar in yuan", "AUDINR=X": "Australian dollar in rupees",
                   "EURINR=X": "Euro in rupees", "GBPINR=X": "Pound in rupees", "JPYINR=X": "Yen in rupees", "SGDINR=X": "Singapore dollar in rupees",
                   "AEDINR=X": "UAE dirham in rupees", "NZDUSD=X": "NZ dollar in US$", "USDCAD=X": "US dollar in Canadian $", "USDCHF=X": "US dollar in Swiss franc",
                   "USDSGD=X": "US dollar in Singapore $", "USDKRW=X": "US dollar in won", "USDTWD=X": "US dollar in Taiwan $",
                   "USDBRL=X": "US dollar in real", "USDMXN=X": "US dollar in peso", "USDZAR=X": "US dollar in rand", "USDTRY=X": "US dollar in lira",
                   "EURGBP=X": "Euro in pounds", "EURJPY=X": "Euro in yen", "GBPJPY=X": "Pound in yen", "AUDJPY=X": "Australian dollar in yen",
                   "EURAUD=X": "Euro in Australian $", "GBPAUD=X": "Pound in Australian $", "AUDNZD=X": "Australian $ in NZ $"},
    "Crypto": {"BTC-USD": "Bitcoin", "ETH-USD": "Ether", "SOL-USD": "Solana", "XRP-USD": "XRP", "BNB-USD": "BNB", "ADA-USD": "Cardano",
               "DOGE-USD": "Dogecoin", "TRX-USD": "Tron", "AVAX-USD": "Avalanche", "LINK-USD": "Chainlink", "DOT-USD": "Polkadot", "LTC-USD": "Litecoin",
               "BCH-USD": "Bitcoin Cash", "XLM-USD": "Stellar", "SHIB-USD": "Shiba Inu", "TON11419-USD": "Toncoin", "HBAR-USD": "Hedera",
               "SUI20947-USD": "Sui", "NEAR-USD": "NEAR", "UNI7083-USD": "Uniswap", "ATOM-USD": "Cosmos", "XMR-USD": "Monero", "ETC-USD": "Ethereum Classic"},
    "Bonds": {"^TNX": "US 10-year yield", "^TYX": "US 30-year yield", "^FVX": "US 5-year yield"},
    "World indices": {"^GSPC": "S&P 500", "^NDX": "Nasdaq 100", "^DJI": "Dow Jones", "^RUT": "Russell 2000", "^NSEI": "Nifty 50", "^BSESN": "Sensex",
                      "^NSEBANK": "Nifty Bank", "^AXJO": "ASX 200", "^FTSE": "FTSE 100", "^GDAXI": "DAX", "^FCHI": "CAC 40", "^STOXX50E": "Euro Stoxx 50",
                      "^N225": "Nikkei 225", "^HSI": "Hang Seng", "000001.SS": "Shanghai Composite", "^KS11": "KOSPI", "^TWII": "Taiwan", "^BVSP": "Brazil Bovespa"},
}
INR = {"GC=F": "Gold in rupees", "SI=F": "Silver in rupees", "HG=F": "Copper in rupees", "ALI=F": "Aluminium in rupees",
       "CL=F": "Crude oil in rupees", "NG=F": "Natural gas in rupees"}   # ~MCX: global futures x US$/Rs (excludes Indian duties/premiums)
# 10-year government bond yields, monthly (OECD via FRED); published with a lag of a month or two
FRED = {"INDIRLTLT01STM": "India 10-year G-sec yield", "IRLTLT01GBM156N": "UK 10-year gilt yield", "IRLTLT01DEM156N": "Germany 10-year yield",
        "IRLTLT01JPM156N": "Japan 10-year yield", "IRLTLT01AUM156N": "Australia 10-year yield", "IRLTLT01CAM156N": "Canada 10-year yield"}
RAW = {}
rows = []


def add_row(t, nm, grp, x):
    mc = x.Close.resample("ME").last().dropna(); per = mc.index.to_period("M")
    mh = x.High.where(x.High.notna(), x.Close).resample("ME").max().reindex(mc.index)   # ATH = highest price (wicks), as on TradingView
    lm = pd.Timestamp(datetime.now(timezone.utc).date()).to_period("M") - 1
    done = mc[per <= lm]; dh = mh[per <= lm]
    if len(done) < 14:
        return
    a = int(np.nanargmax(dh.to_numpy())); old = float(dh.iloc[a])
    w = x.Close.resample("W-FRI").last().dropna(); sma = w.rolling(30).mean()
    r = dict(key=t, name=nm, group=grp, close=float(x.Close.iloc[-1]), asof=str(x.index[-1].date()), first=str(x.index[0].date()),
             ath_close=old, ath_month=str(per[per <= lm][a]), base_months=int(len(done) - 1 - a), below_ath_pct=round((1 - float(x.Close.iloc[-1]) / old) * 100, 2),
             sma_rising=bool(len(sma.dropna()) > 5 and w.iloc[-1] > sma.iloc[-1] > sma.iloc[-5]), mclose=None)
    try:
        r["wclose"], r["dclose"] = wd_closes(x, IX_WK_DEP, IX_DY_DEP) if grp == "World indices" else wd_closes(x)        # weekly / daily cup closes (watch only), 15 Nov 2026
    except Exception as e:  # noqa: BLE001
        print("wd fail", t, e); r["wclose"] = r["dclose"] = None
    try:
        r["mclose"] = mclose_state(x)
    except Exception as e:  # noqa: BLE001
        print("mclose fail", t, e)
    if r["mclose"]:                                  # the breakout month is the new ATH: report the OLD high it cleared
        r.update(ath_close=r["mclose"]["old_ath"], ath_month=r["mclose"]["ath_month"], base_months=r["mclose"]["base_months"])
    r["depth"] = r["mclose"]["depth"] if r["mclose"] else (round(float(done.iloc[a + 1:].min() / old - 1), 4) if a + 1 < len(done) else None)
    rows.append(r)


import io, requests
_FR = {}


def fred(sid):
    """Daily FRED series (H.10 noon exchange rates), cached."""
    if sid not in _FR:
        try:
            r = requests.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}", timeout=30)
            d = pd.read_csv(io.StringIO(r.text)); d.columns = ["Date", "v"]; d = d[pd.to_numeric(d.v, errors="coerce").notna()]
            _FR[sid] = pd.Series(d.v.astype(float).values, index=pd.to_datetime(d.Date))
        except Exception as e:  # noqa: BLE001
            print("FRED fail", sid, str(e)[:60]); _FR[sid] = None
    return _FR[sid]


# 15 Nov 2026: Yahoo's FX history starts ~2003, so older highs were missed (USD/CAD 1.62 in 2002). Older history from the
# Fed's daily rates (FRED); crosses from two legs. AED is pegged at 3.6725 per US$.
FXF = {"USDCAD=X": ("DEXCAUS",), "USDINR=X": ("DEXINUS",), "USDJPY=X": ("DEXJPUS",), "EURUSD=X": ("DEXUSEU",), "GBPUSD=X": ("DEXUSUK",),
       "AUDUSD=X": ("DEXUSAL",), "USDCHF=X": ("DEXSZUS",), "USDSGD=X": ("DEXSIUS",), "USDKRW=X": ("DEXKOUS",), "USDTWD=X": ("DEXTAUS",),
       "USDBRL=X": ("DEXBZUS",), "USDMXN=X": ("DEXMXUS",), "USDZAR=X": ("DEXSFUS",), "USDCNY=X": ("DEXCHUS",), "NZDUSD=X": ("DEXUSNZ",),
       "EURINR=X": ("DEXUSEU", "*", "DEXINUS"), "GBPINR=X": ("DEXUSUK", "*", "DEXINUS"), "JPYINR=X": ("DEXINUS", "/", "DEXJPUS"),
       "AUDINR=X": ("DEXUSAL", "*", "DEXINUS"), "SGDINR=X": ("DEXINUS", "/", "DEXSIUS"), "AEDINR=X": ("DEXINUS", "/", 3.6725),
       "EURGBP=X": ("DEXUSEU", "/", "DEXUSUK"), "EURJPY=X": ("DEXUSEU", "*", "DEXJPUS"), "GBPJPY=X": ("DEXUSUK", "*", "DEXJPUS"),
       "AUDJPY=X": ("DEXUSAL", "*", "DEXJPUS"), "EURAUD=X": ("DEXUSEU", "/", "DEXUSAL"), "GBPAUD=X": ("DEXUSUK", "/", "DEXUSAL"),
       "AUDNZD=X": ("DEXUSAL", "/", "DEXUSNZ")}


def fx_hist(t):
    spec = FXF.get(t)
    if not spec:
        return None
    a = fred(spec[0])
    if a is None or len(spec) == 1:
        return a
    b = spec[2] if isinstance(spec[2], float) else fred(spec[2])
    if b is None:
        return None
    if isinstance(b, float):
        return a / b if spec[1] == "/" else a * b
    j = pd.concat([a, b], axis=1, join="inner").dropna()
    return j.iloc[:, 0] * j.iloc[:, 1] if spec[1] == "*" else j.iloc[:, 0] / j.iloc[:, 1]


for grp, D in A.items():
    for t, nm in D.items():
        x = None
        for _ in range(3):
            try:
                x = yf.download(t, period="max", interval="1d", auto_adjust=False, progress=False)
                break
            except Exception as e:  # noqa: BLE001
                print("retry", t, e); time.sleep(5)
        if x is None or x.empty:
            print("no data", t); continue
        if isinstance(x.columns, pd.MultiIndex):
            x.columns = x.columns.get_level_values(0)
        x = x[["Open", "High", "Low", "Close"]].dropna(subset=["Close"]); x = x[x.Close > 0]
        if len(x) < 400:
            continue
        if grp == "Currencies":
            # Yahoo FX highs have bad spikes (USD/KRW 21,353): cap the day's high at 3% above its open/close
            x = x.assign(High=np.minimum(x.High, np.maximum(x.Open, x.Close) * 1.03))
            h = fx_hist(t)
            if h is not None and len(h):
                old = h[h.index < x.index[0]]
                if len(old):
                    x = pd.concat([pd.DataFrame({"Open": old, "High": old, "Low": old, "Close": old}), x])
                    nm_from = str(old.index[0].date()); print(t, "history from", nm_from)
        RAW[t] = x
        add_row(t, nm, grp, x)
        time.sleep(0.5)
for sid, nm in FRED.items():
    try:
        r = requests.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}", timeout=30)
        d = pd.read_csv(io.StringIO(r.text)); d.columns = ["Date", "v"]
        d = d[pd.to_numeric(d.v, errors="coerce").notna()]
        s = pd.Series(d.v.astype(float).values, index=pd.to_datetime(d.Date) + pd.offsets.MonthEnd(0))
        x = pd.DataFrame({"Open": s, "High": s, "Low": s, "Close": s})
        n0 = len(rows); add_row("FRED:" + sid, nm, "Bonds", x)
        if len(rows) > n0:
            rows[-1]["sma_rising"] = None; rows[-1]["monthly"] = True
            if rows[-1]["mclose"]:
                rows[-1]["mclose"]["sma_rising"] = None
    except Exception as e:  # noqa: BLE001
        print("FRED fail", sid, str(e)[:80])
fx = RAW.get("USDINR=X")
if fx is not None:
    f = fx.Close
    for t, nm in INR.items():
        if t in RAW:
            x = RAW[t]; k = f.reindex(x.index, method="ffill")
            xi = x[["Open", "High", "Low", "Close"]].mul(k, axis=0).dropna()
            if len(xi) >= 400:
                add_row(t + ":INR", nm, "In rupees (≈MCX)", xi)
os.makedirs("data/scan", exist_ok=True)
json.dump(dict(generated=datetime.now(timezone.utc).isoformat(timespec="minutes"),
               month=str(pd.Timestamp(datetime.now(timezone.utc).date()).to_period("M") - 1), rows=rows),
          open("data/scan/assets.json", "w"), separators=(",", ":"))
print(len(rows), "assets;", sum(1 for r in rows if r["mclose"]), "closed last month above an ATH >= 12 months old:",
      [r["name"] for r in rows if r["mclose"]])
