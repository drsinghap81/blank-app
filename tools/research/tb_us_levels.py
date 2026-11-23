"""Today's Top Bottom levels on the US ETFs tested in tb_us.py (24 Nov 2026). Buy only, ETF rules 1/2/2, buffer 0.05%."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tb_asx_levels import main  # noqa: E402

if __name__ == "__main__":
    main(["SMH", "QQQ", "XLF", "XLK", "XLE", "SLV", "SPY", "IWM", "DIA", "GLD", "TLT"], "")
