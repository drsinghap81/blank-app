"""Pilot of shannon_avwap.py: 200 stocks; prints only."""
import os
import sys

os.environ["PILOT"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import shannon_avwap  # noqa: E402

shannon_avwap.main()
