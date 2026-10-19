"""Run the Top Bottom bot for one trading day on Angel One.

Start it any time before 09:00 IST (14:30 Melbourne in summer / 13:30 in winter).
It waits for the open, trades until the close, records the day's bar and exits.

    python tools/angel/run_bot.py            # normal day
    python tools/angel/run_bot.py --check    # login + show today's plan, no trading
    python tools/angel/run_bot.py --init     # (re)start FLAT from today, waiting for fresh levels

Settings: tools/angel/config.json (copy config.example.json)
Secrets : tools/angel/.env        (copy .env.example)  — never commit or share this file.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import traceback
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import json                                   # noqa: E402

import tb_live as tl                          # noqa: E402
from angel_broker import AngelBroker          # noqa: E402
from notify import Telegram                   # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
STATE_DIR = os.path.join(HERE, "state")
STATE = os.path.join(STATE_DIR, "state.json")
HIST = os.path.join(STATE_DIR, "history.csv")
LOGF = os.path.join(STATE_DIR, f"log_{datetime.now(ZoneInfo('Asia/Kolkata')).date()}.txt")


def log(msg):
    line = f"{datetime.now(IST):%H:%M:%S} IST  {msg}"
    print(line, flush=True)
    with open(LOGF, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_env():
    env = dict(os.environ)
    p = os.path.join(HERE, ".env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    need = ["ANGEL_API_KEY", "ANGEL_CLIENT_CODE", "ANGEL_PIN", "ANGEL_TOTP_SECRET"]
    miss = [k for k in need if not env.get(k)]
    if miss:
        sys.exit(f"Missing in tools/angel/.env: {', '.join(miss)}")
    return env


def load_cfg():
    cfg = dict(tl.DEFAULT_CFG)
    p = os.path.join(HERE, "config.json")
    if os.path.exists(p):
        cfg.update(json.load(open(p)))
    return cfg


def now():
    return datetime.now(IST)


def at(hhmm, d=None):
    h, m = map(int, hhmm.split(":"))
    d = d or now().date()
    return datetime(d.year, d.month, d.day, h, m, tzinfo=IST)


def wait_until(t, tg=None):
    while now() < t:
        if tg:
            tg.poll()
        time.sleep(min(20, max(1, (t - now()).total_seconds())))


def load_history(br: AngelBroker, today: date, git_pull: bool) -> pd.DataFrame:
    """continuous near-month daily bars up to yesterday: repo file (refreshed nightly from NSE
    bhavcopies by GitHub) + bars this bot recorded itself."""
    if git_pull:
        try:
            subprocess.run(["git", "-C", REPO, "pull", "-q", "--ff-only"], timeout=60, check=False)
        except Exception as e:  # noqa: BLE001
            log(f"git pull skipped: {e}")
    repo = pd.read_csv(os.path.join(REPO, "data/futures", br.cfg["symbol"] + ".csv"), index_col=0, parse_dates=True)
    repo = repo[["Open", "High", "Low", "Close"]]
    if os.path.exists(HIST):
        own = pd.read_csv(HIST, index_col=0, parse_dates=True)[["Open", "High", "Low", "Close"]]
        own = own[~own.index.isin(repo.index)]          # official bhavcopy wins
        repo = pd.concat([repo, own]).sort_index()
    hist = repo[repo.index < pd.Timestamp(today)]
    # fill any missing recent days from Angel candles (current contract)
    last = hist.index[-1].date()
    if (today - last).days > 1:
        ref = br.reference_contract(last + timedelta(days=1))
        bars = [b for b in br.daily_bars(ref, last + timedelta(days=1), today - timedelta(days=1)) if last < b[0] < today]
        if bars:
            add = pd.DataFrame([b[1:] for b in bars], index=pd.to_datetime([b[0] for b in bars]), columns=["Open", "High", "Low", "Close"])
            hist = pd.concat([hist, add]).sort_index()
            log(f"filled {len(add)} missing day(s) from Angel: {', '.join(str(d.date()) for d in add.index)}")
    return hist


def reconcile(br: AngelBroker, st: tl.State, tg: Telegram) -> bool:
    if br.dry:
        return True
    held = br.net_qty()
    expect = {st.contract: st.qty} if st.pos != 0 else {}
    if held == expect:
        return True
    # the exchange backstop may have filled while the bot was off
    if st.pos != 0 and not held and st.backstop_id:
        o = br.order(st.backstop_id)
        if o and o["status"] == "complete":
            msg = f"Backstop stop filled @ {o['avg']:,.2f} while the bot was off — now FLAT."
            log(msg); tg.send("⚠️ " + msg)
            if st.trades:
                st.trades[-1].update(ExitDate=str(date.today()), ExitFill=o["avg"], Reason="Backstop")
            st.pos, st.qty, st.contract, st.backstop_id = 0, 0, None, None
            st.save(STATE)
            return True
    msg = f"🚨 Position mismatch — Angel shows {held or 'nothing'}, bot expects {expect or 'flat'}. Bot halted; fix in Angel or run --init."
    log(msg); tg.send(msg)
    return False


def main():
    global STATE, HIST
    args = set(sys.argv[1:])
    os.makedirs(STATE_DIR, exist_ok=True)
    cfg, env = load_cfg(), load_env()
    if cfg.get("dry_run", True):          # dry-run keeps its own book so a pretend trade never leaks into live
        STATE = os.path.join(STATE_DIR, "state_dry.json")
    tg = Telegram(env.get("TELEGRAM_BOT_TOKEN"), env.get("TELEGRAM_CHAT_ID"), log)
    today = now().date()
    if today.weekday() >= 5 and "--check" not in args:
        log("weekend — nothing to do"); return
    br = AngelBroker(cfg, env, log, cache_dir=STATE_DIR)
    br.login()
    try:
        hist = load_history(br, today, git_pull="--no-pull" not in args)
        if "--init" in args or not os.path.exists(STATE):
            st = tl.init_flat_state(hist, cfg)
            st.lots = cfg["lots"]
            st.save(STATE)
            log(f"state initialised FLAT (spent levels: top {st.used_T}, bottom {st.used_B})")
        st = tl.State.load(STATE)
        if st.halted and "--resume" not in args:
            tg.send("Bot is HALTED from an earlier problem. Check Angel, then run with --resume."); log("halted"); return
        st.halted = False
        if not reconcile(br, st, tg):
            return
        day = tl.TradingDay(today, hist, st, cfg, br, tg, tg, log=log, state_path=STATE)
        if "--check" in args:
            print(tl.describe_plan(day.plan, st, cfg)); return
        if now() >= at("15:30"):
            log("market already closed"); return
        wait_until(at("08:55"), tg)
        day.start()
        mode = "DRY RUN (no real orders)" if br.dry else "LIVE"
        tg.send(f"Bot running — {mode}. Commands: /status /stop /flat")
        wait_until(at("09:15") + timedelta(seconds=5), tg)
        ref = day.ref
        q = br.quote(ref)
        tries = 0
        while q["open"] <= 0 and tries < 30:
            time.sleep(10); tries += 1; q = br.quote(ref)
        if q["open"] <= 0 or not br.traded_today(ref):
            log("no trading today (holiday?)"); tg.send("No trading today (exchange holiday?)."); return
        if now() < at("09:17"):
            day.on_open(q)
        else:
            day.late_start(q)
        last_q, stopped = q, False
        roll_t, close_t = at(cfg["roll_time"]), at(cfg["close_check_time"])
        while now() < at("15:29"):
            for cmd in tg.poll():
                if cmd == "/status":
                    tg.send(f"{tl.describe_plan(day.plan, st, cfg)}\nLTP {last_q['ltp']:,.2f}  H {last_q['high']:,.2f}  L {last_q['low']:,.2f}"
                            + ("\n(stopped: no new entries)" if stopped else ""))
                elif cmd == "/stop":
                    stopped = True; day.done_for_day = True
                    tg.send("Stopped: no new entries today. Open position + its stop stay. /flat to exit now.")
                elif cmd == "/flat" and st.pos != 0:
                    day.exit_position("Manual /flat", last_q["ltp"]); day.done_for_day = True; st.save(STATE)
                elif cmd == "/help":
                    tg.send("/status – plan and price\n/stop – no new entries today\n/flat – exit the position now")
            try:
                last_q = br.quote(ref)
            except Exception as e:  # noqa: BLE001
                log(f"quote error {e}"); time.sleep(5); continue
            day.tick(last_q)
            if now() >= roll_t:
                day.roll()
            if now() >= close_t:
                day.before_close(last_q)
            if st.halted:
                break
            time.sleep(cfg["poll_seconds"])
        # ---- after the close: record today's bar
        wait_until(at("15:35"), tg)
        bars = [b for b in br.daily_bars(ref, today, today) if b[0] == today]
        if bars:
            b = bars[-1]; bar = dict(Open=b[1], High=b[2], Low=b[3], Close=b[4])
        else:
            q = br.quote(ref); bar = dict(Open=q["open"], High=q["high"], Low=q["low"], Close=q["ltp"])
        new_hist = day.end_of_day(bar)
        own = pd.read_csv(HIST, index_col=0, parse_dates=True) if os.path.exists(HIST) else pd.DataFrame(columns=["Open", "High", "Low", "Close"])
        own.loc[pd.Timestamp(today)] = [bar["Open"], bar["High"], bar["Low"], bar["Close"]]
        own.sort_index().to_csv(HIST, index_label="Date")
        tomorrow = tl.make_plan(new_hist, st, cfg)
        tg.send(f"Day closed. BN fut close {bar['Close']:,.2f}.\n\n" + tl.describe_plan(tomorrow, st, cfg))
        log("done")
    except Exception:  # noqa: BLE001
        err = traceback.format_exc()
        log(err)
        tg.send("🚨 Bot crashed:\n" + err[-1500:] + "\nThe exchange backstop stop (if in a trade) is still in place.")
        raise
    finally:
        br.logout()


if __name__ == "__main__":
    main()
