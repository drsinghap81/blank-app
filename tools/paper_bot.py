#!/usr/bin/env python3
"""
Top Bottom — daily PAPER-TRADING bot (no real orders).

Runs once each evening (India time) on GitHub Actions:
  1. Downloads NSE F&O bhavcopies for any missing trading days and appends the
     near-month index-futures bar (rolls on expiry day) to paper/history_<SYM>.csv.
  2. Re-runs the validated LIVE rules (tools/topbottom_backtest.run_live) over the
     history, so paper results are exactly what the backtested engine would do.
  3. Builds the paper ledger from the paper start date: 1 lot per trade, NSE lot
     size from the bhavcopy, futures-roll P&L correction, estimated costs.
     A position the system already holds on the start date is joined at that
     day's open.
  4. Writes paper/ledger.csv, paper/equity.csv, paper/next_orders.json,
     paper/report.md and (optionally) sends a Telegram message.

Telegram (optional): set repo secrets TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.
"""
from __future__ import annotations

import io
import json
import os
import sys
import time
import zipfile
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import topbottom_backtest as tbb  # noqa: E402

PAPER = os.path.join(ROOT, "paper")
CFG_PATH = os.path.join(PAPER, "config.json")
IST = timezone(timedelta(hours=5, minutes=30))

DEFAULT_CFG = {
    "start_date": "2026-10-19",          # paper trading starts on this session
    "join_existing_position": False,     # False = start flat, wait for a fresh top/bottom break
    "backfill_start": "2026-03-02",      # history needed to warm up tops/bottoms
    "instruments": {
        "BANKNIFTY": {"buffer_pts": 25, "lots": 1},
        "NIFTY": {"buffer_pts": 10, "lots": 1},
    },
    "rules": {"day_sl_pct": 1.0, "max_sl_pct": 2.0, "be_pct": 2.0, "gap_pct": 2.0, "use_once": True},
    "cost_pct_round_trip": 0.05,         # ESTIMATE: brokerage + STT + exchange + GST + slippage, % of entry value
}


# ---------------------------------------------------------------------------
# NSE data
# ---------------------------------------------------------------------------
_session = None


def _sess():
    global _session
    if _session is None:
        import requests
        _session = requests.Session()
        _session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                               "(KHTML, like Gecko) Chrome/120 Safari/537.36",
                                 "Referer": "https://www.nseindia.com/"})
    return _session


def fetch_bhavcopy(day: pd.Timestamp) -> pd.DataFrame | None:
    """UDiFF F&O bhavcopy (format used since July 2024). None if no file (holiday / not yet published)."""
    ymd = day.strftime("%Y%m%d")
    for host in ("nsearchives.nseindia.com", "archives.nseindia.com"):
        url = f"https://{host}/content/fo/BhavCopy_NSE_FO_0_0_0_{ymd}_F_0000.csv.zip"
        for _ in range(3):
            try:
                r = _sess().get(url, timeout=30)
            except Exception:
                time.sleep(2)
                continue
            if r.status_code == 200 and r.content[:2] == b"PK":
                z = zipfile.ZipFile(io.BytesIO(r.content))
                return pd.read_csv(z.open(z.namelist()[0]))
            break
    return None


def bar_from_bhav(bhav: pd.DataFrame, symbol: str, day: pd.Timestamp) -> dict | None:
    f = bhav[(bhav["FinInstrmTp"] == "IDF") & (bhav["TckrSymb"] == symbol)].copy()
    if f.empty:
        return None
    f["Exp"] = pd.to_datetime(f["XpryDt"])
    f = f[f["Exp"] >= day].sort_values("Exp")
    near = f.iloc[0]
    nxt = f.iloc[1] if len(f) > 1 else None
    return dict(Date=day.strftime("%Y-%m-%d"), Expiry=near["Exp"].strftime("%Y-%m-%d"),
                Open=float(near["OpnPric"]), High=float(near["HghPric"]), Low=float(near["LwPric"]),
                Close=float(near["ClsPric"]), NextClose=float(nxt["ClsPric"]) if nxt is not None else np.nan,
                Lot=int(near["NewBrdLotQty"]) if not pd.isna(near.get("NewBrdLotQty")) else np.nan,
                Spot=float(near["UndrlygPric"]) if not pd.isna(near.get("UndrlygPric")) else np.nan)


