"""Pilot of sector_obv.py: 200 stocks from 2022; prints only."""
import os
import sys

os.environ["PILOT"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sector_obv  # noqa: E402

sector_obv.main()
