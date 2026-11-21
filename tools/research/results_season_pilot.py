"""Pilot of results_season.py: 300 stocks from 2021."""
import os
import sys

os.environ["PILOT"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import results_season  # noqa: E402

results_season.main()
