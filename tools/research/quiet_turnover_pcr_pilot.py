"""Pilot of quiet_turnover_pcr.py."""
import os
import sys

os.environ["PILOT"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import quiet_turnover_pcr  # noqa: E402

quiet_turnover_pcr.main()