def update_histories(cfg: dict, today: pd.Timestamp) -> dict[str, pd.DataFrame]:
    syms = list(cfg["instruments"])
    hist = {}
    for s in syms:
        p = os.path.join(PAPER, f"history_{s}.csv")
        hist[s] = pd.read_csv(p) if os.path.exists(p) else pd.DataFrame()
    last = min((pd.Timestamp(h["Date"].iloc[-1]) for h in hist.values() if len(h)),
               default=pd.Timestamp(cfg["backfill_start"]) - pd.Timedelta(days=1))
    days = pd.bdate_range(last + pd.Timedelta(days=1), today)
    added = 0
    for d in days:
        bhav = fetch_bhavcopy(d)
        if bhav is None:
            continue
        for s in syms:
            if len(hist[s]) and (hist[s]["Date"] == d.strftime("%Y-%m-%d")).any():
                continue
            b = bar_from_bhav(bhav, s, d)
            if b:
                hist[s] = pd.concat([hist[s], pd.DataFrame([b])], ignore_index=True)
                added += 1
        time.sleep(0.2)
    for s in syms:
        hist[s].to_csv(os.path.join(PAPER, f"history_{s}.csv"), index=False)
    print(f"history: +{added} bars", file=sys.stderr)
    return hist


# ---------------------------------------------------------------------------
# Paper ledger from the validated live engine
# ---------------------------------------------------------------------------
def roll_adjustment(h: pd.DataFrame, side: int, entry_date, exit_date) -> float:
    """Points to add to a near-month-series trade so it reflects rolling the
    position on expiry day (sell old at its close, buy next at its close)."""
    adj = 0.0
    exp_days = h[(h["Date"] == h["Expiry"])]
    for _, r in exp_days.iterrows():
        d = pd.Timestamp(r["Date"])
        if pd.Timestamp(entry_date) <= d < pd.Timestamp(exit_date) and not np.isnan(r["NextClose"]):
            adj += side * (r["Close"] - r["NextClose"])
    return adj


def build_ledger(sym: str, h: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, dict, tbb.Params, pd.DataFrame]:
    inst, rules = cfg["instruments"][sym], cfg["rules"]
    join = cfg.get("join_existing_position", False)
    p = tbb.Params(buffer_pts=inst["buffer_pts"], day_sl_pct=rules["day_sl_pct"], max_sl_pct=rules["max_sl_pct"],
                   be_pct=rules["be_pct"], gap_pct=rules["gap_pct"], use_once=rules["use_once"],
                   start_flat_on=None if join else cfg["start_date"])
    df = h.copy()
    df.index = pd.to_datetime(df["Date"])
    ohlc = df[["Open", "High", "Low", "Close"]]
    t = tbb.run_live(ohlc, p)
    start = pd.Timestamp(cfg["start_date"])
    rows = []
    if not t.empty:
        t["EntryDate"] = pd.to_datetime(t["EntryDate"])
        t["ExitDate"] = pd.to_datetime(t["ExitDate"])
        # a position already open on the start date is joined at that day's open
        carried = t[(t["EntryDate"] < start) & ((t["ExitDate"] >= start) | t["Open"])]
        if join and len(carried) and start in ohlc.index:
            r = carried.iloc[-1].copy()
            r["Entry"] = float(ohlc.loc[start, "Open"])
            r["EntryDate"] = start
            r["Signal"] = "Joined system position at open"
            rows.append(r)
        for _, r in t[t["EntryDate"] >= start].iterrows():
            rows.append(r)
    led = pd.DataFrame(rows)
    if led.empty:
        led = pd.DataFrame(columns=["EntryDate", "Side", "Entry", "ExitDate", "Exit", "Reason", "Open"])
    else:
        side = np.where(led["Side"] == "BUY", 1, -1)
        led["RollAdj"] = [roll_adjustment(h, s, a, b) for s, a, b in zip(side, led["EntryDate"], led["ExitDate"])]
        led["Points"] = ((led["Exit"] - led["Entry"]) * side + led["RollAdj"]).round(2)
        lot = [int(df.loc[:d, "Lot"].dropna().iloc[-1]) if df.loc[:d, "Lot"].notna().any() else 1
               for d in led["EntryDate"]]
        led["Qty"] = np.array(lot) * inst["lots"]
        led["Gross"] = (led["Points"] * led["Qty"]).round(0)
        led["Costs"] = (led["Entry"] * led["Qty"] * cfg["cost_pct_round_trip"] / 100).round(0)
        led["Net"] = led["Gross"] - led["Costs"]
        led.insert(0, "Instrument", sym)
        led["Status"] = np.where(led["Open"], "OPEN (marked to last close)", "Closed")
    return led, tbb.next_orders(ohlc, t, p), p, ohlc


