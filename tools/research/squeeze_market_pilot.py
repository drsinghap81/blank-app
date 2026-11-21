"""Pilot of squeeze_market.py: FII data Aug-Nov 2026 only."""
import os
import sys

os.environ["PILOT"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import squeeze_market  # noqa: E402

squeeze_market.main()
