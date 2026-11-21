"""Pilot: fetch the FRED money-market series and print the summary (tools/mmf.py)."""
import os
import sys

sys.path.insert(0, "tools")
os.makedirs("data/scan", exist_ok=True)
import mmf  # noqa: E402

mmf.main()
print("R|", open("data/scan/mmf.json").read()[:600])
