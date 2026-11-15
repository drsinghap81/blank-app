"""Research (15 Nov 2026): do SHORT trades work on assets that trend both ways (coins, commodities, currencies, world indices)?
Yahoo daily data. Each system run long and short; costs 0.10% a round trip (0.20% for coins). One position per asset at a time.
  921   : EMA9 crosses EMA21 (short: below, while under a falling 30-week SMA; long: above, over a rising one); exit on the opposite cross.
  S30   : weekly close crosses below a falling 30-week SMA (short) / above a rising one (long); exit on the weekly close back across.
  CUPW  : weekly close below the 2-year low (26+ weeks old, 20%+ rally since) under a falling 30-week SMA; cover on a weekly close above it.
          (long mirror: weekly close above the 2-year high after a 20%+ dip, over a rising SMA)
  CUPD  : the same on daily bars (1-year extreme, 20+ days old, 15%+ move).
Entry at the next day's open."""
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


def trades_for(x, grp):
    o, h, l, c = (x[k].to_numpy(float) for k in ("Open", "High", "Low", "Close")); idx = x.index; n = len(c)
    cost = 0.002 if grp == "Crypto" else 0.001
    e9 = pd.Series(c).ewm(span=9, adjust=False).mean().to_numpy(); e21 = pd.Series(c).ewm(span=21, adjust=False).mean().to_numpy()
    wk = idx.to_period("W-FRI"); W = pd.DataFrame({"c": pd.Series(c, index=idx).groupby(wk).last(), "h": pd.Series(h, index=idx).groupby(wk).max(),
                                                   "l": pd.Series(l, index=idx).groupby(wk).min(), "i": pd.Series(np.arange(n), index=idx).groupby(wk).last()})
    W["sma"] = W.c.rolling(30).mean(); W["rise"] = W.sma > W.sma.shift(4)
    wi = W.i.to_numpy().astype(int); wc = W.c.to_numpy(); ws = W.sma.to_numpy(); wr = W.rise.to_numpy()
    above = np.full(n, np.nan); rising = np.full(n, np.nan); wend = np.zeros(n, bool)   # state of the LAST COMPLETED week, known from the next day
    for k in range(len(wi)):
        nxt = wi[k + 1] if k + 1 < len(wi) else n - 1
        if np.isfinite(ws[k]): above[wi[k] + 1:nxt + 1] = wc[k] > ws[k]; rising[wi[k] + 1:nxt + 1] = wr[k]
        wend[wi[k]] = True
    wabove_at_close = np.full(n, np.nan)
    for k in range(len(wi)):
        if np.isfinite(ws[k]): wabove_at_close[wi[k]] = wc[k] > ws[k]
    out = []
    def run(name, side, entry_sig, exit_sig):
        t = 0
        while t < n - 1:
            if entry_sig(t):
                ei = t + 1; e = o[ei]; xi = None
                for u in range(ei, n - 1):
                    if exit_sig(u): xi = u + 1; break
                if xi is None: xi = n - 1; xp = c[-1]
                else: xp = o[xi]
                r = (xp / e - 1) if side == "L" else (e / xp - 1)
                out.append(dict(sys=name, side=side, date=idx[ei], ret=r - cost, days=xi - ei))
                t = xi
            else:
                t += 1
    ok = lambda v: v == v
    # 9/21
    run("921", "S", lambda t: e9[t] < e21[t] and e9[t - 1] >= e21[t - 1] and ok(above[t]) and above[t] == 0 and rising[t] == 0, lambda u: e9[u] > e21[u])
    run("921", "L", lambda t: e9[t] > e21[t] and e9[t - 1] <= e21[t - 1] and ok(above[t]) and above[t] == 1 and rising[t] == 1, lambda u: e9[u] < e21[u])
    # S30 (signals on week-end bars)
    prev = {}
    wk_idx = {int(wi[k]): k for k in range(len(wi))}
    def s30(side):
        def ent(t):
            k = wk_idx.get(t)
            if k is None or k < 35 or not np.isfinite(ws[k]) or not np.isfinite(ws[k - 1]): return False
            if side == "S": return wc[k] < ws[k] and wc[k - 1] >= ws[k - 1] and not wr[k]
            return wc[k] > ws[k] and wc[k - 1] <= ws[k - 1] and wr[k]
        def ex(u):
            k = wk_idx.get(u)
            if k is None or not np.isfinite(ws[k]): return False
            return wc[k] > ws[k] if side == "S" else wc[k] < ws[k]
        return ent, ex
    for sd in "SL":
        en, ex = s30(sd); run("S30", sd, en, ex)
    # cups
    def cup(side, weekly):
        H = W.h.to_numpy() if weekly else h; L = W.l.to_numpy() if weekly else l; C = wc if weekly else c
        K, B, D = (104, 26, 0.20) if weekly else (250, 20, 0.15)
        def ent(t):
            if weekly:
                k = wk_idx.get(t)
                if k is None: return False
            else:
                k = t
            if k < B + 3 or not np.isfinite(ws[wk_idx.get(t, 0)] if weekly else 1): return False
            lo = max(0, k - K)
            if side == "S":
                a = lo + int(np.argmin(L[lo:k])); rim = L[a]
                if not (C[k] < rim and k - a >= B and C[a + 1:k].max() / rim - 1 >= D): return False
                return (above[t] == 0 and rising[t] == 0) if not weekly else (wc[wk_idx[t]] < ws[wk_idx[t]] and not wr[wk_idx[t]])
            a = lo + int(np.argmax(H[lo:k])); rim = H[a]
            if not (C[k] > rim and k - a >= B and C[a + 1:k].min() / rim - 1 <= -D): return False
            return (above[t] == 1 and rising[t] == 1) if not weekly else (wc[wk_idx[t]] > ws[wk_idx[t]] and wr[wk_idx[t]])
        def ex(u):
            k = wk_idx.get(u)
            if k is None or not np.isfinite(ws[k]): return False
            return wc[k] > ws[k] if side == "S" else wc[k] < ws[k]
        return ent, ex
    for sd in "SL":
        en, ex = cup(sd, True); run("CUPW", sd, en, ex)
        en, ex = cup(sd, False); run("CUPD", sd, en, ex)
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
        for r in trades_for(x, grp): rows.append(dict(r, grp=grp, asset=nm))
        time.sleep(0.3)
