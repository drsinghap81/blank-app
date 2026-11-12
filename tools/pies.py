"""Trading 212 pies (Australia, US-listed ETFs) from the app's tested rules (11 Nov 2026). Month-end decisions, trade the
first session of the new month. Writes data/scan/us/pies.json; the app shows this month's targets and the server alerts on
a change. Tests (scratchpad pies/, 2008-Oct 2026, 0.15% FX per unit traded, price-only index series):
  rotation : hold the best ONE of S&P 500 (VOO) / Nasdaq 100 (QQQ) / S&P MidCap (MDY) / Russell 2000 (IWM) by 3-month
             return; cash (SGOV) if none is up.                          11.4%/yr, worst -15.2% (S&P 500 9.1%, -47.5%)
  sectors  : 3 slots for sector/industry ETFs whose month closed at a new high after a 12+ month base, above a rising
             30-week SMA, 6-month RS vs the S&P 500 > 0 (strongest RS first); each held until a month-end close below its
             30-week SMA; empty slots in VOO while the S&P is above its 10-month average, else SGOV.   9.9%/yr, worst -21.9%"""
import json
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

OUT = "data/scan/us/pies.json"
IDX = {"^GSPC": "VOO", "^NDX": "QQQ", "MDY": "MDY", "^RUT": "IWM"}
NAME = {"VOO": "S&P 500", "QQQ": "Nasdaq 100", "MDY": "S&P MidCap 400", "IWM": "Russell 2000", "SGOV": "Cash (0-3 month T-bills)"}
ETF = ["GDX", "IAI", "IGV", "IHI", "ITA", "IYT", "JETS", "KBE", "KIE", "KRE", "MDY", "PAVE", "PEJ", "PPH", "RSP", "SMH", "XBI",
       "XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY", "XME", "XOP", "XRT"]
ETF_NM = {"GDX": "Gold miners", "IAI": "Brokers & exchanges", "IGV": "Software", "IHI": "Medical devices", "ITA": "Aerospace & defence",
          "IYT": "Transport", "JETS": "Airlines", "KBE": "Banks", "KIE": "Insurance", "KRE": "Regional banks", "MDY": "S&P MidCap 400",
          "PAVE": "Infrastructure", "PEJ": "Leisure & entertainment", "PPH": "Pharma", "RSP": "S&P 500 equal weight", "SMH": "Semiconductors",
          "XBI": "Biotech", "XLB": "Materials", "XLC": "Communication", "XLE": "Energy", "XLF": "Financials", "XLI": "Industrials",
          "XLK": "Technology", "XLP": "Consumer staples", "XLRE": "Real estate", "XLU": "Utilities", "XLV": "Health care",
          "XLY": "Consumer discretionary", "XME": "Metals & mining", "XOP": "Oil & gas", "XRT": "Retail"}
SLOTS, BASE = 3, 12
LIVE_TICK = ["VOO", "QQQ", "IWM", "SGOV"]          # 12 Nov 2026: real ETF prices (total return) for the live tracker
FX = "AUDUSD=X"
# UK (Trading 212 ISA) can't buy US-listed ETFs: UK-listed UCITS twins of the same indices. Sector pie limited to the sectors
# and industries with a UCITS twin (retest 11 Nov 2026: 9.8%/yr, -20.0%; 70/30 with the rotation 10.8%, -16.0%).
ETF_UK = ["XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY", "SMH", "XBI", "GDX"]
UCITS = {"VOO": ("VUAG", "Vanguard S&P 500 UCITS (Acc)"), "QQQ": ("EQQQ", "Invesco EQQQ Nasdaq-100 UCITS"),
         "MDY": ("SPY4", "SPDR S&P 400 US Mid Cap UCITS"), "IWM": ("R2US", "SPDR Russell 2000 US Small Cap UCITS"),
         "SGOV": ("CSH2", "Amundi Smart Overnight Return GBP (cash)"),
         "XLB": ("SXLB", "SPDR US Materials Select Sector UCITS"), "XLC": ("SXLC", "SPDR US Communication Services Select Sector UCITS"),
         "XLE": ("SXLE", "SPDR US Energy Select Sector UCITS"), "XLF": ("SXLF", "SPDR US Financials Select Sector UCITS"),
         "XLI": ("SXLI", "SPDR US Industrials Select Sector UCITS"), "XLK": ("SXLK", "SPDR US Technology Select Sector UCITS"),
         "XLP": ("SXLP", "SPDR US Consumer Staples Select Sector UCITS"), "XLU": ("SXLU", "SPDR US Utilities Select Sector UCITS"),
         "XLV": ("SXLV", "SPDR US Health Care Select Sector UCITS"), "XLY": ("SXLY", "SPDR US Consumer Discretionary Select Sector UCITS"),
         "SMH": ("SMGB", "VanEck Semiconductor UCITS"), "XBI": ("BTEK", "iShares Nasdaq US Biotechnology UCITS (close twin)"),
         "GDX": ("GDGB", "VanEck Gold Miners UCITS")}
