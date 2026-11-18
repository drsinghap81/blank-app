"""Option-premium signal -> stock delivery test (18 Nov 2026, Amritpal's question).

When a stock's ATM CALL premium gives a bullish signal on its daily chart, does buying the STOCK (delivery) from the next
open beat (a) a random day of the same stocks and (b) the same signal on the stock's own chart? PUT signals are measured
too (a bullish put = falling stock: does the stock then fall?).

Data: NSE F&O bhavcopies (branches optatm-CE-*/optatm-PE-*: strikes +-10% of the near future, nearest 3 expiries), current
F&O list (survivorship bias in favour), 2020 - Oct 2026; stock prices from Yahoo (adjusted).
Contract on day d: nearest monthly expiry with >= 10 days left, strike nearest the near future's close; its own daily
history (close if traded, else settle). Signals on that contract's chart at d (same rules as the app):
  921   EMA 9 crossed above EMA 21 in the last 2 bars, close above EMA 21
  hi20  close above the highest close of the previous 20 bars
  tb    close crosses above the last top of the closing line
  cup   cup close: close above the highest high of the window, that high 20+ bars old, cup 15%+ deep
  rsi60 RSI(14) crosses above 60 today
  any   any of 921 / hi20 / tb / cup;   any+rsi = any of them on a day RSI(14) is above 60;  any&rsi60 = with RSI crossing 60
Trade: buy at the next day's open, sell at the close 5 / 10 / 20 / 60 trading days later. One event per stock per 10 days.
Output: data/research/opt_signal_delivery.json"""
import glob
import json
import math
import os
import subprocess

import numpy as np
import pandas as pd
import yfinance as yf

H = (5, 10, 20, 60)


def load():
    os.makedirs("oatm", exist_ok=True)
    heads = subprocess.run(["git", "ls-remote", "--heads", "origin"], capture_output=True, text=True).stdout.split()
    for b in [h.replace("refs/heads/", "") for h in heads if "refs/heads/optatm-" in h]:
        subprocess.run(["git", "fetch", "-q", "--depth", "1", "origin", b], check=True)
        for f in subprocess.run(["git", "ls-tree", "-r", "--name-only", "FETCH_HEAD"], capture_output=True, text=True).stdout.split():
            if f.endswith(".csv.gz"):
                open(os.path.join("oatm", os.path.basename(f)), "wb").write(subprocess.run(["git", "show", f"FETCH_HEAD:{f}"], capture_output=True).stdout)
    return pd.concat([pd.read_csv(f, parse_dates=["Date", "EXPIRY"]) for f in sorted(glob.glob("oatm/*.csv.gz"))], ignore_index=True)


def ema(v, n):
    k = 2 / (n + 1); e = v[0]; out = np.empty(len(v))
    for i, x in enumerate(v):
        e = x * k + e * (1 - k); out[i] = e
    return out


def rsi(c, n=14):
    c = np.asarray(c, float); o = np.full(len(c), np.nan)
    if len(c) <= n:
        return o
    d = np.diff(c); g = np.maximum(d, 0); l_ = np.maximum(-d, 0); ag, al = g[:n].mean(), l_[:n].mean()
    o[n] = 100 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(n + 1, len(c)):
        ag = (ag * (n - 1) + g[i - 1]) / n; al = (al * (n - 1) + l_[i - 1]) / n
        o[i] = 100 if al == 0 else 100 - 100 / (1 + ag / al)
    return o


def sigs(h, c):
    """signals on the LAST bar of (h, c)."""
    n = len(c); s = {}
    if n >= 25:
        e9, e21 = ema(c, 9), ema(c, 21)
        s["921"] = any(e9[i] > e21[i] and e9[i - 1] <= e21[i - 1] for i in (n - 1, n - 2)) and c[-1] > e21[-1]
        s["hi20"] = c[-1] > c[-21:-1].max()
    else:
        s["921"] = s["hi20"] = False
    top = None
    for i in range(1, n - 2):
        if c[i] > c[i - 1] and c[i] >= c[i + 1]:
            top = c[i]
    s["tb"] = top is not None and n >= 3 and c[-1] > top >= c[-2]
    s["cup"] = False
    if n >= 23:
        lo = max(0, n - 1 - 250); a = lo + int(np.argmax(h[lo:n - 1])); rim = h[a]
        if c[-1] > rim and n - 1 - a >= 20:
            seg = c[a + 1:n - 1]
            s["cup"] = len(seg) > 0 and seg.min() / rim - 1 <= -0.15
    r = rsi(c)
    s["rsi60"] = n > 15 and r[-1] > 60 and r[-2] <= 60
    s["rsi_above60"] = n > 15 and r[-1] > 60
    s["any"] = s["921"] or s["hi20"] or s["tb"] or s["cup"]
    s["any+rsi"] = s["any"] and s["rsi_above60"]
    s["any&rsi60"] = s["any"] and s["rsi60"]
    return s


KEYS = ["921", "hi20", "tb", "cup", "rsi60", "any", "any+rsi", "any&rsi60"]


