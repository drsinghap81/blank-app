# Live trading server (AWS) — Angel One orders on tap, moomoo read-only

The phone app's **Live** tab shows the top 8–10 India trades for the next session with final sizes. When the app is connected to this server, it also:
- reads your Angel One cash, holdings and positions;
- sizes each trade within your cash and free slots;
- places one order per **Send**, after you type the quantity to confirm.

The server holds the broker keys. The repo and the phone app never do.

**Safety**
- **Dry run by default.** Send shows the exact Angel order and sends nothing. The **Dry run / Live orders** switch on the Angel card changes this: Live needs your app password again plus the word LIVE typed; Dry run is one tap. The mode is stored on the server (`var/mode.json`, overriding `LIVE_ORDERS` in `.env`); set `ALLOW_APP_LIVE=0` in `.env` to stop the app from turning live on.
- **Only today's plan rows.** There are no free-form orders.
- **Size limits.** Quantity can't exceed the plan size, and value is capped at `MAX_ORDER_VALUE`, 20% of capital and your cash. There are also `MAX_ORDERS_DAY` orders per day, and each row can be sent once a day.
- **Sells only for exits** on stocks you hold, up to the quantity you hold.
- **Fill tracking + protective stop.** Every 2 minutes in market hours (and whenever the app refreshes), the server matches your orders to Angel's order book. Each trade goes **Sent → Filled** (real price and quantity, written to the journal) **→ 🛡 GTT stop placed on Angel**, or Rejected/Cancelled with Angel's reason. The GTT sits on Angel's side for a year, so it works even if this server is down.
  - **9/21 trades:** stop at the plan stop (the 5-day low), as backtested.
  - **ATH trades:** a safety net `ATH_NET_PCT=15`% below the plan stop. The system's own exit is a weekly close below the 30-week SMA. A stop at the SMA would have sold 15% of trades on dips that mostly recovered (−5.5% each); at 15% below, it hits about 1% of trades and costs about 0.16% per trade.
  - The limit is `GTT_LIMIT_GAP_PCT=5`% below the trigger, so a fast fall still fills.
  - Selling from the app cancels the GTT first. If a holding disappears (the GTT fired, or you sold elsewhere), the trade is closed in the journal and counted for the losing-streak pause.
  - Set `PROTECT_STOPS=0` to turn this off.
- **No market orders.** Buys are LIMIT orders: after-market (AMO) in the evening or early morning, or 1% above the live price during market hours, capped at the plan price + 3%. Buy-stops are STOPLOSS_LIMIT orders, sent between 09:15 and 15:30 IST. This follows SEBI's 2026 API rules.
- **Login and logging.** The app password is stored as a salted hash, and the app gets a 12-hour token. Login is blocked for 15 minutes after 5 wrong tries. Every order and dry run is logged in `var/orders.jsonl`.
- **The Top Bottom futures bot (`tools/angel`) is separate** and stays dry-run.

## Portfolio guard (the "portfolio stop-loss")
The guard was tested on the ATH system, 2017–26:
- **The worst fall has been about 20 × the risk per trade** (1% → −20%, 0.75% → −16%, 0.5% → −11%).
- **Lowering risk beat every other drawdown rule.** Cutting size in a drawdown, in Turtle-style or stepped versions, did worse for the same fall. A hard "sell everything at −10%" stop sold near the lows and missed the rebound: 9% a year against 17%, with the same worst fall.

So the guard works like this:
- You set `DD_BUDGET_PCT`, the worst fall you can sit through. Risk per trade is set from a Monte Carlo of the system (2,000 reshuffled 10-year histories): the level at which 95% of paths stayed within the budget (10% → 0.29%, 15% → 0.45%, 20% → 0.6%, 25% → 0.8%, 30% → 1.05%).
- One stock is capped at `MAX_POS_PCT=10`.
- The server tracks your account's high-water mark. It warns at 75% and 100% of the budget, and it never sells for you.
- After `STREAK=5` losing exits in a row, new buys pause for `PAUSE_DAYS=14` (2 weeks). Exits still go through.

## 1. AWS box (about US$5–10 a month)
1. Sign in to <https://lightsail.aws.amazon.com>.
2. **Create instance:**
   - Region **Mumbai (ap-south-1)**.
   - Linux/Unix, **Ubuntu 24.04**.
   - The US$5 plan (1 GB) is enough. Pick US$10 (2 GB) if you'll also run moomoo OpenD.
3. **Networking → Create static IP**, and attach it to the instance.
4. **Networking → IPv4 firewall:** allow **HTTPS 443** and **HTTP 80** (needed for the free certificate). Keep SSH 22.
5. Open the browser SSH console for the instance and run:
   ```
   curl -fsSL https://raw.githubusercontent.com/drsinghap81/blank-app/main/tools/live_server/deploy/setup.sh | sudo bash
   ```
   It prints your **server address** (`https://<ip-with-dashes>.sslip.io`) and the **static IP**.

## 2. Angel SmartAPI
1. Go to <https://smartapi.angelone.in> → **My Apps → Create App** (Trading APIs). Copy the **API key**.
2. Register the **static IP** from step 1 as the app's primary IP. Orders from any other IP are rejected.
3. Enable **TOTP** and copy the text secret behind the QR code.

## 3. Enter your password and Angel keys
In the SSH console (use normal Chrome; **type** the command, because pasting can add hidden `^[[200~` characters), run:
```
sudo setkeys
```
It asks for:
- a new app password, twice
- the Angel API key and client code
- the PIN
- the **TOTP secret**: the ~26–32 character text behind the QR code, not the 6-digit code

Answers marked hidden show nothing while you type. Leave an answer blank to keep the current value. The script saves everything to `/opt/trenddesk/.env`, restarts the server, and leaves `LIVE_ORDERS=0`. Type the keys yourself; don't paste them into chat or GitHub.

## 4. Connect the phone app
1. Open the **Live** tab.
2. Enter the server address and your app password, then tap **Connect**.
3. Check that the Angel card shows your cash and holdings and the **DRY RUN** badge.

## 5. Dry-run week, then go live
- **First:** tap **Send** on a few trades and compare the order it shows (variety, price, quantity) with what you'd place yourself.
- **Going live:** on the Angel card, tap **Live orders**, type your app password and `LIVE`, then tap **Turn on live**. The badge turns red: **LIVE ORDERS**.
- **Every order:** check it in the Angel app. An after-market (AMO) order shows as "AMO" until the open.
- **To stop at any time:** tap **Dry run**. "Log out" only signs the phone out; it doesn't change the server's mode.

## moomoo (optional, read-only)
The Live list is India only (US/ASX backtests showed no edge). moomoo is only read, to show your account value and positions. To set it up:
1. Install **moomoo OpenD** (command-line version for Ubuntu) from moomoo's OpenAPI download page.
2. Log in once with your moomoo ID; its config holds a hashed password.
3. Keep OpenD listening on `127.0.0.1:11111`.
4. In `.env`, set `MOOMOO_ENABLED=1` and `MOOMOO_MARKETS=AU,US`.

The server never unlocks trading on moomoo.

## Files
- `app.py`: the API.
- `brokers.py`: Angel (equity delivery), moomoo (read-only) and a mock broker.
- `test_server.py`: dry-run and guard tests (`python -m pytest tools/live_server/test_server.py`).
- `deploy/setup.sh` and `deploy/trenddesk.service`: one-time install with HTTPS through Caddy (sslip.io hostname); the code updates every weekday at 08:00 IST.
- The plan itself comes from `tools/trade_plan.py` (GitHub Actions, about 21:15 IST) → `data/scan/trade_plan.json`.
