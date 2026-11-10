"""Industry Pulse (our own computation of the 'industry group breadth' idea): for each industry group, the share of its liquid
stocks that are 'trending' over the last 1 week / 1 month / 1 quarter.
trending(stock, day) = weighted RPI > 100 (mean of 2-week / 3-month / 6-month performance vs the market index x 100)
                       AND EMA9 > EMA21 AND close > SMA150 AND SMA150 rising over 20 days (Stage 2) AND close >= 75% of the 52-week high.
India groups: Yahoo industries, with banks split into PSU / private large / private mid & small / small finance, autos into
2W-3W-EV / PV & tractors / CV & buses, and a Dairy group (NSE_SPLIT).
Backtest NSE 2017-26 (scratchpad pulse/): top 10% of groups by 1-month Pulse beat the bottom 10% by +2.9% over the next 3 months
(+2.4% 2017-21, +3.4% 2022-26), better than plain group return (+1.8%); as a hard ATH filter it did not help.
Usage: python tools/group_pulse.py NSE|US|ASX  -> data/scan[/us|/asx]/group_pulse.json"""
import json, os, sys, time
from datetime import datetime, timezone
import numpy as np, pandas as pd, yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from session import drop_partial  # noqa: E402

CFG = {"NSE": dict(out="data/scan/", bench="^NSEI", suf=".NS", minval=2e7, minpx=50),
       "US": dict(out="data/scan/us/", bench="^GSPC", suf="", minval=1e7, minpx=5),
       "ASX": dict(out="data/scan/asx/", bench="^AXJO", suf=".AX", minval=1e6, minpx=20)}   # A$20 floor (10 Nov 2026)


NSE_SPLIT = {
    "Banks - PSU": ["SBIN", "BANKBARODA", "PNB", "CANBK", "UNIONBANK", "INDIANB", "BANKINDIA", "CENTRALBK", "IOB", "UCOBANK", "MAHABANK", "PSB", "IDBI"],
    "Banks - Private Large": ["HDFCBANK", "ICICIBANK", "KOTAKBANK", "AXISBANK", "INDUSINDBK"],
    "Banks - Small Finance & Payments": ["AUBANK", "EQUITASBNK", "UJJIVANSFB", "SURYODAY", "UTKARSHBNK", "ESAFSFB", "CAPITALSFB", "JSFB", "FINOPB"],
    "Auto - 2W/3W/EV": ["HEROMOTOCO", "BAJAJ-AUTO", "EICHERMOT", "TVSMOTOR", "TVSHLTD", "OLAELEC", "ATHERENERG", "ATULAUTO", "MERCURYEV"],
    "Auto - PV & Tractors": ["MARUTI", "M&M", "TMPV", "HYUNDAI", "ESCORTS", "VSTTILLERS"],
    "Auto - CV & Buses": ["TMCV", "ASHOKLEY", "SMLMAH", "FORCEMOT", "OLECTRA"],
    "Dairy": ["HATSUN", "DODLA", "PARAGMILK", "HERITGFOOD", "MILKYMIST", "MLKFOOD", "UMANGDAIRY", "VADILALIND"],
}


