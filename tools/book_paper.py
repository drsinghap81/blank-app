"""Combined paper portfolio ("the book"): Monthly ATH + 9/21 cross on the spare cash + Top Bottom futures on pledged margin.
Paper only — no orders. Runs nightly after the scans (GitHub Actions), state kept in paper/book/.
  ATH   : every new breakout in data/scan/ath.json from the start date; 1% of equity at risk to the 30-week SMA, <= 20% of
          equity per stock, <= 10 stocks; one add when the scanner marks it 'added'; exit at the scanner's exit price.
  9/21  : every new EMA 9/21 signal in data/scan/trend_scan.json (NSE) bought at the scanner's entry (next open), 1% risk
          to the 5-day-low stop, <= 20% per stock, <= 10 stocks, only with cash the ATH book is not using, keeping 15% of equity free for new ATH breakouts. Followed here on
          daily prices: stop hit -> sold at the stop (or the open if below); Supertrend(10,3) red at the close -> next open.
  TB    : Top Bottom paper trades (paper/ledger.csv) from the start date, scaled to TB_QTY units (1 Bank Nifty lot = 30).
Costs: 0.125% per side + 0.15% slippage per side on stocks; TB nets as recorded by the paper bot."""
import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BOOK = "paper/book"
CFG = dict(capital=2_000_000, start="2026-10-29", ath_risk=0.01, t921_risk=0.01, cap=0.20, max_ath=10, max_921=10, reserve=0.15,
           tb_qty=30, cost=0.00125, slip=0.0015)


def load(path, default):
    try:
        return json.load(open(path))
    except Exception:  # noqa: BLE001
        return default


def fill_buy(px, c):
    return px * (1 + c["slip"]) * (1 + c["cost"])


def fill_sell(px, c):
    return px * (1 - c["slip"]) * (1 - c["cost"])


