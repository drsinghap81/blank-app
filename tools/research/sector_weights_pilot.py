"""Pilot of tools/sector_weights.py (prints, writes nothing)."""
import os
import sys

os.environ["PILOT"] = "1"
sys.path.insert(0, "tools")
import sector_weights  # noqa: E402

sector_weights.main()
