"""Print the option backtest's state and its v9 'Sector green' slices from the server's public summary (23 Nov 2026)."""
import requests
h = requests.get("https://13-126-118-48.sslip.io/api/health", timeout=30).json()
print("R| health", {k: h.get(k) for k in ("version", "latest", "update_waiting", "mode")})
j = requests.get("https://13-126-118-48.sslip.io/api/research/optbt/summary", timeout=60).json()
r = j.get("results") or {}
print("R| state", j.get("state"), "progress", j.get("progress"), "running", j.get("running"), "built", j.get("built"), "version", r.get("version"))
for k, v in (r.get("Sector green") or {}).items():
    print("R| SECTOR", k, {x: v.get(x) for x in ("n", "pnl_rs", "total_R", "avg_R", "win", "worst_dd_R", "days", "up_days", "total_return_on_max_peak_pct")})
