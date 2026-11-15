"""Research (15 Nov 2026): RSI range rule on coins, commodities, currencies, world indices (Yahoo daily).
Short: below a falling 30-week SMA, RSI(14) rallies into 55-65 (never above 65 in 20 bars) and crosses back below 55.
Long mirror: above a rising SMA, RSI dips into 35-45 (never below 35) and crosses back above 45. Stop = 10-bar extreme.
Exit A: RSI 35 / 65 target; exit B: weekly close back across the 30-week SMA; both exit on RSI > 65 (short) / < 35 (long)."""
import time
import numpy as np, pandas as pd, yfinance as yf
COST = 0.001

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
A.pop("Bonds", None)

def rsi(c, n=14):
    d = np.diff(c, prepend=c[0]); up = pd.Series(np.maximum(d, 0)).ewm(alpha=1 / n, adjust=False).mean(); dn = pd.Series(np.maximum(-d, 0)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).fillna(50).to_numpy()
def sim(o, h, l, c, R, trend_up, trend_dn, wk_up, wk_dn, idx, ok, tf, sym):
    out = []; n = len(c); t = 25
    while t < n - 1:
        sig = None
        if trend_dn[t] and R[t] < 55 <= R[t - 1] and R[t - 5:t].max() <= 65 and R[t - 20:t].max() <= 65 and R[t - 5:t].max() >= 55: sig = 'S'
        elif trend_up[t] and R[t] > 45 >= R[t - 1] and R[t - 20:t].min() >= 35 and R[t - 5:t].min() <= 45: sig = 'L'
        if sig is None or not ok(t): t += 1; continue
        e = o[t + 1]; stop = h[t - 9:t + 1].max() * 1.001 if sig == 'S' else l[t - 9:t + 1].min() * 0.999
        if (sig == 'S' and e >= stop) or (sig == 'L' and e <= stop): t += 1; continue
        for ex in 'AB':
            xi = None; xp = None
            for u in range(t + 1, n):
                if sig == 'S':
                    if o[u] >= stop and u > t + 1: xp, xi = o[u], u; break
                    if h[u] >= stop: xp, xi = stop, u; break
                    hit = (R[u] <= 35) if ex == 'A' else wk_up[u]
                    if hit or R[u] >= 65:
                        if u + 1 < n: xp, xi = o[u + 1], u + 1
                        break
                else:
                    if o[u] <= stop and u > t + 1: xp, xi = o[u], u; break
                    if l[u] <= stop: xp, xi = stop, u; break
                    hit = (R[u] >= 65) if ex == 'A' else wk_dn[u]
                    if hit or R[u] <= 35:
                        if u + 1 < n: xp, xi = o[u + 1], u + 1
                        break
            if xi is None: xp, xi = c[-1], n - 1
            r = (e - xp) / e if sig == 'S' else (xp - e) / e
            risk = abs(stop - e) / e
            out.append(dict(sym=sym, tf=tf, side=sig, exit=ex, date=idx[t + 1], ret=r - COST, R=(r - COST) / risk, bars=xi - t))
        t += 3
    return out

rows = []
for grp, D in A.items():
    for t, nm in D.items():
        try:
            x = yf.download(t, start="2010-01-01", interval="1d", auto_adjust=False, progress=False)
        except Exception as e:  # noqa: BLE001
            print("fail", t, e); continue
        if x is None or x.empty: continue
        if isinstance(x.columns, pd.MultiIndex): x.columns = x.columns.get_level_values(0)
        x = x[["Open", "High", "Low", "Close"]].dropna(); x = x[(x.Close > 0) & (x.Open > 0)]
        if grp == "Currencies": x = x.assign(High=np.minimum(x.High, np.maximum(x.Open, x.Close) * 1.03), Low=np.maximum(x.Low, np.minimum(x.Open, x.Close) / 1.03))
        if len(x) < 500: continue
        COST = 0.002 if grp == "Crypto" else 0.001
        o, h, l, c = (x[k].to_numpy(float) for k in ("Open", "High", "Low", "Close")); idx = x.index; n = len(c)
        wkp = idx.to_period("W-FRI"); s = lambda a: pd.Series(a, index=idx)
        W = pd.DataFrame({"o": s(o).groupby(wkp).first(), "h": s(h).groupby(wkp).max(), "l": s(l).groupby(wkp).min(), "c": s(c).groupby(wkp).last(), "i": s(np.arange(n)).groupby(wkp).last()})
        W["sma"] = W.c.rolling(30).mean(); W["up"] = (W.c > W.sma) & (W.sma > W.sma.shift(4)); W["dn"] = (W.c < W.sma) & (W.sma < W.sma.shift(4))
        tu = np.zeros(n, bool); td = np.zeros(n, bool); wku = np.zeros(n, bool); wkd = np.zeros(n, bool); wi = W.i.to_numpy().astype(int)
        for k in range(len(W)):
            nx = wi[k + 1] if k + 1 < len(W) else n - 1
            tu[wi[k] + 1:nx + 1] = W.up.iloc[k]; td[wi[k] + 1:nx + 1] = W.dn.iloc[k]
            if np.isfinite(W.sma.iloc[k]): wku[wi[k]] = W.c.iloc[k] > W.sma.iloc[k]; wkd[wi[k]] = W.c.iloc[k] < W.sma.iloc[k]
        T1 = sim(o, h, l, c, rsi(c), tu, td, wku, wkd, idx, lambda t: True, "D", nm)
        Wo, Wh, Wl, Wc = (W[k].to_numpy() for k in "ohlc")
        T1 += sim(Wo, Wh, Wl, Wc, rsi(Wc), W.up.to_numpy(), W.dn.to_numpy(), (W.c > W.sma).to_numpy(), (W.c < W.sma).to_numpy(), W.index.to_timestamp(how="end"), lambda k: True, "W", nm)
        for r in T1: rows.append(dict(r, grp=grp))
        time.sleep(0.3)
T = pd.DataFrame(rows); T["yr"] = T.date.dt.year
def pf(v): return v[v > 0].sum() / -v[v < 0].sum() if (v < 0).any() else np.inf
print(T.groupby(["grp", "tf", "side", "exit"]).agg(n=("ret", "size"), avg=("ret", lambda v: v.mean() * 100), win=("ret", lambda v: (v > 0).mean() * 100), R=("R", "mean"), pf=("ret", pf)).round(2).to_string())
print("\nALL"); print(T.groupby(["tf", "side", "exit"]).agg(n=("ret", "size"), R=("R", "mean"), pf=("ret", pf)).round(2).to_string())
g = T[(T.grp.isin(["Crypto", "In rupees (≈MCX)", "Metals"])) & (T.side == "S") & (T.exit == "A")]
print("\nShort, exit A, R by year"); print(g.groupby(["grp", "yr"]).R.mean().unstack(0).round(2).to_string())
