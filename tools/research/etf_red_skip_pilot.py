"""Pilot of etf_red_skip.py: India ETFs + NSE indices only."""
import os
import sys

os.environ["PILOT"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import etf_red_skip  # noqa: E402

etf_red_skip.main()
