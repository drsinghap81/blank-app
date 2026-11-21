"""Pilot of sector_oi_rrg.py: last ~70 sessions, coverage only."""
import os
import sys

os.environ["PILOT"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sector_oi_rrg  # noqa: E402

sector_oi_rrg.main()
