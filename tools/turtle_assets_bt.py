"""Research (16 Nov 2026): Turtle rules (Amritpal's slide) on gold, commodities, coins, currencies and world indices, Yahoo daily.
Long: buy-stop above the 20-day high; fixed stop = entry - 2 ATR(20); trailing stop = 10-day low; first hit exits.
Short mirror: sell-stop below the 20-day low; fixed stop = entry + 2 ATR; trail = 10-day high. Also System 2 (55/20).
One position per asset per side; cost 0.10% (coins 0.20%). Results per trade in R (risk = 2 ATR) and %."""
import time
import numpy as np, pandas as pd, yfinance as yf

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


def run(x, nin, nout, side, cost):
    o, h, l, c = (x[k].to_numpy(float) for k in ("Open", "High", "Low", "Close")); n = len(c)
    tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    atr = np.r_[np.nan, pd.Series(tr).ewm(alpha=1 / 20, adjust=False, min_periods=20).mean().to_numpy()]
    hh = pd.Series(h).shift(1).rolling(nin).max().to_numpy(); ll = pd.Series(l).shift(1).rolling(nin).min().to_numpy()
    tlo = pd.Series(l).shift(1).rolling(nout).min().to_numpy(); thi = pd.Series(h).shift(1).rolling(nout).max().to_numpy()
    out = []; t = max(nin, 21) + 1
    while t < n:
        a = atr[t - 1]
        if side == "L" and np.isfinite(hh[t]) and h[t] > hh[t] and np.isfinite(a):
            e = max(o[t], hh[t]); fix = e - 2 * a; xi = None
            for u in range(t, n):
                st = max(fix, tlo[u]) if u > t and np.isfinite(tlo[u]) else fix
                if l[u] <= st: xp = min(o[u], st) if u > t else st; xi = u; break
            if xi is None: xp, xi = c[-1], n - 1
            out.append(dict(date=x.index[t], ret=xp / e - 1 - cost, R=(xp - e) / (2 * a) - cost * e / (2 * a), days=xi - t)); t = xi + 1
        elif side == "S" and np.isfinite(ll[t]) and l[t] < ll[t] and np.isfinite(a):
            e = min(o[t], ll[t]); fix = e + 2 * a; xi = None
            for u in range(t, n):
                st = min(fix, thi[u]) if u > t and np.isfinite(thi[u]) else fix
                if h[u] >= st: xp = max(o[u], st) if u > t else st; xi = u; break
            if xi is None: xp, xi = c[-1], n - 1
            out.append(dict(date=x.index[t], ret=e / xp - 1 - cost, R=(e - xp) / (2 * a) - cost * e / (2 * a), days=xi - t)); t = xi + 1
        else:
            t += 1
    return out


rows = []
for grp, D in A.items():
    for tk, nm in D.items():
        try:
            x = yf.download(tk, start="2010-01-01", interval="1d", auto_adjust=False, progress=False)
        except Exception as e:  # noqa: BLE001
            print("fail", tk, e); continue
        if x is None or x.empty: continue
        if isinstance(x.columns, pd.MultiIndex): x.columns = x.columns.get_level_values(0)
        x = x[["Open", "High", "Low", "Close"]].dropna(); x = x[(x.Close > 0) & (x.Open > 0)]
        if grp == "Currencies": x = x.assign(High=np.minimum(x.High, np.maximum(x.Open, x.Close) * 1.03), Low=np.maximum(x.Low, np.minimum(x.Open, x.Close) / 1.03))
        if len(x) < 500: continue
        cost = 0.002 if grp == "Crypto" else 0.001
        for sysn, nin, nout in (("20/10", 20, 10), ("55/20", 55, 20)):
            for side in "LS":
                for r in run(x, nin, nout, side, cost): rows.append(dict(r, grp=grp, asset=nm, sys=sysn, side=side))
        time.sleep(0.3)
T = pd.DataFrame(rows); T["yr"] = T.date.dt.year
def pf(v): return v[v > 0].sum() / -v[v < 0].sum() if (v < 0).any() else np.inf
agg = dict(n=("R", "size"), R=("R", "mean"), pf=("R", pf), win=("R", lambda v: (v > 0).mean() * 100), avg=("ret", lambda v: v.mean() * 100), days=("days", "median"))
pd.set_option("display.width", 200)
print(T.groupby(["grp", "sys", "side"]).agg(**agg).round(2).to_string())
print("\nALL"); print(T.groupby(["sys", "side"]).agg(**agg).round(2).to_string())
g = T[T.asset.isin(["Gold", "Silver", "Gold in rupees", "Crude oil (WTI)", "Bitcoin", "Ether", "S&P 500", "Nifty 50"])]
print("\nKey assets"); print(g.groupby(["asset", "sys", "side"]).agg(**agg).round(2).to_string())
y = T[(T.sys == "20/10")].groupby(["side", "yr"]).R.sum().unstack(0).round(1); print("\nSum of R by year, 20/10, all assets"); print(y.to_string())
