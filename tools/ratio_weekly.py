"""Nifty weekly 'conclave' ratio system - daily end-of-day job (runs after the NSE close).

System (backtest Mar 2019 - Oct 2026, see project doc conclave-2022.md):
  Each weekly series, both sides, entered on the first trading day after the previous expiry, held to expiry:
    call side: +1 call ~150 pts ITM, -2 calls ~1.44% OTM, -4 calls ~1.71% OTM
    put side:  +1 put  ~150 pts ITM, -2 puts  ~1.44% OTM, -4 puts  ~1.71% OTM
  SKIP the week when the next expiry's ATM straddle (measured on the expiry evening, normalised by sqrt(days))
  is above the 80th percentile of its own history. Optional shift rule: when a side's long goes ATM/OTM, re-set
  that side 150 pts ITM.
  Backtest (lot 65, costs): ~Rs 2.5 lakh/yr per set, every year positive, worst week -Rs 1.65 lakh. Margin ~Rs 8-10 lakh/set.

What this job does (idempotent, catches up on missed days):
  - downloads the NSE F&O bhavcopy for each new trading day (Nifty options + futures only)
  - on an expiry evening: measures the next series' straddle, appends data/ratio/iv_hist.csv, decides TRADE/SKIP,
    publishes the plan (strikes from that evening's future) to data/ratio/ratio_weekly.json and sends an alert
  - on the entry day (first day after expiry): records a PAPER entry at that day's close with strikes re-centred
  - every day: marks the paper position to market; on expiry: settles at intrinsic and appends data/ratio/paper.csv
Nothing here places orders."""
import io
import json
import os
import sys
import time
import zipfile
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from notify import send
except Exception:  # noqa: BLE001
    def send(_):
        return False

OUT = "data/ratio"
LOT = int(os.environ.get("NIFTY_LOT", "65"))
ITM_PTS, D1, D2, N1, N2 = 150, 0.0144, 0.0171, 2, 4
PCT_SKIP = 80
MARGIN_EST = "Rs 8-10 lakh per set (estimate; check your broker)"
S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
                  "Referer": "https://www.nseindia.com/"})


def bhav(d):
    url = f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"
    for _ in range(3):
        try:
            r = S.get(url, timeout=30)
            if r.status_code == 200 and r.content[:2] == b"PK":
                z = zipfile.ZipFile(io.BytesIO(r.content))
                b = pd.read_csv(z.open(z.namelist()[0]))
                b = b[(b.TckrSymb == "NIFTY") & b.FinInstrmTp.isin(["IDO", "IDF"])]
                return pd.DataFrame({"INST": b.FinInstrmTp.map({"IDO": "OPT", "IDF": "FUT"}), "EXPIRY": pd.to_datetime(b.XpryDt),
                                     "STRIKE": b.StrkPric, "TYPE": b.OptnTp, "CLOSE": b.ClsPric, "SETTLE": b.SttlmPric,
                                     "VOL": b.TtlTradgVol})
            if r.status_code == 404:
                return None
        except Exception:  # noqa: BLE001
            time.sleep(3)
    return None


class Day:
    def __init__(self, d, b):
        self.d = d
        f = b[b.INST == "FUT"].sort_values("EXPIRY")
        self.F = float(f.CLOSE.iloc[0])
        o = b[b.INST == "OPT"].copy()
        o["PX"] = np.where(o.VOL > 0, o.CLOSE, o.SETTLE)
        self.o = o
        self.exps = sorted(e for e in o.EXPIRY.unique())

    def px(self, e, typ, k):
        x = self.o[(self.o.EXPIRY == e) & (self.o.TYPE == typ) & (self.o.STRIKE == k)]
        return float(x.PX.iloc[0]) if len(x) and x.PX.iloc[0] > 0 else None

    def strikes(self, e, typ):
        x = self.o[(self.o.EXPIRY == e) & (self.o.TYPE == typ) & (self.o.PX > 0)]
        ks = np.array(sorted(x.STRIKE.unique()))
        if not len(ks):
            return None
        near = lambda v: float(ks[np.argmin(np.abs(ks - v))])
        F = self.F
        if typ == "CE":
            return [near(F - ITM_PTS), near(F * (1 + D1)), near(F * (1 + D2))]
        return [near(F + ITM_PTS), near(F * (1 - D1)), near(F * (1 - D2))]

    def straddle(self, e):
        c = self.o[(self.o.EXPIRY == e) & (self.o.TYPE == "CE") & (self.o.PX > 0)].set_index("STRIKE").PX
        p = self.o[(self.o.EXPIRY == e) & (self.o.TYPE == "PE") & (self.o.PX > 0)].set_index("STRIKE").PX
        both = c.index.intersection(p.index)
        if not len(both):
            return None, None
        k = float(min(both, key=lambda z: abs(z - self.F)))
        return k, float(c[k] + p[k])