def main():
    X = load(); print("rows", len(X), flush=True)
    X["PX"] = np.where(X.VOL > 0, X.CLOSE, X.SETTLE)
    F = X[X.INST == "FUT"].sort_values("EXPIRY").groupby(["SYMBOL", "Date"]).CLOSE.first()
    O = X[(X.INST == "OPT") & (X.PX > 0)]
    syms = sorted(O.SYMBOL.unique()); print("symbols", len(syms), flush=True)
    P = yf.download([s + ".NS" for s in syms], start="2019-10-01", auto_adjust=True, progress=False, group_by="ticker", threads=True)
    ev = []
    for sym in syms:
        try:
            px = P[sym + ".NS"][["Open", "Close"]].dropna()
        except Exception:  # noqa: BLE001
            continue
        if len(px) < 200:
            continue
        pidx = px.index; po, pc = px.Open.values, px.Close.values
        Fs = F.get(sym)
        if Fs is None:
            continue
        Os = O[O.SYMBOL == sym]
        series = {k: g.drop_duplicates("Date").set_index("Date").sort_index() for k, g in Os.groupby(["TYPE", "EXPIRY", "STRIKE"])}
        by_day = {d: g for d, g in Os.groupby("Date")}
        sh = pd.Series(pc, index=pidx); sh_h = sh                                   # stock's own signals use closes (cup on closes)
        last_ev = {}
        for d, g in by_day.items():
            if d not in Fs.index or d not in px.index:
                continue
            f = float(Fs.loc[d]); exps = sorted(e for e in g.EXPIRY.unique() if (e - d).days >= 10)
            if not exps:
                continue
            e = exps[0]; ks = g[g.EXPIRY == e].STRIKE.unique()
            if not len(ks):
                continue
            k = float(min(ks, key=lambda v: abs(v - f)))
            j = pidx.get_loc(d)
            if j + 1 + max(H) >= len(pidx) and j + 1 + H[0] >= len(pidx):
                continue
            fwd = {h: (pc[j + 1 + h - 1] / po[j + 1] - 1) * 100 if j + h < len(pidx) else np.nan for h in H}
            own = sigs(sh_h.values[max(0, j - 260):j + 1], sh.values[max(0, j - 260):j + 1])
            for typ in ("CE", "PE"):
                S = series.get((typ, e, k))
                if S is None:
                    continue
                S = S[S.index <= d]
                if len(S) < 5 or S.index[-1] != d:
                    continue
                hh = np.where(S.VOL > 0, S.HIGH, S.PX).astype(float); cc = S.PX.values.astype(float)
                s = sigs(hh, cc)
                hit = [k_ for k_ in KEYS if s[k_]]
                if not hit:
                    continue
                key = (typ,)
                if d - last_ev.get(key, pd.Timestamp("1900-01-01")) < pd.Timedelta(days=14):
                    continue
                last_ev[key] = d
                ev.append(dict(sym=sym, d=d, typ=typ, sig=hit, own_any=bool(own["any"]), **{f"r{h}": fwd[h] for h in H}))
        # control: every 5th trading day of the stock
        for j in range(250, len(pidx) - 1, 5):
            if pidx[j] < pd.Timestamp("2020-03-01"):
                continue
            own = sigs(sh_h.values[max(0, j - 260):j + 1], sh.values[max(0, j - 260):j + 1])
            ev.append(dict(sym=sym, d=pidx[j], typ="CTRL", sig=[k_ for k_ in KEYS if own[k_]], own_any=bool(own["any"]),
                           **{f"r{h}": (pc[j + h] / po[j + 1] - 1) * 100 if j + h < len(pidx) else np.nan for h in H}))
        print(sym, len(ev), flush=True)
    E = pd.DataFrame(ev)

    def summ(Z):
        out = {}
        for h in H:
            r = Z[f"r{h}"].dropna()
            if len(r) < 30:
                continue
            out[f"{h}d"] = dict(n=len(r), avg=round(r.mean(), 2), med=round(r.median(), 2), win=round((r > 0).mean() * 100, 1),
                                t=round(r.mean() / (r.std() / math.sqrt(len(r))), 2))
        return out
    res = dict(method=__doc__, control_all=summ(E[E.typ == "CTRL"]))
    C = E[E.typ == "CTRL"]
    for k_ in KEYS:
        res[f"stock's own {k_}"] = summ(C[C.sig.apply(lambda L: k_ in L)])
    for typ in ("CE", "PE"):
        Z = E[E.typ == typ]
        for k_ in KEYS:
            Zk = Z[Z.sig.apply(lambda L: k_ in L)]
            res[f"{typ} {k_}"] = summ(Zk)
            if typ == "CE" and k_ in ("any", "any+rsi", "any&rsi60"):
                res[f"{typ} {k_} | stock has no own signal"] = summ(Zk[~Zk.own_any])
                res[f"{typ} {k_} by year (20d avg)"] = Zk.groupby(Zk.d.dt.year).r20.mean().round(2).to_dict()
    os.makedirs("data/research", exist_ok=True)
    json.dump(res, open("data/research/opt_signal_delivery.json", "w"), indent=1, default=str)
    for k, v in res.items():
        if k != "method":
            print(k, v, flush=True)


if __name__ == "__main__":
    main()
