# Archived (28 Nov 2026 clean-up)

Amritpal: "Just keep systems that work. Remove all other" -> "Go, but preserve them somewhere".
The app keeps only the systems in the New mix (Momentum, Cup 9/21, Flags, Pulse, Gold, Top Bottom bots, US / ASX Top Bottom ETFs,
US RSI(2)). Everything else was taken out of the app's screens and daily downloads, not deleted.

## How to get anything back
- The complete code and app as they were before the clean-up: branch `archive/before-cleanup-2026-11-28`
  (`git checkout archive/before-cleanup-2026-11-28 -- docs/app.js` restores the old app file).
- Scheduled scans that were stopped are kept here in `archive/workflows/`; move a file back to `.github/workflows/` to restart it.
- Every backtest stays in the Project docs (claude/*.md) and its script in tools/research/.

## What was archived
| Item | Where it was | Why |
|---|---|---|
| Bottoming out (W, tilted W, triple bottom, inverse H&S) | Strategies card, Today "Chart patterns" row, Bottoms page, trading strip | tested no edge (-1%/yr, -47% worst fall) |
| Breakout retest | Strategies card | weak (7%/yr, -27%) |
| Tight bases / VCP | Strategies card, Today "VCP setups" row | did not beat ATH or 9/21 (strict VCP 7%/yr) |
| 9/21 any stock | Strategies card | switched off already (Cup 9/21 stays) |
| At support | trading strip | fair at best, not in the mix |
| Turtle (stocks, ETFs, MCX) | Today tiles + section, beginner tile, trading strip, Portfolio paper record, Auto row, Bots card | not in the mix; Top Bottom MCX replaced it. The server's Turtle MCX job still manages anything armed or open, and its card / Auto row reappear if so. Scan workflow moved to archive/workflows/turtle-watch.yml |
Downloads no longer made on Today / Portfolio: turtle.json (316 KB), patterns.json, vcp.json.
Still running because other things use them: pattern_scan (it also builds flags.json), trendline_scan (alerts).
