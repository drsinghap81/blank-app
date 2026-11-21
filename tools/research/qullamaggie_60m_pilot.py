"""Pilot of qullamaggie_60m.py: 200 stocks; prints only."""
import os
import sys

os.environ["PILOT"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qullamaggie_60m  # noqa: E402

qullamaggie_60m.main()