COST = 0.0015


def load():
    import yfinance as yf
    tick = sorted(set(list(IDX) + ETF + list(LIVE_TICK) + [FX]))
    d = yf.download(tick, period="max", interval="1d", auto_adjust=True, progress=False, group_by="column", threads=True)
    px = d["Close"].dropna(how="all")
    return px[px.index >= "2004-01-01"]


def decide(px, etf=None):
    ETF_ = etf or ETF
    """Month-end targets for both pies, from 2007 to the last COMPLETED month (and a provisional view of this month)."""
    M = px.resample("ME").last(); lastday = px.index[-1]
    complete = pd.offsets.BMonthEnd().rollforward(lastday).normalize() == lastday.normalize()   # data reaches the month's last session
    done = M if complete else M.iloc[:-1]
    sma = px.rolling(150, min_periods=150).mean(); up = sma > sma.shift(20)
    Ms = sma.resample("ME").last(); Mu = up.resample("ME").last()

    def run(M_):
        m3 = M_[list(IDX)].pct_change(3); rs6 = M_[ETF_].pct_change(6).sub(M_["^GSPC"].pct_change(6), axis=0)
        hi = M_[ETF_].cummax().shift(1); ma10 = M_["^GSPC"].rolling(10).mean()
        last = pd.Series(np.nan, index=ETF_); hold = []; rot, sec = {}, {}
        for k, d in enumerate(M_.index):
            age = k - last
            nh = M_[ETF_].loc[d] >= M_[ETF_].iloc[:k + 1].max(); last[nh.fillna(False)] = k
            s = m3.loc[d].dropna().sort_values(ascending=False)
            rot[d] = {IDX[s.index[0]]: 1.0} if len(s) and s.iloc[0] > 0 else {"SGOV": 1.0}
            hold = [e for e in hold if pd.notna(M_.loc[d, e]) and M_.loc[d, e] > Ms.loc[d, e]]
            cand = [e for e in ETF_ if e not in hold and pd.notna(hi.loc[d, e]) and M_.loc[d, e] > hi.loc[d, e] and age[e] >= BASE
                    and bool(Mu.loc[d, e]) and M_.loc[d, e] > Ms.loc[d, e] and pd.notna(rs6.loc[d, e]) and rs6.loc[d, e] > 0]
            for e in sorted(cand, key=lambda e: -rs6.loc[d, e])[: max(0, SLOTS - len(hold))]:
                hold.append(e)
            w = {e: round(1 / SLOTS, 4) for e in hold}; rest = round(1 - len(hold) / SLOTS, 4)
            if rest > 0:
                core = "VOO" if pd.notna(ma10.loc[d]) and M_.loc[d, "^GSPC"] > ma10.loc[d] else "SGOV"
                w[core] = w.get(core, 0) + rest
            sec[d] = w
        return rot, sec

    rot, sec = run(done)
    prov = run(M) if len(M) and M.index[-1] not in done.index else (rot, sec)
    return M, done, rot, sec, prov


def perf(M, W, start):
    """Pie return month by month from `start` (live record), using ETF/index prices (cash ~4%/yr now)."""
    R = M.pct_change().shift(-1); out = []; prev = {}
    tick = {**{v: k for k, v in IDX.items()}, **{e: e for e in ETF}}
    for d, w in W.items():
        if d < start or d == list(W)[-1]:
            prev = w; continue
        turn = sum(abs(w.get(k, 0) - prev.get(k, 0)) for k in set(w) | set(prev))
        r = sum(v * (R.loc[d, tick[k]] if k in tick and pd.notna(R.loc[d, tick[k]]) else 0.0033) for k, v in w.items()) - turn * COST
        out.append([str((d + pd.offsets.MonthEnd(1)).date()), round(r * 100, 2)]); prev = w
    return out


def nav(px, W, start):
    """12 Nov 2026: daily value of 1 unit put in at `start`, plus AUD/USD, for the app's tracker. Each month-end target is
    traded at that month-end close; between rebalances the slices drift with their ETF prices (auto-adjusted, dividends
    in). A ticker without a price earns cash (~4%/yr)."""
    days = px.index[px.index > start]
    dec = sorted(W)
    if not len(days) or not dec:
        return None
    last = lambda col, t: (px[col].loc[:t].dropna().iloc[-1] if col in px.columns and len(px[col].loc[:t].dropna()) else None)  # noqa: E731
    v, prev, cur, out = 1.0, {}, None, []
    for t in days:
        m_end = max([d for d in dec if d < t] or [None])
        if m_end is None:
            continue
        if cur is None or cur[0] != m_end:
            if cur is not None:
                v = val
            w = W[m_end]; v *= 1 - sum(abs(w.get(k, 0) - prev.get(k, 0)) for k in set(w) | set(prev)) * COST; prev = w
            cur = (m_end, w, {k: last(k, m_end) for k in w})
        _, w, p0 = cur
        val = v * sum(x * ((last(k, t) / p0[k]) if p0.get(k) and last(k, t) else 1 + 0.04 * (t - cur[0]).days / 365) for k, x in w.items())
        fx = last(FX, t)
        out.append([str(t.date()), round(float(val), 5), round(float(fx), 5) if fx else None])
    return out