def supertrend_dir(h, l, cl, n=10, m=3.0):
    pc = np.roll(cl, 1); pc[0] = cl[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    atr = np.empty_like(cl); atr[0] = tr[0]
    for i in range(1, len(cl)):
        atr[i] = atr[i - 1] + (tr[i] - atr[i - 1]) / n
    mid = (h + l) / 2
    fu, fl = mid + m * atr, mid - m * atr
    d = np.ones(len(cl), dtype=int)
    for i in range(1, len(cl)):
        ub, lb = mid[i] + m * atr[i], mid[i] - m * atr[i]
        fu[i] = ub if (ub < fu[i - 1] or cl[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = lb if (lb > fl[i - 1] or cl[i - 1] < fl[i - 1]) else fl[i - 1]
        d[i] = (-1 if cl[i] < fl[i] else 1) if d[i - 1] == 1 else (1 if cl[i] > fu[i] else -1)
    return d


def main():
    os.makedirs(BOOK, exist_ok=True)
    c = {**CFG, **load(f"{BOOK}/config.json", {})}
    st = load(f"{BOOK}/state.json", None) or dict(cash=c["capital"], pos={}, done=[], trades=[])
    done = set(st["done"])
    pos = st["pos"]
    ath = load("data/scan/ath.json", {})
    trend = load("data/scan/trend_scan.json", {})
    asof = max(ath.get("asof", "2000-01-01"), trend.get("asof", "2000-01-01"))
    start = c["start"]

    def equity():
        tb = st.get("tb_total", 0.0)
        return st["cash"] + sum(p["sh"] * p["last"] for p in pos.values()) + tb

    def close_pos(k, px, d, why):
        p = pos.pop(k)
        proceeds = p["sh"] * fill_sell(px, c)
        st["cash"] += proceeds
        st["trades"].append(dict(engine=p["engine"], symbol=p["symbol"], entry_date=p["date"], entry=round(p["avg"], 2),
                                 shares=p["sh"], exit_date=d, exit=round(px, 2), pnl=round(proceeds - p["cost"]),
                                 ret_pct=round((proceeds / p["cost"] - 1) * 100, 1), why=why))
        done.add(k)

    # ---------------- ATH (scanner records carry entry, add and exit)
    recs = sorted([r for r in ath.get("tracked") or [] if str(r.get("date", ""))[:10] >= start], key=lambda r: r["date"])
    for r in recs:
        k = f"ath:{r['symbol']}:{r['date'][:10]}"
        if k in done:
            continue
        if k not in pos:
            n_ath = sum(1 for p in pos.values() if p["engine"] == "ATH")
            E, sma = r["entry"], r.get("sma_entry") or r.get("sma30")
            if n_ath >= c["max_ath"] or not sma or E <= sma:
                done.add(k); continue
            eq = equity()
            val = min(c["ath_risk"] * eq * E / (E - sma), c["cap"] * eq, st["cash"] / (1 + c["slip"] + c["cost"]))
            sh = math.floor(val / E)
            if sh * E < 10_000:
                done.add(k); continue
            cost = sh * fill_buy(E, c)
            st["cash"] -= cost
            pos[k] = dict(engine="ATH", symbol=r["symbol"], date=r["date"][:10], sh=sh, avg=E, cost=cost, last=r["close"],
                          stop_note=f"weekly close < 30-wk SMA ({r.get('sma30')})", added=False)
        p = pos[k]
        p["last"] = r["close"]; p["stop_note"] = f"weekly close < 30-wk SMA ({r.get('sma30')})"
        if r.get("add_status") == "added" and not p["added"] and r.get("add_price"):
            A, sma = r["add_price"], r.get("add_sma") or r.get("sma30")
            eq = equity()
            if sma and A > sma:
                val = min(c["ath_risk"] * eq * A / (A - sma), c["cap"] * eq - p["sh"] * A, st["cash"] / (1 + c["slip"] + c["cost"]))
                sh = math.floor(val / A)
                if sh > 0:
                    cost = sh * fill_buy(A, c)
                    st["cash"] -= cost
                    p["avg"] = (p["avg"] * p["sh"] + A * sh) / (p["sh"] + sh); p["sh"] += sh; p["cost"] += cost
            p["added"] = True
        if r.get("status") == "exited" and r.get("exit_price"):
            close_pos(k, r["exit_price"], str(r.get("exit_date"))[:10], "weekly close below 30-wk SMA")

    # ---------------- 9/21 (entries from the scanner, exits followed here on daily prices)
    for e in trend.get("early") or []:
        if not str(e.get("setup", "")).startswith("EMA") or e["signal_date"] < start:
            continue
        k = f"921:{e['symbol']}:{e['signal_date']}"
        if k in done or k in pos or e.get("entry") is None or str(e["status"]).startswith(("skipped", "NEW")):
            continue
        n921 = sum(1 for p in pos.values() if p["engine"] == "9/21")
        E, stop = float(e["entry"]), float(e["stop"])
        if n921 >= c["max_921"] or E <= stop:
            done.add(k); continue
        eq = equity()
        # 9/21 only uses the cash the ATH book is not using, keeping a reserve free for new ATH breakouts
        ath_now = sum(p["sh"] * p["last"] for p in pos.values() if p["engine"] == "ATH")
        t921_now = sum(p["sh"] * p["last"] for p in pos.values() if p["engine"] == "9/21")
        budget = max(0.0, (1 - c["reserve"]) * eq - ath_now - t921_now)
        val = min(c["t921_risk"] * eq * E / (E - stop), c["cap"] * eq, budget, st["cash"] / (1 + c["slip"] + c["cost"]))
        sh = math.floor(val / E)
        if sh * E < 10_000:
            done.add(k); continue
        cost = sh * fill_buy(E, c)
        st["cash"] -= cost
        pos[k] = dict(engine="9/21", symbol=e["symbol"], date=e["signal_date"], sh=sh, avg=E, cost=cost, last=e["close"],
                      stop=stop, checked=e["signal_date"], sell_next=False, stop_note=f"stop {stop}, then Supertrend red")
    held = sorted({p["symbol"] for p in pos.values() if p["engine"] == "9/21"})
    if held:
        import yfinance as yf
        d = yf.download([s + ".NS" for s in held], period="1y", interval="1d", auto_adjust=False, progress=False,
                        group_by="column", threads=True)
        for k in [k for k, p in pos.items() if p["engine"] == "9/21"]:
            p = pos[k]
            try:
                x = pd.DataFrame({f: d[f][p["symbol"] + ".NS"] for f in ("Open", "High", "Low", "Close")}).dropna()
            except Exception:  # noqa: BLE001
                continue
            if len(x) < 30:
                continue
            sd = supertrend_dir(x.High.values, x.Low.values, x.Close.values)
            for i, (dt, row) in enumerate(x.iterrows()):
                ds = str(dt.date())
                if ds <= p["checked"]:
                    continue
                if p.get("sell_next"):
                    close_pos(k, float(row.Open), ds, "Supertrend turned red"); break
                if ds > p["date"] and row.Low <= p["stop"]:
                    close_pos(k, float(min(row.Open, p["stop"])), ds, "stop"); break
                p["last"] = float(row.Close); p["checked"] = ds
                if sd[i] == -1:
                    p["sell_next"] = True
                    p["stop_note"] = "Supertrend red: sell next open"

    # ---------------- Top Bottom (paper ledger, scaled to TB_QTY)
    tb_total, tb_open = 0.0, 0.0
    try:
        L = pd.read_csv("paper/ledger.csv")
        L = L[L.EntryDate >= start]
        for _, t in L.iterrows():
            scale = c["tb_qty"] / float(t.Qty) if float(t.Qty) else 0
            if str(t.Status).lower().startswith("closed"):
                tb_total += float(t.Net) * scale
        summ = load("paper/summary.json", {})
        op = L[~L.Status.astype(str).str.lower().str.startswith("closed")]
        if len(op):
            tb_open = float(summ.get("open_mtm_net", 0)) * c["tb_qty"] / float(op.Qty.iloc[-1])
    except Exception as ex:  # noqa: BLE001
        print("TB ledger:", ex)
    st["tb_total"] = tb_total + tb_open

    # ---------------- record
    eq = equity()
    ath_v = sum(p["sh"] * p["last"] for p in pos.values() if p["engine"] == "ATH")
    t921_v = sum(p["sh"] * p["last"] for p in pos.values() if p["engine"] == "9/21")
    hist_path = f"{BOOK}/history.csv"
    H = pd.read_csv(hist_path) if os.path.exists(hist_path) else pd.DataFrame()
    row = dict(date=asof, equity=round(eq), cash=round(st["cash"]), ath_value=round(ath_v), t921_value=round(t921_v),
               tb_pnl=round(st["tb_total"]), n_ath=sum(p["engine"] == "ATH" for p in pos.values()),
               n_921=sum(p["engine"] == "9/21" for p in pos.values()))
    H = pd.concat([H[H.date != asof] if len(H) else H, pd.DataFrame([row])], ignore_index=True).sort_values("date")
    H.to_csv(hist_path, index=False)
    P = pd.DataFrame([dict(engine=p["engine"], symbol=p["symbol"], since=p["date"], shares=p["sh"], avg=round(p["avg"], 2),
                           last=round(p["last"], 2), value=round(p["sh"] * p["last"]),
                           pnl=round(p["sh"] * fill_sell(p["last"], c) - p["cost"]),
                           pnl_pct=round((p["sh"] * p["last"] / p["cost"] - 1) * 100, 1), exit_rule=p.get("stop_note", ""))
                      for p in pos.values()])
    P.to_csv(f"{BOOK}/positions.csv", index=False)
    pd.DataFrame(st["trades"]).to_csv(f"{BOOK}/trades.csv", index=False)
    st["done"] = sorted(done)
    json.dump(st, open(f"{BOOK}/state.json", "w"), indent=0, default=str)
    T = pd.DataFrame(st["trades"])
    summ = dict(asof=asof, updated_ist=(datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d %H:%M"),
                start=start, capital=c["capital"], equity=round(eq), ret_pct=round((eq / c["capital"] - 1) * 100, 2),
                cash=round(st["cash"]), invested_pct=round((ath_v + t921_v) / eq * 100, 1) if eq else 0,
                ath=dict(value=round(ath_v), open=row["n_ath"], realised=round(T[T.engine == "ATH"].pnl.sum()) if len(T) else 0),
                t921=dict(value=round(t921_v), open=row["n_921"], realised=round(T[T.engine == "9/21"].pnl.sum()) if len(T) else 0),
                tb=dict(pnl=round(st["tb_total"]), qty=c["tb_qty"]), closed_trades=len(T),
                rules=dict(ath_risk_pct=c["ath_risk"] * 100, t921_risk_pct=c["t921_risk"] * 100, cap_pct=c["cap"] * 100))
    json.dump(summ, open(f"{BOOK}/summary.json", "w"), indent=1)
    print(json.dumps(summ))


if __name__ == "__main__":
    main()
