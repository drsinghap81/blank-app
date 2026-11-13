# US RSI(2) dip-buy bot for moomoo

Buys short, sharp dips in S&P 500 stocks that are in long-term uptrends, and sells on the first bounce.
Backtest 2010–2026 (project note `connors-rsi2-us-test.md`): 11%/yr alone, −26% worst fall, 66% winners;
50/50 with US momentum it cut the worst fall roughly in half.

## Rules
- Universe: S&P 500, 50-day average volume above 2 million shares.
- Buy ~10 minutes before the close when price > 200-day average and RSI(2) < 10 (lowest RSI first, 10 slots).
- Sell ~10 minutes before the close when price > 5-day average, or after 7 trading days.
- Protective stop: entry − 3 × ATR(14), placed at moomoo as a GTC stop order.

## How it runs
1. `rsi2-prep` GitHub job (after every US close) writes `data/scan/us/rsi2.json`: per stock, the levels needed to apply
   the rules to a live price (no long price history needed on your machine). The app's US Today page shows the same list.
2. `bot.py run` at **15:50 New York time**, Mon–Fri, on the machine running moomoo **OpenD** (your PC or the server).
   It checks stops that filled during the day, sells exits, then buys new signals, and waits up to 90 s for each fill.
3. Everything goes to `journal_<mode>.csv`, `state_<mode>.json` and Telegram (optional).

## Setup
1. Install and log in to **moomoo OpenD** (moomoo's API gateway) and keep it running. You log in yourself.
2. `pip install moomoo-api` (Python 3.9+).
3. `cp config.example.env config.env` and edit.
4. `python bot.py selftest` — checks OpenD, the prep file and (paper/live) the account.
5. Schedule (Linux cron; the CRON_TZ line makes it follow New York time, including daylight saving):
   ```
   CRON_TZ=America/New_York
   50 15 * * 1-5  cd /path/to/tools/moomoo_rsi2 && /usr/bin/python3 bot.py run >> bot.log 2>&1
   ```
   On Windows use Task Scheduler at the matching Melbourne time (7:50 am in Australian summer, 5:50 am in winter — check
   when the clocks change in either country).

## Going live, in stages
| Stage | MODE | What happens | Move on when |
|---|---|---|---|
| 1 | `dry` | No orders. Simulated fills at the live price. | A week of runs with no errors |
| 2 | `paper` | Real orders in moomoo's paper account | 4–8 weeks; fills and results match the app list |
| 3 | `live` | Real money. Needs `LIVE_CONFIRM=YES_REAL_MONEY` and `MOOMOO_TRADE_PWD` in the environment | You decide |

## Safety
- Only sells shares the bot bought (its state file); never touches your other holdings; skips stocks you already hold.
- At most `MAX_NEW_PER_DAY` buys a day; buy orders are limits (live price + 0.5%).
- Create a file named `PAUSE` in this folder to stop new buys (exits still run). The bot creates it itself if the book
  falls `MAX_DD_PCT` below its peak; delete it to resume.
- Skips the day if prices aren't updating (holiday, early close) and refuses stale prep files.
- If moomoo refuses the stop order (for example in paper trading), the bot checks the stop itself at each run.

## Known differences from the backtest
- Decisions use the 15:50 price, not the exact close; a few signals change in the last 10 minutes.
- The backtest could sell a stock on its stop and buy it back the same day; the bot waits a day.
- Replayed day by day on 7 years of real prices with a simulated broker, the bot took 97% of the backtest's trades with
  realised P&L within 2% (scratch replay, 14 Nov 2026). Unit tests: `python -m pytest tools/moomoo_rsi2/test_bot.py`.
- Early-close days (13:00): the bot skips the day.
