"""Pilot of rank_by_industry.py: 400 stocks, 9/21 only."""
import os
import sys

os.environ["PILOT"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rank_by_industry  # noqa: E402

rank_by_industry.main()
