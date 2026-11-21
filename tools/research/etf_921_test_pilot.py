"""Pilot of etf_921_test.py."""
import os
import sys

os.environ["PILOT"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import etf_921_test  # noqa: E402

etf_921_test.main()
