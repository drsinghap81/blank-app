"""US option liquidity for the short-watch names (15 Nov 2026). For each US stock / ETF on the short watch (ath.json week/day
short, funds.json US ETFs with a support break): the first monthly-ish expiry 14+ days out, at-the-money call and put
bid-ask spread (% of mid), volume and open interest across the chain. Grade (judgement, not a test):
  liquid = ATM spread <= 3% and chain OI >= 10,000;  fair = spread <= 8% and OI >= 1,000;  thin = otherwise / no options.
Yahoo option data (delayed). -> data/scan/us/opt_liq.json"""
import json, time
from datetime import datetime, timezone, timedelta
import yfinance as yf

syms = set()
try:
    a = json.load(open("data/scan/us/ath.json"))
    syms |= {r["symbol"] for r in a.get("week_short", []) + a.get("day_short", [])}
except Exception as e:  # noqa: BLE001
    print("ath", e)
try:
    f = json.load(open("data/scan/funds.json"))
    syms |= {str(r.get("symbol") or r["key"]).replace("US:", "") for r in f["rows"] if r.get("market") == "US" and (r.get("wshort") or r.get("dshort"))}
except Exception as e:  # noqa: BLE001
    print("funds", e)
out = {}
for s in sorted(syms):
    try:
        t = yf.Ticker(s.replace(".", "-")); exps = t.options
        if not exps:
            out[s] = dict(grade="none"); continue
        today = datetime.now(timezone.utc).date()
        e = next((x for x in exps if (datetime.strptime(x, "%Y-%m-%d").date() - today).days >= 14), exps[-1])
        ch = t.option_chain(e); px = t.fast_info.get("lastPrice") or t.history(period="5d").Close.iloc[-1]
        oi = int(ch.calls.openInterest.fillna(0).sum() + ch.puts.openInterest.fillna(0).sum())
        vol = int(ch.calls.volume.fillna(0).sum() + ch.puts.volume.fillna(0).sum())
        sp = []
        for side in (ch.calls, ch.puts):
            k = side.iloc[(side.strike - px).abs().argsort()[:1]]
            b, a_ = float(k.bid.iloc[0] or 0), float(k.ask.iloc[0] or 0)
            if a_ > 0 and b > 0:
                sp.append((a_ - b) / ((a_ + b) / 2) * 100)
        spr = round(max(sp), 1) if sp else None
        if spr is None or spr > 40:     # weekend / stale quotes (bid 0 or absurd spread): grade on open interest alone
            spr = None; g = "liquid" if oi >= 20000 else "fair" if oi >= 2000 else "thin"
        else:
            g = "liquid" if spr <= 3 and oi >= 10000 else "fair" if spr <= 8 and oi >= 1000 else "thin"
        out[s] = dict(grade=g, expiry=e, atm_spread_pct=spr, chain_oi=oi, chain_vol=vol, price=round(float(px), 2))
        time.sleep(0.5)
    except Exception as ex:  # noqa: BLE001
        print("fail", s, str(ex)[:80])
json.dump(dict(generated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), rows=out), open("data/scan/us/opt_liq.json", "w"), indent=0)
print(len(out), "symbols", {k: v["grade"] for k, v in out.items()})
