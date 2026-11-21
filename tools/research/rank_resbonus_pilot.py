"""Pilot of rank_resbonus.py: 400 stocks."""
import os
import sys

os.environ["PILOT"] = "1"
os.environ.setdefault("RANKS", "r63,r63_res25,r63_res50")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rank_by_industry  # noqa: E402

rank_by_industry.main()