def universe(mkt):
    if mkt == "NSE":
        u = pd.read_csv("data/universe/nse_industry.csv").rename(columns={"basic_industry": "group"})
        u["sector"] = u["sector"].fillna("Other")
        try:
            nm = pd.read_csv("data/universe/niftytotalmarket.csv"); names = dict(zip(nm.Symbol, nm["Company Name"]))
        except Exception:  # noqa: BLE001
            names = {}
        u["name"] = u.symbol.map(names).fillna(u.symbol)
        u["group"] = u.group.replace({"Confectioners": "Sugar & Confectionery"})   # Yahoo labels Indian sugar mills 'Confectioners'
        # split Yahoo's broad groups the way Indian investors group them (private vs PSU banks, 2-wheelers vs cars, dairy)
        ov = {}
        for g, ss in NSE_SPLIT.items():
            for x in ss:
                ov[x] = g
        add = [x for x in ov if x not in set(u.symbol)]
        if add:
            u = pd.concat([u, pd.DataFrame({"symbol": add, "name": add, "group": [ov[x] for x in add]})], ignore_index=True)
        secmap = {"Banks": "Financial Services", "Auto - ": "Consumer Cyclical", "Dairy": "Consumer Defensive"}
        for x, g in ov.items():
            u.loc[u.symbol == x, "sector"] = next(v for k, v in secmap.items() if g.startswith(k))
        u["group"] = [ov.get(x, g) for x, g in zip(u.symbol, u.group)]
        u.loc[u.group == "Banks - Regional", "group"] = "Banks - Private Mid & Small"
        u.loc[u.group == "Auto Manufacturers", "group"] = "Auto - PV & Tractors"
    else:
        u = pd.read_csv(f"data/universe/{'us' if mkt == 'US' else 'asx'}_meta.csv").rename(columns={"industry": "group"})
    u = u.dropna(subset=["group", "symbol"]); u["symbol"] = u.symbol.astype(str); u["name"] = u.name.fillna(u.symbol).astype(str)
    u = u[u.group.astype(str).str.len() > 0]
    if "sector" not in u:
        u["sector"] = "Other"
    u["sector"] = u.sector.fillna("Other").astype(str)
    return u.drop_duplicates("symbol")[["symbol", "name", "group", "sector"]]


def download(tickers):
    out = {}
    for a in range(0, len(tickers), 200):
        ch = tickers[a:a + 200]
        for k in range(3):
            try:
                d = yf.download(ch, period="3y", interval="1d", auto_adjust=True, progress=False, group_by="column", threads=True)
                for t in ch:
                    try:
                        out[t] = pd.DataFrame({"c": d["Close"][t], "v": d["Volume"][t]}).dropna()
                    except Exception:  # noqa: BLE001
                        pass
                break
            except Exception as e:  # noqa: BLE001
                print("retry", a, e, flush=True); time.sleep(15)
        print(a + len(ch), "downloaded", flush=True)
    return out