def side_value(day, e, typ, ks):
    """value (pts) of +1 long - 2 short1 - 4 short2 at this day's prices; None if any price missing"""
    p = [day.px(e, typ, k) for k in ks]
    if any(v is None for v in p):
        return None, p
    return p[0] - N1 * p[1] - N2 * p[2], p


def intrinsic(F, typ, k):
    return max(F - k, 0) if typ == "CE" else max(k - F, 0)


def plan_for(day, e, hist):
    k, st = day.straddle(e)
    if k is None:
        return None
    days = (e - day.d).days
    ivn = st / day.F / np.sqrt(max(days, 1))
    h = hist.ivn.values
    pct = float((h < ivn).mean() * 100) if len(h) else None
    cut = float(np.percentile(h, PCT_SKIP)) if len(h) >= 30 else None
    decision = "SKIP" if (cut is not None and ivn > cut) else "TRADE"
    legs = {}
    for typ in ("CE", "PE"):
        ks = day.strikes(e, typ)
        v, p = side_value(day, e, typ, ks)
        kl, k1, k2 = ks
        net = None if v is None else round(v, 2)
        nv = v or 0.0                      # net debit (+) / credit (-) in points
        peak = k1
        if typ == "CE":                    # above k2 the payoff is (2k1 + 4k2 - kl) - 5S
            ube = (N1 * k1 + N2 * k2 - kl - nv) / (N1 + N2 - 1)
            lbe = kl + nv
        else:                              # below k2 the payoff is kl - 2k1 - 4k2 + 5S
            ube = (N1 * k1 + N2 * k2 - kl + nv) / (N1 + N2 - 1)
            lbe = kl - nv
        legs[typ] = dict(long=kl, short2=k1, short4=k2, prices=[None if x is None else round(x, 2) for x in p], net_debit=net,
                         best_at=peak, best_pts=round(abs(k1 - kl) - (v or 0), 1),
                         breakeven_far=round(ube, 0), breakeven_near=round(lbe, 0),
                         shift_trigger=kl)
    return dict(expiry=str(e.date()), asof=str(day.d.date()), future=round(day.F, 1), days_to_expiry=days, atm=k,
                straddle=round(st, 2), straddle_pct_of_future=round(st / day.F * 100, 3), ivn=round(ivn, 6),
                percentile=None if pct is None else round(pct), skip_above_pct=PCT_SKIP, decision=decision, legs=legs,
                lot=LOT, margin=MARGIN_EST)


def msg_plan(p):
    c, q = p["legs"]["CE"], p["legs"]["PE"]
    s = (f"Nifty weekly ratio - expiry {p['expiry']}: {p['decision']}\n"
         f"Straddle {p['straddle']:.0f} pts ({p['straddle_pct_of_future']:.2f}%), percentile {p['percentile']} (skip above {p['skip_above_pct']})\n")
    if p["decision"] == "TRADE":
        s += (f"Enter tomorrow near the close (strikes re-centre on the day):\n"
              f"CALL: +1 {c['long']:.0f}CE, -2 {c['short2']:.0f}CE, -4 {c['short4']:.0f}CE\n"
              f"PUT:  +1 {q['long']:.0f}PE, -2 {q['short2']:.0f}PE, -4 {q['short4']:.0f}PE\n"
              f"Danger zones beyond {q['breakeven_far']:.0f} / {c['breakeven_far']:.0f}. Lot {p['lot']}.")
    else:
        s += "Premium is unusually high this week - stay out."
    return s


