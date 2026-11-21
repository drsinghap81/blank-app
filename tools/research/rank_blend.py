"""9/21 blend ranking test (21 Nov 2026, Amritpal: "All 3"): r63 vs results vs blends of 3-month strength and industry results season.
Same engine as rank_by_industry.py (RED buys skipped). Output data/research/rank_blend.json"""
import os
import sys

os.environ.setdefault("RANKS", "r63,results,blend,blend_m,blend3")
os.environ["NO_ATH"] = "1"
os.environ.setdefault("OUT", "data/research/rank_blend.json")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rank_by_industry  # noqa: E402

rank_by_industry.main()
