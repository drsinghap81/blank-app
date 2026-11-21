"""Pilot of holy_grail.py: 150 stocks; prints only."""
import os
import sys

os.environ["PILOT"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import holy_grail  # noqa: E402

holy_grail.main()
