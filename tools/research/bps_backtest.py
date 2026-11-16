"""Bull put spread at support in an uptrend (17 Nov 2026), step 2: real NSE stock put prices (bhavcopy EOD, branches oput-*).
Events (bps_events.csv): swing-low LEVEL touches, support LINE touches, and matched random uptrend days (control).
Trade at the touch-day close:
  expiry   = the first monthly expiry at least 10 calendar days away
  short put= the highest strike at or below the support (variant "2% below": at or below support x 0.98)
  long put = the highest strike at or below short x 0.95
  needs a traded short leg that day (volume > 0) and a credit > 0
Exits: (a) hold to expiry (settled on the near future's close that day); (b) take 50% of the credit when the spread's closing
value falls to half, else expiry. Costs: slippage max(Rs 0.05, 1% of premium) per leg per side, Rs 20 + GST per order, STT
0.1% on premium sold. Per lot of the day; return on risk = P&L / (width - credit) x lot.
Output: data/research/bps_backtest.json."""
import glob
import json
import math
import os
import subprocess

import numpy as np
import pandas as pd


def load():
    os.makedirs("oput", exist_ok=True)
    heads = subprocess.run(["git", "ls-remote", "--heads", "origin"], capture_output=True, text=True).stdout.split()
    for b in [h.replace("refs/heads/", "") for h in heads if "refs/heads/oput-" in h]:
        subprocess.run(["git", "fetch", "-q", "--depth", "1", "origin", b], check=True)
        files = subprocess.run(["git", "ls-tree", "-r", "--name-only", "FETCH_HEAD"], capture_output=True, text=True).stdout.split()
        for f in files:
            if f.endswith(".csv.gz"):
                data = subprocess.run(["git", "show", f"FETCH_HEAD:{f}"], capture_output=True).stdout
                open(os.path.join("oput", os.path.basename(f)), "wb").write(data)
    D = pd.concat([pd.read_csv(f, parse_dates=["Date", "EXPIRY"]) for f in sorted(glob.glob("oput/*.csv.gz"))])
    return D


def slip(p):
    return max(0.05, 0.01 * p)


def trade(g, d, L, below):
    on = g[g.Date == d]
    fut = on[on.INST == "FUT"].sort_values("EXPIRY")
    if fut.empty:
        return None
    lot = fut.LOT.dropna(); lot = float(lot.iloc[0]) if len(lot) else np.nan
    if not np.isfinite(lot) or lot <= 0:
        return None
    exps = sorted(e for e in on[on.INST == "OPT"].EXPIRY.unique() if (e - d).days >= 10)
    if not exps:
        return None
    ex = exps[0]; P = on[(on.INST == "OPT") & (on.EXPIRY == ex) & (on.CLOSE > 0)].set_index("STRIKE")
    ks = sorted(P.index)
    s_cands = [k for k in ks if k <= L * (0.98 if below else 1.0)]
    if not s_cands:
        return None
    ks_ = s_cands[-1]; l_cands = [k for k in ks if k <= ks_ * 0.95]
    if not l_cands or P.loc[ks_, "VOL"] <= 0:
        return None
    kl = l_cands[-1]; ps, pl = float(P.loc[ks_, "CLOSE"]), float(P.loc[kl, "CLOSE"])
    credit = ps - pl
    if credit <= 0.05:
        return None
    width = ks_ - kl
    path = g[(g.INST == "OPT") & (g.EXPIRY == ex) & (g.Date > d) & (g.Date <= ex)]
    piv = path.pivot_table(index="Date", columns="STRIKE", values="CLOSE")
    val = (piv.get(ks_) - piv.get(kl)).dropna() if ks_ in piv and kl in piv else pd.Series(dtype=float)
    fx = g[(g.INST == "FUT") & (g.EXPIRY == ex) & (g.Date == ex)]
    if len(fx):
        S = float(fx.CLOSE.iloc[0]); exp_val = max(ks_ - S, 0) - max(kl - S, 0)
    elif len(val) and val.index[-1] >= ex - pd.Timedelta(days=3):
        exp_val = float(val.iloc[-1])
    else:
        return None
    entry_cost = slip(ps) + slip(pl)
    fees = lambda orders: orders * 20 * 1.18  # noqa: E731
    stt = 0.001 * ps * lot
    hold = (credit - exp_val - entry_cost) * lot - fees(2) - stt
    tp = val[val <= 0.5 * credit]
    if len(tp):
        v = float(tp.iloc[0]); tpp = (credit - v - entry_cost - slip(v / 2 + 0.01) * 2) * lot - fees(4) - stt
    else:
        tpp = hold
    risk = (width - credit) * lot
    return dict(expiry=str(ex.date()), short=ks_, long=kl, credit=credit, width=width, lot=lot, hold=hold, tp50=tpp,
                ror_hold=hold / risk * 100, ror_tp=tpp / risk * 100, max_win=(credit - entry_cost) * lot)


def summ(X, col, rcol):
    if not len(X):
        return {}
    r = X[rcol]
    return dict(n=len(X), win=round((X[col] > 0).mean() * 100, 1), avg_rs=round(X[col].mean()), med_rs=round(X[col].median()),
                worst_rs=round(X[col].min()), avg_ror=round(r.mean(), 1), t=round(r.mean() / (r.std() / math.sqrt(len(r))), 2) if len(r) > 2 else None,
                pos_years=f"{int((X.groupby(X.d.str[:4])[col].sum() > 0).sum())}/{X.d.str[:4].nunique()}")


def main():
    D = load(); print("option rows", len(D), flush=True)
    E = pd.read_csv("data/research/bps_events.csv")
    G = {k: g for k, g in D.groupby("SYMBOL")}
    rows = []
    for e in E.itertuples():
        g = G.get(e.sym)
        if g is None:
            continue
        for below in (False, True):
            t = trade(g, pd.Timestamp(e.d), e.L, below)
            if t:
                kind = "line 3rd touch" if e.kind == "line" and getattr(e, "nth", np.nan) == 3 else e.kind
                rows.append(dict(sym=e.sym, d=e.d, kind=kind, place="2% below" if below else "at support", **t))
    T = pd.DataFrame(rows); out = dict(method=__doc__, groups={})
    T.loc[T.kind == "line 3rd touch", "kind2"] = "line"
    for kind in ("level", "line 3rd touch", "line", "control"):
        for place in ("at support", "2% below"):
            X = T[((T.kind == kind) | ((kind == "line") & (T.kind == "line 3rd touch"))) & (T.place == place)]
            g = {"hold to expiry": summ(X, "hold", "ror_hold"), "take 50%": summ(X, "tp50", "ror_tp")}
            out["groups"][f"{kind} | {place}"] = g; print(kind, place, g, flush=True)
    os.makedirs("data/research", exist_ok=True)
    json.dump(out, open("data/research/bps_backtest.json", "w"), indent=1, default=float)
    T.to_csv("data/research/bps_trades.csv.gz", index=False)


if __name__ == "__main__":
    main()
