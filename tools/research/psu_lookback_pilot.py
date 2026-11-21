"""Pilot of psu_lookback.py: a few days only."""
import os
import sys

os.environ["PILOT"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import psu_lookback  # noqa: E402

psu_lookback.main()
