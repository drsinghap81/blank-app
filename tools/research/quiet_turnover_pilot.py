"""Pilot of quiet_turnover.py."""
import os
import sys

os.environ["PILOT"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import quiet_turnover  # noqa: E402

quiet_turnover.main()