def main():
    os.makedirs(OUT, exist_ok=True)
    hist = pd.read_csv(f"{OUT}/iv_hist.csv", parse_dates=["asof", "expiry"]) if os.path.exists(f"{OUT}/iv_hist.csv") else pd.DataFrame(columns=["asof", "expiry", "future", "atm", "straddle", "days", "ivn"])
    state = json.load(open(f"{OUT}/state.json")) if os.path.exists(f"{OUT}/state.json") else {}
    plan = json.load(open(f"{OUT}/ratio_weekly.json")) if os.path.exists(f"{OUT}/ratio_weekly.json") else {}
    paper = pd.read_csv(f"{OUT}/paper.csv") if os.path.exists(f"{OUT}/paper.csv") else pd.DataFrame()
    last = pd.Timestamp(state.get("last_day", str(hist["asof"].max().date()) if len(hist) else "2026-10-01"))
    today = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).date()
    now_ist = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    end = pd.Timestamp(today) if now_ist.hour * 60 + now_ist.minute >= 16 * 60 + 30 else pd.Timestamp(today) - pd.Timedelta(days=1)
    msgs = []
    for d in pd.bdate_range(last + pd.Timedelta(days=1), end):
        b = bhav(d)
        if b is None or b.empty:
            continue
        day = Day(d, b)
        print("processing", d.date(), "future", day.F, flush=True)
        is_expiry = any(e == d for e in day.exps)
        nxt = [e for e in day.exps if e > d]
        if not nxt:
            continue
        e_next = nxt[0]
        pos = state.get("position")
        # 1) settle an open paper position on its expiry day
        if pos and pd.Timestamp(pos["expiry"]) <= d:
            pnl = 0.0
            for typ, lg in pos["legs"].items():
                ks = [lg["long"], lg["short2"], lg["short4"]]
                end_v = intrinsic(day.F, typ, ks[0]) - N1 * intrinsic(day.F, typ, ks[1]) - N2 * intrinsic(day.F, typ, ks[2])
                pnl += end_v - lg["entry_value"] - lg["entry_cost"]
            row = dict(expiry=pos["expiry"], entry=pos["entry"], decision="TRADE", future_entry=pos["future"], future_expiry=round(day.F, 1),
                       pnl_pts=round(pnl, 1), pnl_rs=round(pnl * LOT), move_pct=round((day.F / pos["future"] - 1) * 100, 2))
            paper = pd.concat([paper, pd.DataFrame([row])], ignore_index=True)
            msgs.append(f"Nifty weekly ratio (paper) expiry {pos['expiry']}: {'+' if pnl >= 0 else ''}{pnl:.0f} pts = Rs {pnl*LOT:+,.0f} per set "
                        f"(Nifty {row['move_pct']:+.2f}% for the week)")
            state["position"] = None; pos = None
        # 2) expiry evening: measure the next series, decide, publish the plan
        if is_expiry or not plan or pd.Timestamp(plan.get("expiry", "2000-01-01")) < e_next:
            if plan.get("expiry") != str(e_next.date()):
                p = plan_for(day, e_next, hist[hist.expiry < e_next])
                if p:
                    p["late"] = not is_expiry
                    plan = p
                    hist = pd.concat([hist, pd.DataFrame([dict(asof=d, expiry=e_next, future=round(day.F, 2), atm=p["atm"], straddle=p["straddle"],
                                                                days=p["days_to_expiry"], ivn=p["ivn"])])], ignore_index=True)
                    msgs.append(msg_plan(p))
                    state["entry_pending"] = str(e_next.date()) if p["decision"] == "TRADE" else None
            continue
        # 3) entry day: paper entry at this close, strikes re-centred on today's future
        if state.get("entry_pending") == str(e_next.date()) and not pos:
            legs = {}
            ok = True
            for typ in ("CE", "PE"):
                ks = day.strikes(e_next, typ)
                v, pr = side_value(day, e_next, typ, ks)
                if v is None:
                    ok = False; break
                cost = sum((max(0.1, 0.005 * x) + 0.0007 * x + 40 / LOT) * n for x, n in zip(pr, (1, N1, N2)))
                legs[typ] = dict(long=ks[0], short2=ks[1], short4=ks[2], entry_prices=pr, entry_value=v, entry_cost=cost)
            if ok:
                state["position"] = dict(expiry=str(e_next.date()), entry=str(d.date()), future=round(day.F, 1), legs=legs)
                def far_be(t, l):
                    nv = l["entry_value"]
                    a = N1 * l["short2"] + N2 * l["short4"] - l["long"]
                    return round((a - nv) / (N1 + N2 - 1) if t == "CE" else (a + nv) / (N1 + N2 - 1), 0)
                plan["entered"] = dict(date=str(d.date()), future=round(day.F, 1),
                                       legs={t: dict(long=l["long"], short2=l["short2"], short4=l["short4"], prices=[round(x, 2) for x in l["entry_prices"]],
                                                     net=round(l["entry_value"], 2), breakeven_far=far_be(t, l))
                                             for t, l in legs.items()})
            state["entry_pending"] = None
        # 4) mark to market
        pos = state.get("position")
        if pos:
            mtm = 0.0
            for typ, lg in pos["legs"].items():
                v, _ = side_value(day, pd.Timestamp(pos["expiry"]), typ, [lg["long"], lg["short2"], lg["short4"]])
                if v is not None:
                    mtm += v - lg["entry_value"] - lg["entry_cost"]
            plan["paper_mtm"] = dict(date=str(d.date()), pts=round(mtm, 1), rs=round(mtm * LOT), future=round(day.F, 1))
        state["last_day"] = str(d.date())
    if "last_day" not in state and len(hist):
        state["last_day"] = str(hist["asof"].max().date())
    hist = hist.drop_duplicates("expiry", keep="first")
    hist.assign(asof=pd.to_datetime(hist["asof"]).dt.date, expiry=pd.to_datetime(hist.expiry).dt.date).to_csv(f"{OUT}/iv_hist.csv", index=False)
    if len(paper):
        paper.to_csv(f"{OUT}/paper.csv", index=False)
    plan["updated"] = now_ist.strftime("%Y-%m-%d %H:%M IST")
    plan["position"] = state.get("position")
    json.dump(plan, open(f"{OUT}/ratio_weekly.json", "w"), indent=1, default=str)
    json.dump(state, open(f"{OUT}/state.json", "w"), indent=1, default=str)
    for m_ in msgs:
        print(m_)
        if os.environ.get("SEND_ALERTS") == "1":
            send(m_)


if __name__ == "__main__":
    main()
