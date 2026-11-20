"""Print the option backtest's Pulse slices from the server's public summary (20 Nov 2026)."""
import json
import requests
j = requests.get("https://13-126-118-48.sslip.io/api/research/optbt/summary", timeout=60).json()
r = j.get("results") or {}
print("R| state", j.get("state"), "progress", j.get("progress"), "built", j.get("built"), "version", r.get("version"))
for k in ("index filter (basket)", "filter CE", "filter PE", "BUY, 5 EMA exits, no lull + PCR + BB (the paper trader)"):
    v = r.get(k) or {}
    print("R|", k, {x: v.get(x) for x in ("n", "pnl_rs", "win", "worst_run_rs", "days", "up_days")})
for k, v in (r.get("Pulse") or {}).items():
    print("R| PULSE", k, v if not isinstance(v, dict) else {x: v.get(x) for x in ("n", "pnl_rs", "win", "worst_run_rs", "days", "up_days")})
