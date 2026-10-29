"""Option-OI support / resistance for every NSE F&O underlying, from the latest F&O bhavcopy.

For each underlying, on its nearest expiry:
  support    = strike with the highest PUT open interest
  resistance = strike with the highest CALL open interest
Also the 2nd-highest strikes and the put/call OI ratio.
Writes data/oi/oi_levels.json keyed by the app's Yahoo ticker (e.g. RELIANCE.NS, ^NSEI, ^NSEBANK).
Runs nightly in GitHub Actions (paper-trade workflow) after NSE publishes the bhavcopy (about 7 pm IST).

TRAPPED-WRITER ALERTS (Amritpal's rule, 24 Oct 2026):
  trapped PUT writers  = the biggest put OI of the whole chain sits ABOVE the price (those puts are now in the money)
                         -> writers under pressure, read as a BEARISH sign
  trapped CALL writers = the biggest call OI sits BELOW the price -> short-covering fuel, a BULLISH sign
Every night: data/oi/alerts.json (today's list + what is NEW vs yesterday), data/oi/history.csv (one row per
underlying per day, for backtesting later) and a Telegram summary (indices + new alerts) when SEND_TELEGRAM=1.
"""
import io
import json
import os
import sys
import time
import zipfile
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "oi", "oi_levels.json")
INDEX_TICKERS = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK", "FINNIFTY": "NIFTY_FIN_SERVICE.NS",
                 "MIDCPNIFTY": "NIFTY_MID_SELECT.NS", "NIFTYNXT50": "^NSMIDCP"}
s = requests.Session()
s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
                  "Referer": "https://www.nseindia.com/"})


def bhavcopy(d):
    url = f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"
    for _ in range(3):
        try:
            r = s.get(url, timeout=40)
            if r.status_code == 200 and r.content[:2] == b"PK":
                z = zipfile.ZipFile(io.BytesIO(r.content))
                return pd.read_csv(z.open(z.namelist()[0]))
            return None
        except Exception:  # noqa: BLE001
            time.sleep(3)
    return None


def levels(g, under=None):
    """support = biggest put OI at or below the price, resistance = biggest call OI at or above it
    (out-of-the-money writing). After a sharp fall the biggest put OI often sits ABOVE the price
    (puts written earlier, now in the money) — that is kept separately as *_any."""
    ce = g[g.OptnTp == "CE"].groupby("StrkPric").OpnIntrst.sum()
    pe = g[g.OptnTp == "PE"].groupby("StrkPric").OpnIntrst.sum()
    if ce.empty or pe.empty or ce.max() <= 0 or pe.max() <= 0:
        return None
    any_s, any_r = float(pe.idxmax()), float(ce.idxmax())
    pcr = round(float(pe.sum() / ce.sum()), 2)          # whole chain
    if under:
        pe_o, ce_o = pe[pe.index <= under], ce[ce.index >= under]
        pe = pe_o if len(pe_o) and pe_o.max() > 0 else pe
        ce = ce_o if len(ce_o) and ce_o.max() > 0 else ce
    c2, p2 = ce.nlargest(2), pe.nlargest(2)
    return dict(support_any=any_s, resistance_any=any_r,
        support=float(p2.index[0]), support_oi=int(p2.iloc[0]),
        support_2=float(p2.index[1]) if len(p2) > 1 else None,
        resistance=float(c2.index[0]), resistance_oi=int(c2.iloc[0]),
        resistance_2=float(c2.index[1]) if len(c2) > 1 else None,
        pcr=pcr,
    )


def main():
    ist = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    b, day = None, None
    for back in range(0, 8):
        d = (ist - timedelta(days=back)).date()
        if d.weekday() >= 5:
            continue
        b = bhavcopy(d)
        if b is not None:
            day = d
            break
    if b is None:
        sys.exit("no F&O bhavcopy found in the last week")
    b = b[b.FinInstrmTp.isin(["IDO", "STO"])].copy()
    b["XpryDt"] = pd.to_datetime(b.XpryDt)
    out = {}
    for sym, g in b.groupby("TckrSymb"):
        exps = sorted(e for e in g.XpryDt.unique() if e.date() >= day)
        if not exps:
            continue
        e = exps[0]
        under = float(g.UndrlygPric.dropna().iloc[0]) if "UndrlygPric" in g and g.UndrlygPric.notna().any() else None
        lv = levels(g[g.XpryDt == e], under)
        if lv is None:
            continue
        ticker = INDEX_TICKERS.get(sym, f"{sym}.NS")
        out[ticker] = dict(symbol=sym, date=str(day), expiry=str(e.date()), underlying=under, **lv)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    prev = {}
    if os.path.exists(OUT):
        try:
            old = json.load(open(OUT))
            if old.get("date") != str(day):
                prev = old.get("levels", {})
            else:   # same day re-run: compare with the stored "previous" snapshot instead
                prev = json.load(open(ALERTS)).get("prev_levels", {}) if os.path.exists(ALERTS) else {}
        except Exception:  # noqa: BLE001
            prev = {}
    json.dump(dict(date=str(day), levels=out), open(OUT, "w"), indent=1)
    print(f"OI levels for {len(out)} underlyings on {day}")
    alerts(out, prev, day)