def main():
    pxa = load()                                      # all series (decisions use the same columns and calendar as before)
    px = pxa[[c for c in sorted(set(list(IDX) + ETF)) if c in pxa.columns]].dropna(how="all")
    M, done, rot, sec, (prot, psec) = decide(px)
    last = done.index[-1]; prev = done.index[-2]
    start = pd.Timestamp("2026-10-31")
    name = lambda k: NAME.get(k) or ETF_NM.get(k) or k  # noqa: E731

    def card(key, title, rule, test, W, P):
        now, before = W[last], W[prev]
        return dict(key=key, title=title, rule=rule, test=test, decided=str(last.date()),
                    hold=[dict(ticker=k, name=name(k), pct=round(v * 100, 1)) for k, v in sorted(now.items(), key=lambda x: -x[1])],
                    changed=now != before, before=[dict(ticker=k, pct=round(v * 100, 1)) for k, v in before.items()],
                    provisional=[dict(ticker=k, pct=round(v * 100, 1)) for k, v in P[max(P)].items()] if P[max(P)] != now else None,
                    record=perf(M, W, start), nav=nav(pxa.loc[pxa.index.isin(px.index)], W, start))
    _, done_u, rot_u, sec_u, (prot_u, psec_u) = decide(px, ETF_UK)

    def uk(card_):
        tr = lambda L: [dict(x, ticker=UCITS.get(x["ticker"], (x["ticker"],))[0], us=x["ticker"], name=UCITS.get(x["ticker"], (None, x.get("name")))[1] or x.get("name")) for x in (L or [])]  # noqa: E731
        return dict(card_, hold=tr(card_["hold"]), before=tr(card_["before"]), provisional=tr(card_["provisional"]) if card_["provisional"] else None)
    uk_pies = [uk(card("rotation", "US index rotation", "Each month-end: hold the best one of the S&P 500 / Nasdaq 100 / S&P MidCap 400 / Russell 2000 UCITS ETFs by 3-month return; GBP cash ETF if none is up.",
                       "2008-26 (US$, same signals): 11.1%/yr, worst fall -15.5%. In GBP the returns also move with GBP/USD.", rot_u, prot_u)),
               uk(card("sectors", "US sector breakouts", f"Up to {SLOTS} of the 10 US sectors + semiconductors, biotech and gold miners (the ones with UCITS twins) with a monthly cup breakout ({BASE}+ month base), rising 30-week SMA and 6-month RS > 0; each kept until a month-end close below its 30-week SMA. Empty slots: the S&P 500 while it is above its 10-month average, else the cash ETF.",
                       "2008-26 (US$): 9.8%/yr, worst fall -20.0%; 70% rotation + 30% this pie: 10.8%, -16.0%.", sec_u, psec_u))]
    out = dict(generated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), asof=str(px.index[-1].date()), broker="Trading 212 (Australia)",
               note="Rebalance on the first trading day after the month-end decision. FX fee 0.15% each way on Trading 212 AU. "
                    "Pies have no stop-loss: the month-end check is the exit.",
               pies=[card("rotation", "US index rotation", "Each month-end: hold the best one of VOO / QQQ / MDY / IWM by 3-month return; SGOV (cash) if none is up.",
                          "2008-26: 11.4%/yr, worst fall -15.2% (S&P 500: 9.1%, -47.5%). Price-only series; ETFs add dividends.", rot, prot),
                     card("sectors", "US sector breakouts", f"Up to {SLOTS} sector/industry ETFs with a monthly cup breakout ({BASE}+ month base), rising 30-week SMA and 6-month RS > 0; each kept until a month-end close below its 30-week SMA. Empty slots: VOO while the S&P 500 is above its 10-month average, else SGOV.",
                          "2008-26: 9.9%/yr, worst fall -21.9% (S&P 500: 9.1%, -47.5%).", sec, psec)],
               uk=dict(broker="Trading 212 UK (ISA)", note="UK-listed UCITS twins of the same indices (US-listed ETFs can't be bought from a UK account). Search each fund by name in Trading 212 to confirm the line; GBP lines avoid the FX fee on purchase. Rebalance on the first trading day after the month-end decision.", pies=uk_pies))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w"), indent=0)
    print("pies:", [(p["key"], p["hold"], p["changed"]) for p in out["pies"]])


if __name__ == "__main__":
    main()