def whatsapp(text: str) -> None:
    """WhatsApp alert via CallMeBot (free, personal) or TextMeBot (~US$1/month, sends from
    your own WhatsApp to yourself). Repo secrets: WHATSAPP_PROVIDER (callmebot|textmebot),
    WHATSAPP_PHONE (e.g. +61412345678), WHATSAPP_APIKEY."""
    prov = (os.environ.get("WHATSAPP_PROVIDER") or "callmebot").lower()
    phone, key = os.environ.get("WHATSAPP_PHONE"), os.environ.get("WHATSAPP_APIKEY")
    if not phone or not key:
        return
    if prov == "textmebot":
        url, params = "https://api.textmebot.com/send.php", {"recipient": phone, "apikey": key, "text": text}
    else:
        url, params = "https://api.callmebot.com/whatsapp.php", {"phone": phone, "apikey": key, "text": text}
    try:
        r = _sess().get(url, params=params, timeout=30)
        print("whatsapp:", prov, r.status_code, r.text[:120].replace("\n", " "), file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print("whatsapp failed:", e, file=sys.stderr)


def whatsapp_message(orders_all: dict, summary: dict, led: pd.DataFrame, cfg: dict) -> str:
    """Same style as the daily Top Bottom calls."""
    lines = []
    for sym, o in orders_all.items():
        nxt = (pd.Timestamp(o["date"]) + pd.offsets.BDay(1)).strftime("%d/%m/%Y")
        lots = cfg["instruments"][sym]["lots"]
        lot = o.get("lot_size") or 0
        lines.append(f"*TOP BOTTOM LEVELS for {nxt}*")
        lines.append("")
        lines.append(f"*{sym} FUT ({pd.Timestamp(o['futures_contract_expiry']).strftime('%d-%b').upper()}) - "
                     f"Closing Price {float(o['close']):,.2f}*")
        lines.append(f"Position: {o['position']}  ({lots} lot{'s' if lots > 1 else ''} x {lot})")
        for x in o["orders"]:
            lines.append(f"    {x}")
        lines.append("")
    if len(led):
        today = led[pd.to_datetime(led["ExitDate"]).dt.date == pd.Timestamp(list(orders_all.values())[0]["date"]).date()]
        for _, r in today.iterrows():
            if not bool(r["Open"]):
                lines.append(f"Closed today: {r['Side']} {r['Entry']:,.0f} -> {r['Exit']:,.0f} "
                             f"({r['Reason']}) = Rs {r['Net']:,.0f}")
    lines.append(f"Paper P&L since {summary['start_date']}: realised Rs {summary['realised_net']:,.0f}, "
                 f"open Rs {summary['open_mtm_net']:,.0f}, trades {summary['trades']} "
                 f"(W {summary['winners']}/L {summary['losers']})")
    lines.append("_Paper trading only - not investment advice_")
    return "\n".join(lines)


def telegram(text: str) -> None:
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        return
    try:
        _sess().post(f"https://api.telegram.org/bot{tok}/sendMessage",
                     data={"chat_id": chat, "text": text}, timeout=20)
    except Exception as e:  # noqa: BLE001
        print("telegram failed:", e, file=sys.stderr)


def main():
    os.makedirs(PAPER, exist_ok=True)
    if not os.path.exists(CFG_PATH):
        json.dump(DEFAULT_CFG, open(CFG_PATH, "w"), indent=2)
    cfg = json.load(open(CFG_PATH))
    today = pd.Timestamp(datetime.now(IST).date())
    hist = update_histories(cfg, today)

    ledgers, orders_all, report = [], {}, []
    for sym, h in hist.items():
        if h.empty:
            continue
        led, orders, p, ohlc = build_ledger(sym, h, cfg)
        ledgers.append(led)
        last = h.iloc[-1]
        orders["futures_contract_expiry"] = last["Expiry"]
        orders["lot_size"] = None if pd.isna(last.get("Lot")) else int(last["Lot"])
        orders["spot_close"] = None if pd.isna(last.get("Spot")) else float(last["Spot"])
        orders_all[sym] = {k: (str(v) if isinstance(v, (pd.Timestamp,)) else v) for k, v in orders.items()}
        nxt = (pd.Timestamp(last["Date"]) + pd.offsets.BDay(1)).date()
        report.append(f"*{sym} FUT* ({last['Expiry']} expiry) — close {last['Close']:,.2f} on {last['Date']}")
        report.append(f"Position: {orders['position']}")
        report += [f"• {x}" for x in orders["orders"]]
        report.append(f"(orders for {nxt}; levels on the near-month futures close line)")
        report.append("")

    led = pd.concat(ledgers, ignore_index=True) if ledgers else pd.DataFrame()
    led.to_csv(os.path.join(PAPER, "ledger.csv"), index=False)
    json.dump(orders_all, open(os.path.join(PAPER, "next_orders.json"), "w"), indent=2, default=str)

    # equity (closed + open marked to market), in rupees
    if len(led):
        closed = led[~led["Open"].astype(bool)]
        summary = {
            "trades": int(len(led)), "closed": int(len(closed)),
            "winners": int((closed["Net"] > 0).sum()), "losers": int((closed["Net"] < 0).sum()),
            "realised_net": float(closed["Net"].sum()),
            "open_mtm_net": float(led.loc[led["Open"].astype(bool), "Net"].sum()),
        }
        eq = led.assign(Day=pd.to_datetime(led["ExitDate"]).dt.date).groupby("Day")["Net"].sum().cumsum()
        eq.rename("CumNet").to_csv(os.path.join(PAPER, "equity.csv"))
    else:
        summary = {"trades": 0, "closed": 0, "winners": 0, "losers": 0, "realised_net": 0.0, "open_mtm_net": 0.0}
    summary["updated_ist"] = datetime.now(IST).strftime("%Y-%m-%d %H:%M")
    summary["start_date"] = cfg["start_date"]
    json.dump(summary, open(os.path.join(PAPER, "summary.json"), "w"), indent=2)

    head = (f"TOP BOTTOM — PAPER (since {cfg['start_date']})\n"
            f"Realised ₹{summary['realised_net']:,.0f} | Open MTM ₹{summary['open_mtm_net']:,.0f} | "
            f"Trades {summary['trades']} (W {summary['winners']} / L {summary['losers']})\n")
    text = head + "\n" + "\n".join(report) + "Paper trading only — no orders placed."
    open(os.path.join(PAPER, "report.md"), "w").write(text)
    print(text)
    for sym, o in orders_all.items():
        o["date"] = hist[sym].iloc[-1]["Date"]
    wa = whatsapp_message(orders_all, summary, led, cfg)
    open(os.path.join(PAPER, "whatsapp.txt"), "w").write(wa)
    if os.environ.get("SEND_TELEGRAM", "1") == "1":
        telegram(wa.replace("*", "").replace("_", ""))
        whatsapp(wa)


if __name__ == "__main__":
    main()
