"""Pilot of e50_rising_test.py: 400 stocks."""
import os
import sys

os.environ["PILOT"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import e50_rising_test  # noqa: E402

e50_rising_test.main()
