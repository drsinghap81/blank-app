"""Top Bottom on MCX commodities that have MINI / MICRO contracts (24 Nov 2026, Amritpal: "backtest commodities that have mini or
micro futures so we can trade those under this margin").
MCX history isn't reachable from the runners, so each price is an MCX-equivalent rupee series from the COMEX / NYMEX front month
(Yahoo) x USD/INR (levels differ from MCX by import duty; daily swings - what Top Bottom trades - track closely):
  GOLD   GC=F  Rs/10 g   GOLDM 100 g, GOLDGUINEA 8 g, GOLDPETAL 1 g
  SILVER SI=F  Rs/kg     SILVERM 5 kg, SILVERMIC 1 kg
  CRUDE  CL=F  Rs/bbl    CRUDEOILM 10 bbl            (Apr 2020 negative prints dropped)
  NATGAS NG=F  Rs/mmBtu  NATGASMINI 250 mmBtu        (front-month rolls make gaps - caveat)
  COPPER HG=F  Rs/kg     COPPER 2,500 kg (no mini on MCX now - shown for reference)
  ALUMIN ALI=F Rs/kg     ALUMINI 1 t (Yahoo's aluminium history is short/patchy)
Engine tools/topbottom_backtest.run_live, buffer 0.05%, event exits off, cost 0.06% a round trip. Versions: both sides / buy only /
buy only while price > 200-day. Rules: INDEX 1/2/2 (Bank Nifty bot) and STOCK 1.5/3/3. Returns on full contract value, compounded per
trade. Newest first, bull/bear, ex-Covid. Also an equal-weight monthly basket of the minis (+ Bank Nifty) for the smooth-curve question."""
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, ".."))
import topbottom_backtest as tbb  # noqa: E402

SPEC = {  # name: (yahoo, multiplier to Rs unit, unit, [(contract, units per lot)])
    "GOLD": ("GC=F", 10 / 31.1035, "Rs/10g", [("GOLDM", 10), ("GOLDGUINEA", 0.8), ("GOLDPETAL", 0.1)]),
    "SILVER": ("SI=F", 32.1507, "Rs/kg", [("SILVERM", 5), ("SILVERMIC", 1)]),
    "CRUDE": ("CL=F", 1.0, "Rs/bbl", [("CRUDEOILM", 10)]),
    "NATGAS": ("NG=F", 1.0, "Rs/mmBtu", [("NATGASMINI", 250)]),
    "COPPER": ("HG=F", 2.20462, "Rs/kg", [("COPPER", 2500)]),
    "ALUMIN": ("ALI=F", 0.001, "Rs/kg", [("ALUMINI", 1000)]),
}
RULES = {"INDEX 1/2/2": dict(day_sl_pct=1.0, max_sl_pct=2.0, be_pct=2.0, gap_pct=1.0), "STOCK 1.5/3/3": dict(day_sl_pct=1.5, max_sl_pct=3.0, be_pct=3.0, gap_pct=1.5)}
COST = 0.0006


def yh(t):
    d = yf.download(t, start="2009-01-01", progress=False, auto_adjust=False)
    d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]
    d.index = pd.to_datetime(d.index).tz_localize(None); return d


def stats(t, end):
    if t.empty:
        return None
    r = t.Pct / 100 - COST; g, b = r[r > 0].sum(), -r[r < 0].sum()
    eq = (1 + r.values).cumprod(); dd = (eq / np.maximum.accumulate(eq) - 1).min()
    d0, d1 = pd.Timestamp(t.EntryDate.min()), pd.Timestamp(t.ExitDate.max()); yrs = max(0.5, (d1 - d0).days / 365.25)
    w = lambda y: (np.prod(1 + r[pd.to_datetime(t.ExitDate) > end - pd.DateOffset(years=y)]) - 1) * 100
    exc = r[~((pd.to_datetime(t.EntryDate) >= "2020-02-15") & (pd.to_datetime(t.EntryDate) < "2021-01-01"))]
    return dict(n=len(t), win=(r > 0).mean() * 100, pf=g / b if b else 9, cagr=(eq[-1] ** (1 / yrs) - 1) * 100, dd=dd * 100,
                y1=w(1), y2=w(2), y3=w(3), y5=w(5), exc=((np.prod(1 + exc)) ** (1 / yrs) - 1) * 100)