def main(mkt):
    cf = CFG[mkt]; u = universe(mkt)
    tick = {s: (s.replace("/", "-").replace(".", "-") if mkt == "US" else s) + cf["suf"] for s in u.symbol}
    data = download(list(tick.values()) + [cf["bench"]])
    B = data.get(cf["bench"]); B = B.c if B is not None else None
    C = pd.DataFrame({s: data[t].c for s, t in tick.items() if t in data and len(data[t]) > 160})
    V = pd.DataFrame({s: data[t].v for s, t in tick.items() if t in data and len(data[t]) > 160}).reindex(C.index)
    C = drop_partial(C.sort_index(), {"NSE": "NSE", "US": "US", "ASX": "ASX"}[mkt]); V = V.reindex(C.index)
    B = B.reindex(C.index).ffill()
    liq = ((C * V).rolling(60, min_periods=40).median() >= cf["minval"]) & (C >= cf["minpx"])
    rpi = lambda k: 100 * (C / C.shift(k)).div(B / B.shift(k), axis=0)
    r2, r3, r6 = rpi(10), rpi(63), rpi(126); w = (r2 + r3 + r6) / 3
    e9 = C.ewm(span=9, adjust=False).mean(); e21 = C.ewm(span=21, adjust=False).mean(); s150 = C.rolling(150).mean()
    st2 = (C > s150) & (s150 > s150.shift(20))
    hi52 = C.rolling(250, min_periods=120).max()
    tr = (w > 100) & (e9 > e21) & st2 & (C >= 0.75 * hi52) & liq
    grp = dict(zip(u.symbol, u.group)); nm = dict(zip(u.symbol, u.name))
    L = liq.iloc[-1]; syms = [s for s in C.columns if L.get(s, False)]
    def share(wn, at=-1):
        x = tr.astype(float).rolling(wn).mean().iloc[at]; return x
    s1w, s1m, s1q, s1m_prev = share(5), share(21), share(63), share(21, -22)
    groups = {}
    for s in syms:
        groups.setdefault(grp[s], []).append(s)
    rows = []
    for g, ss in groups.items():
        if len(ss) < 3:
            continue
        mem = []
        for s in ss:
            mem.append(dict(symbol=s, name=str(nm.get(s, s))[:60], close=round(float(C[s].iloc[-1]), 2), wrpi=round(float(w[s].iloc[-1]), 1),
                            rpi2w=round(float(r2[s].iloc[-1]), 1), rpi3m=round(float(r3[s].iloc[-1]), 1), rpi6m=round(float(r6[s].iloc[-1]), 1),
                            d1w=int(tr[s].iloc[-5:].sum()), d1m=int(tr[s].iloc[-21:].sum()), trending=bool(tr[s].iloc[-1]), stage2=bool(st2[s].iloc[-1]),
                            from_high=round(float((C[s].iloc[-1] / hi52[s].iloc[-1] - 1) * 100), 1)))
        mem.sort(key=lambda m: (-m["d1m"], -(m["wrpi"] if np.isfinite(m["wrpi"]) else 0)))
        p = lambda ser: round(float(np.nanmean([ser[s] for s in ss])) * 100, 1)
        rows.append(dict(group=g, n=len(ss), p1w=p(s1w), p1m=p(s1m), p1q=p(s1q), p1m_prev=p(s1m_prev),
                         trending_now=int(sum(m["trending"] for m in mem)), members=mem))
    # charts: equal-weight group index (current liquid members, daily returns clipped at +-30%) vs the market, and 1-month Pulse history
    N = 250; ret = C.pct_change().clip(-0.3, 0.3); p21 = tr.astype(float).rolling(21).mean()
    dates = [str(d.date()) for d in C.index[-N:]]; bm = (B.iloc[-N:] / B.iloc[-N] * 100).round(2).tolist()
    charts = dict(t=dates, market=bm, groups={})
    for g, ss in groups.items():
        if len(ss) < 3:
            continue
        gi = (1 + ret[ss].iloc[-N:].mean(axis=1).fillna(0)).cumprod(); gi = gi / gi.iloc[0] * 100
        pp = (p21[ss].iloc[-N:].mean(axis=1) * 100)
        charts["groups"][g] = dict(idx=[round(float(v), 2) for v in gi], pulse=[None if np.isnan(v) else round(float(v), 1) for v in pp])
    secof = dict(zip(u.symbol, u.sector))
    for r in rows:
        ss = [m["symbol"] for m in r["members"]]
        r["sector"] = pd.Series([secof.get(x, "Other") for x in ss]).mode().iloc[0]
    # sector aggregates (all liquid members of the sector's groups)
    r3 = (C / C.shift(63)).div(B / B.shift(63), axis=0) - 1; r1 = (C / C.shift(21)).div(B / B.shift(21), axis=0) - 1
    sectors = []
    for sec in sorted({r["sector"] for r in rows}):
        ss = [m["symbol"] for r in rows if r["sector"] == sec for m in r["members"]]
        if len(ss) < 5:
            continue
        p = lambda ser: round(float(np.nanmean([ser[x] for x in ss])) * 100, 1)
        gi = (1 + ret[ss].iloc[-N:].mean(axis=1).fillna(0)).cumprod(); gi = gi / gi.iloc[0] * 100
        charts.setdefault("sectors", {})[sec] = dict(idx=[round(float(v), 2) for v in gi],
                                                     pulse=[None if np.isnan(v) else round(float(v), 1) for v in (p21[ss].iloc[-N:].mean(axis=1) * 100)])
        sectors.append(dict(sector=sec, n=len(ss), groups=sum(r["sector"] == sec for r in rows), p1w=p(s1w), p1m=p(s1m), p1q=p(s1q), p1m_prev=p(s1m_prev),
                            rs1m=round(float(np.nanmean(r1[ss].iloc[-1])) * 100, 1), rs3m=round(float(np.nanmean(r3[ss].iloc[-1])) * 100, 1),
                            trending_now=int(sum(bool(tr[x].iloc[-1]) for x in ss))))
    sectors.sort(key=lambda r: -r["p1m"])
    json.dump(charts, open(cf["out"] + "group_pulse_charts.json", "w"), separators=(",", ":"))
    s200 = C.rolling(200).mean(); s50 = C.rolling(50).mean(); bs = B.rolling(150).mean()
    market = dict(index=cf["bench"], close=round(float(B.iloc[-1]), 2), up=bool(B.iloc[-1] > bs.iloc[-1] and bs.iloc[-1] > bs.iloc[-21]),
                  r1m=round(float(B.iloc[-1] / B.iloc[-22] - 1) * 100, 1), r3m=round(float(B.iloc[-1] / B.iloc[-64] - 1) * 100, 1),
                  from_high=round(float(B.iloc[-1] / B.iloc[-250:].max() - 1) * 100, 1),
                  above200=round(float((C.iloc[-1] > s200.iloc[-1])[syms].mean()) * 100, 1), above50=round(float((C.iloc[-1] > s50.iloc[-1])[syms].mean()) * 100, 1),
                  p1w=round(float(np.nanmean([s1w[x] for x in syms])) * 100, 1), p1m=round(float(np.nanmean([s1m[x] for x in syms])) * 100, 1),
                  p1q=round(float(np.nanmean([s1q[x] for x in syms])) * 100, 1),
                  above200_1m_ago=round(float((C.iloc[-22] > s200.iloc[-22])[syms].mean()) * 100, 1))
    rows.sort(key=lambda r: -r["p1m"])
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    stock = {m["symbol"]: [r["group"], r["p1m"], r["rank"], len(rows)] for r in rows for m in r["members"]}
    mkt_share = round(float(np.nanmean([s1m[s] for s in syms])) * 100, 1)
    out = dict(generated=datetime.now(timezone.utc).isoformat(timespec="minutes"), asof=str(C.index[-1].date()), market=mkt,
               groups_n=len(rows), stocks_n=len(syms), market_pulse_1m=mkt_share,
               rule="Trending day = weighted RPI > 100 (mean of 2-week, 3-month and 6-month performance vs the market index x 100), "
                    "EMA 9 > EMA 21, a Stage 2 uptrend (above a rising 150-day average) and within 25% of the 52-week high. Pulse = share of a group's liquid stocks' days that "
                    "were trending over the last 1 week / 1 month / 1 quarter. Groups with 3+ liquid stocks.",
               backtest="NSE 2017-26: the 10% of groups with the highest 1-month Pulse beat the lowest 10% by +2.9% over the next 3 months "
                        "(+2.2% in 2017-21, +3.6% in 2022-26), better than plain group return (+1.8%); 1-week Pulse +1.2% over the next month. "
                        "Trending stocks in top-Pulse groups beat the average stock by +1.4% over 3 months. As a hard filter on ATH breakouts "
                        "it did not raise returns - use it as a tiebreaker / tailwind. US and ASX: not separately tested.",
               rows=rows, sectors=sectors, mstats=market, stock=stock)
    os.makedirs(cf["out"], exist_ok=True); json.dump(out, open(cf["out"] + "group_pulse.json", "w"), separators=(",", ":"))
    # weekly closes (last ~60 weeks) of every liquid stock, for the stock panel's mini chart
    # + weekly RSI(14, Wilder) on the full ~3-year weekly series, for the range-shift panel (40/60 bands)
    Wf = C[syms].resample("W-FRI").last()
    dW = Wf.diff(); au = dW.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean(); ad = (-dW.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    RW = (100 - 100 / (1 + au / ad.replace(0, np.nan))).iloc[-62:]
    W = Wf.iloc[-62:]
    if W.index[-1] > C.index[-1]:
        W.index = list(W.index[:-1]) + [C.index[-1]]
    json.dump({"t": [str(d.date()) for d in W.index],
               "s": {s: [None if pd.isna(v) else float(f"{v:.4g}") for v in W[s]] for s in syms},
               "r": {s: [None if pd.isna(v) else round(float(v), 1) for v in RW[s]] for s in syms}},
              open(cf["out"] + "stock_weekly.json", "w"), separators=(",", ":"))
    print(mkt, "groups", len(rows), "stocks", len(syms), "market pulse 1m", mkt_share, "top", [(r["group"], r["p1m"]) for r in rows[:5]])


if __name__ == "__main__":
    for m in (sys.argv[1:] or ["NSE", "US", "ASX"]):
        try:
            main(m)
        except Exception as e:  # noqa: BLE001
            print("FAILED", m, e)
