"""Pilot of ath_red_skip.py: 150 stocks, 1 seed; prints only."""
import os
import sys

os.environ["PILOT"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ath_red_skip  # noqa: E402

ath_red_skip.main()
