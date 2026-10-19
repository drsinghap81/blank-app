# Top Bottom live bot — Angel One (BankNifty futures)

Trades the Top Bottom system on BankNifty near-month futures through Angel One SmartAPI,
with the same rules as the backtest and the paper bot (`tools/topbottom_backtest.py`, `tools/paper_bot.py`).

**How it trades**
- Watches the near-month future from 09:15 to 15:29 IST, every 2 seconds.
- **Entries:** sell when price trades below the previous bottom − 25, buy when it trades above the previous top + 25. Each level is used once. If the market opens more than 2% beyond a level, no trade.
- **Orders:** marketable LIMIT orders, re-priced until filled. SEBI's 2026 rules ban market and IOC orders for API algos, so the bot never uses them.
- **Stops:**
  - Entry day: a real 1% stop.
  - After that: the system point (the opposite level), capped at 2% from entry. It moves to breakeven once the trade has been 2% in profit.
  - When the system-point stop hits, the bot exits and reverses (stop-and-reverse), unless the market opened more than 2% beyond it.
- **Backstop:** while in a trade, a STOPLOSS_LIMIT order rests at the exchange 0.5% beyond the bot's stop. It protects you if the laptop or internet dies.
- **Expiry day:** an open position is rolled at 15:10 IST. New entries that day go into next month's contract.
- **Approvals:** before the open, Telegram asks **Approve / Skip** for each entry and for a reversal. If you don't answer, the bot skips (configurable).

**Checked:** replaying 2024–2026 through this exact code gives the same 147 trades as the backtest engine (`python tools/angel/sim_check.py 2024-01-01`).

---

## One-time setup

### 1. Angel SmartAPI app and static IP
1. Log in at <https://smartapi.angelone.in> → **My Apps → Create / Add App** (type "Trading APIs"). Note the **API key**.
2. **Static IP:** API orders are only accepted from the IP registered in that app (one primary, one optional backup; it can be changed once a week).
   - Find your IP: open <https://api.ipify.org> on the laptop.
   - Most home broadband IPs **change**. Ask your internet provider for a static IP. Otherwise, run the bot on a small cloud server in Mumbai with a fixed IP; ask me for those steps.
3. **TOTP:** in SmartAPI, enable TOTP. When the QR code is shown, also copy the **text secret** (the key behind the QR). Add it to Google Authenticator as well, so you keep it.

### 2. Telegram (needed for Approve/Skip)
1. In Telegram, message **@BotFather** → `/newbot` → copy the **token**.
2. Send any message to your new bot. Then open `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and copy `"chat":{"id": ...}`. That number is your **chat id**.

### 3. Install on the laptop
```
git clone https://github.com/drsinghap81/blank-app.git
cd blank-app
python -m pip install -r tools/angel/requirements.txt
```
Copy `tools/angel/.env.example` to `tools/angel/.env` and fill in the six values.
Copy `tools/angel/config.example.json` to `tools/angel/config.json`.
These files stay on your laptop: they are git-ignored and never uploaded.

### 4. Test
```
python tools/angel/run_bot.py --check
```
This logs in, lists the BankNifty contracts and prints today's plan.

---

## Daily running

Run `python tools/angel/run_bot.py` on weekdays before **08:55 IST**. Starting at **1:00 PM Melbourne time** works all year. The bot waits for the open, trades, records the day's bar after 15:35 IST and exits. Keep the laptop awake and online until about **9:10 PM Melbourne (summer) / 8:10 PM (winter)**.

- **Windows:** Task Scheduler → Create Basic Task → Weekly, Mon–Fri, 1:00 PM → Start a program:
  - Program: `python`
  - Arguments: `tools\angel\run_bot.py`
  - Start in: the `blank-app` folder

  Tick "Wake the computer to run this task" (Conditions tab).
- **Mac:** `crontab -e` and add `0 13 * * 1-5 cd ~/blank-app && /usr/bin/python3 tools/angel/run_bot.py >> tools/angel/state/cron.log 2>&1`. Set Energy settings so the Mac doesn't sleep.

**Telegram commands:** `/status` (plan and live price), `/stop` (no new entries today), `/flat` (exit the position now), `/help`.

## Going live
1. Keep `"dry_run": true` for 2–3 sessions. It uses real Angel prices and logins but sends **no orders**, and it keeps a separate book, `state/state_dry.json`.
2. Check its Telegram messages against the paper bot's daily levels.
3. Set `"dry_run": false` and run `python tools/angel/run_bot.py --init` once **before the open**. This starts the live book flat. From then on, a scheduled run does the rest.

**Margin:** 2 lots of BankNifty futures need roughly ₹2.5–3 lakh, plus a buffer for losses.

## Safety checks built in
- At start the bot compares Angel's actual BankNifty futures position with its own record. If they differ, it **halts** and messages you. If the exchange backstop filled while the bot was off, it notices this and records you as flat.
- If an exit can't be filled, the bot halts and tells you to close the position manually.
- Everything is logged in `tools/angel/state/log_<date>.txt`, and trades are kept in `state/state.json`.
- If the laptop is off on a day you hold a position, there is **no stop** that day (backstops are day orders). The paper bot's nightly Telegram message is a second check.

Not investment advice. Futures trading can lose more than the margin deposited.
