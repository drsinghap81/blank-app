"""9/21 ranking: 3-month strength + a results-season bonus (22 Nov 2026, Amritpal: "Yes"). Engine as rank_by_industry.py
(RED buys skipped). Output data/research/rank_resbonus.json"""
import os
import sys

os.environ.setdefault("RANKS", "r63,r63_res25,r63_res50,results")
os.environ["NO_ATH"] = "1"
os.environ.setdefault("OUT", "data/research/rank_resbonus.json")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rank_by_industry  # noqa: E402

rank_by_industry.main()
