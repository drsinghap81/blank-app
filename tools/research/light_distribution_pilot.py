"""Pilot of light_distribution.py: 150 stocks (9/21 + ATH), 60 Nifty 500 names (bottoms); prints only, writes nothing."""
import os
import sys

os.environ["PILOT"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import light_distribution  # noqa: E402

light_distribution.main()