def main():
    fx = yh("USDINR=X")["Close"]; months = {}
    for name, (tk, mult, unit, lots) in SPEC.items():
        try:
            s = yh(tk)
        except Exception as ex:  # noqa: BLE001
            print(f"R| {name} no data {ex}", flush=True); continue
        k = fx.reindex(s.index).ffill() * mult
        df = pd.DataFrame({c: s[c] * k for c in ("Open", "High", "Low", "Close")}).dropna()
        df = df[(df.High >= df.Low) & (df.Low > 0) & (df.index >= "2010-01-01")]
        if len(df) < 500:
            print(f"R| {name} too little data ({len(df)} days)", flush=True); continue
        end = df.index[-1]; px = df.Close.iloc[-1]; above = (df.Close > df.Close.rolling(200).mean()).to_numpy()
        lotv = " / ".join(f"{c} ~Rs {px * u / 1e5:.2f} L" for c, u in lots)
        vol = df.Close.pct_change().std() * np.sqrt(252) * 100
        print(f"R| == {name} {unit} {df.index[0].date()} -> {end.date()} last {px:,.0f} | yearly vol {vol:.0f}% | contract value: {lotv}", flush=True)
        for rl, kw in RULES.items():
            for lab, extra in (("both sides", {}), ("buy only", dict(long_only=True)), ("buy only >200d", dict(short_ok=None))):
                p = tbb.Params(buffer_pct=0.05, buffer_pts=0, event_exit=False, **kw, **({k_: v for k_, v in extra.items() if k_ != "short_ok"}))
                if lab == "buy only >200d":
                    p = tbb.Params(buffer_pct=0.05, buffer_pts=0, event_exit=False, long_only=True, **kw)
                t = tbb.run_live(df[["Open", "High", "Low", "Close"]], p)
                t = t[~t.Open] if "Open" in t else t
                if lab == "buy only >200d" and len(t):
                    idx = df.index.get_indexer(pd.to_datetime(t.EntryDate)); t = t[[bool(above[max(0, i - 1)]) for i in idx]]
                S = stats(t, end)
                if S:
                    print(f"R| {name:6s} {rl:13s} {lab:15s} | n {S['n']:4d} win {S['win']:3.0f}% PF {S['pf']:.2f} | CAGR {S['cagr']:+6.1f}% DD {S['dd']:+6.1f}% | "
                          f"1y {S['y1']:+6.1f} 2y {S['y2']:+6.1f} 3y {S['y3']:+6.1f} 5y {S['y5']:+6.1f} | exCovid {S['exc']:+5.1f}%/yr", flush=True)
                if rl == "INDEX 1/2/2" and lab in ("both sides", "buy only"):
                    r = (t.Pct / 100 - COST); r.index = pd.to_datetime(t.ExitDate)
                    months[(name, lab)] = r.groupby(r.index.to_period("M")).apply(lambda x: np.prod(1 + x) - 1)
                    if lab == "both sides":
                        L = t[t.Side == "BUY"].Pct / 100 - COST; Sh = t[t.Side == "SELL"].Pct / 100 - COST
                        bull = [bool(above[max(0, i - 1)]) for i in df.index.get_indexer(pd.to_datetime(t.EntryDate))]
                        rr = t.Pct / 100 - COST; bu, be = rr[np.array(bull)], rr[~np.array(bull)]
                        pf = lambda x: x[x > 0].sum() / max(1e-9, -x[x < 0].sum())
                        print(f"R| {name:6s} split | longs PF {pf(L):.2f} ({len(L)}) shorts PF {pf(Sh):.2f} ({len(Sh)}) | bull PF {pf(bu):.2f} bear PF {pf(be):.2f}", flush=True)
                        yy = r.groupby(r.index.year).apply(lambda x: (np.prod(1 + x) - 1) * 100)
                        print(f"R| {name:6s} years (both, index rules) " + " ".join(f"{y}:{v:+.0f}" for y, v in yy[::-1].items()), flush=True)
    bn = pd.read_csv("data/futures/BANKNIFTY.csv", parse_dates=["Date"]).set_index("Date")[["Open", "High", "Low", "Close"]]
    t = tbb.run_live(bn[bn.index >= "2010-01-01"], tbb.Params(buffer_pct=0.05, buffer_pts=0, event_exit=False)); t = t[~t.Open]
    r = t.Pct / 100 - 0.0005; r.index = pd.to_datetime(t.ExitDate); months[("BANKNIFTY", "both sides")] = r.groupby(r.index.to_period("M")).apply(lambda x: np.prod(1 + x) - 1)
    def book(keys, lab):
        M = pd.DataFrame({k: months[k] for k in keys if k in months}).sort_index()
        M = M[M.index >= pd.Period("2011-01", "M")].fillna(0.0); m = M.mean(axis=1); eq = (1 + m).cumprod()
        yrs = len(m) / 12; dd = (eq / eq.cummax() - 1).min()
        w = lambda y: (np.prod(1 + m.iloc[-12 * y:]) - 1) * 100
        corr = M.corr().where(~np.eye(len(M.columns), dtype=bool)).stack().median() if M.shape[1] > 1 else np.nan
        print(f"R| BOOK {lab} ({M.shape[1]} sleeves) | CAGR {(eq.iloc[-1] ** (1 / yrs) - 1) * 100:+.1f}% | monthly DD {dd * 100:+.1f}% | up months {(m > 0).mean() * 100:.0f}% | "
              f"1y {w(1):+.1f} 2y {w(2):+.1f} 3y {w(3):+.1f} 5y {w(5):+.1f} | median corr {corr:.2f}", flush=True)
    book([("BANKNIFTY", "both sides")], "Bank Nifty alone")
    book([("GOLD", "buy only"), ("SILVER", "buy only"), ("CRUDE", "both sides"), ("NATGAS", "both sides")], "4 minis (gold/silver buy, crude/natgas both)")
    book([("BANKNIFTY", "both sides"), ("GOLD", "buy only"), ("SILVER", "buy only"), ("CRUDE", "both sides"), ("NATGAS", "both sides")], "BN + 4 minis")
    book([("BANKNIFTY", "both sides"), ("GOLD", "buy only"), ("SILVER", "buy only")], "BN + gold + silver (buy only)")


if __name__ == "__main__":
    main()
