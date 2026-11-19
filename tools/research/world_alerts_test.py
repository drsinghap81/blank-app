"""Backtest the index-W and EMA 9 lift-off alerts on US, ASX and UK (19 Nov 2026). See tools/world_alerts.py."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import world_alerts  # noqa: E402

for mk in ("US", "ASX", "UK"):
    try:
        world_alerts.test(mk)
    except Exception as e:  # noqa: BLE001
        print("R|", mk, "failed", e, flush=True)
