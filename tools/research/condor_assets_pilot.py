"""Pilot of condor_assets.py: gold, natural gas, Reliance from 2019."""
import os
import sys

os.environ["PILOT"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import condor_assets  # noqa: E402

condor_assets.main()