T = pd.DataFrame(rows); T["yr"] = T.date.dt.year
pd.set_option("display.width", 200)
def pf(v): return v[v > 0].sum() / -v[v < 0].sum() if (v < 0).any() else np.inf
g = T.groupby(["grp", "sys", "side"]).ret.agg(n="size", avg=lambda v: v.mean() * 100, med=lambda v: v.median() * 100, win=lambda v: (v > 0).mean() * 100, pf=pf)
print(g.round(2).to_string())
print("\nALL groups:"); print(T.groupby(["sys", "side"]).ret.agg(n="size", avg=lambda v: v.mean() * 100, win=lambda v: (v > 0).mean() * 100, pf=pf).round(2).to_string())
s = T[T.side == "S"]
for grp in s.grp.unique():
    y = s[s.grp == grp].groupby(["sys", "yr"]).ret.sum().unstack(0) * 100
    print("\nSHORT", grp, "sum of trade % by year"); print(y.round(0).fillna(0).astype(int).to_string())
fx = T[(T.asset.str.contains("in rupees")) | (T.asset == "US dollar in rupees")]
print("\nRupee pairs:"); print(fx.groupby(["asset", "sys", "side"]).ret.agg(n="size", avg=lambda v: v.mean() * 100, pf=pf).round(2).to_string())
btc = T[T.asset.isin(["Bitcoin", "Ether"])]
print("\nBTC/ETH:"); print(btc.groupby(["asset", "sys", "side"]).ret.agg(n="size", avg=lambda v: v.mean() * 100, win=lambda v: (v > 0).mean() * 100, pf=pf).round(2).to_string())