ALERTS = os.path.join(os.path.dirname(OUT), "alerts.json")
HIST = os.path.join(os.path.dirname(OUT), "history.csv")


def flags(v):
    u = v.get("underlying")
    if not u:
        return False, False
    return v["support_any"] > u, v["resistance_any"] < u


def alerts(out, prev, day):
    rows, tp, tc = [], [], []
    for t, v in out.items():
        p_, c_ = flags(v)
        u = v["underlying"]
        rec = dict(ticker=t, symbol=v["symbol"], price=u, expiry=v["expiry"], pcr=v["pcr"],
                   support=v["support"], resistance=v["resistance"],
                   biggest_put=v["support_any"], biggest_call=v["resistance_any"])
        if p_:
            was = flags(prev[t])[0] if t in prev else False
            tp.append(dict(rec, gap_pct=round((v["support_any"] / u - 1) * 100, 2), new=not was))
        if c_:
            was = flags(prev[t])[1] if t in prev else False
            tc.append(dict(rec, gap_pct=round((1 - v["resistance_any"] / u) * 100, 2), new=not was))
        rows.append(dict(date=str(day), **rec, trapped_puts=p_, trapped_calls=c_))
    tp.sort(key=lambda r: -r["gap_pct"]); tc.sort(key=lambda r: -r["gap_pct"])
    already_sent = False
    if os.path.exists(ALERTS):
        try:
            a = json.load(open(ALERTS)); already_sent = a.get("date") == str(day) and a.get("sent", False)
        except Exception:  # noqa: BLE001
            pass
    send = os.environ.get("SEND_TELEGRAM") == "1" and not already_sent
    h = pd.DataFrame(rows)
    if os.path.exists(HIST):
        old = pd.read_csv(HIST)
        old = old[old.date != str(day)]
        h = pd.concat([old, h], ignore_index=True)
    h.to_csv(HIST, index=False)
    print(f"trapped put writers: {len(tp)} ({sum(r['new'] for r in tp)} new) | trapped call writers: {len(tc)} ({sum(r['new'] for r in tc)} new)")
    if send:
        telegram(summary(day, out, tp, tc))
    json.dump(dict(date=str(day), trapped_puts=tp, trapped_calls=tc, prev_levels=prev, sent=already_sent or send),
              open(ALERTS, "w"), indent=1)


def summary(day, out, tp, tc):
    L = [f"🧲 OI writer alerts — NSE close {day}"]
    for t, name in (("^NSEI", "Nifty"), ("^NSEBANK", "Bank Nifty")):
        v = out.get(t)
        if not v:
            continue
        p_, c_ = flags(v)
        tag = "🔴 put writers TRAPPED (bearish)" if p_ else "🟢 call writers TRAPPED (bullish)" if c_ else "no trapped writers"
        L.append(f"{name} {v['underlying']:,.0f}: S {v['support']:,.0f} / R {v['resistance']:,.0f}, PCR {v['pcr']:.2f} — {tag}"
                 + (f" (biggest put OI {v['support_any']:,.0f})" if p_ else f" (biggest call OI {v['resistance_any']:,.0f})" if c_ else ""))
    n = len(out)
    L.append(f"\nBreadth: {len(tp)}/{n} with trapped PUT writers (bearish), {len(tc)}/{n} with trapped CALL writers (bullish)")
    new_p = [r for r in tp if r["new"]][:15]
    new_c = [r for r in tc if r["new"]][:15]
    if new_p:
        L.append("\n🔴 NEW trapped put writers (bearish): " + ", ".join(f"{r['symbol']} ({r['biggest_put']:g} vs {r['price']:g})" for r in new_p))
    if new_c:
        L.append("\n🟢 NEW trapped call writers (bullish): " + ", ".join(f"{r['symbol']} ({r['biggest_call']:g} vs {r['price']:g})" for r in new_c))
    if not new_p and not new_c:
        L.append("\nNo new alerts today.")
    L.append("Full list: app → 🧲 OI Alerts tab")
    return "\n".join(L)


def telegram(text):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from notify import send
    send(text)


if __name__ == "__main__":
    main()
