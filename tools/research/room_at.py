"""Room above the resistance at the breakout: nearest older peak above it (overhead supply) for given stocks/days (28 Nov 2026)."""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import flag_volume as FV  # noqa: E402

ASK = [("NTPC", "2026-01-29", 345.08), ("TATASTEEL", "2026-05-13", 214.77), ("WELENT", "2026-06-18", 565.22), ("PAGEIND", "2026-06-24", 40384.97),
       ("TITAN", "2026-07-21", 4679.80), ("HCG", "2026-08-10", 688.20)]


def main():
    P = FV.load()
    for sym, d, R in ASK:
        x = P.get(sym)
        if x is None:
            print("R|", sym, "no data"); continue
        h = x.HIGH.to_numpy(float); D = x.index; i = int(np.searchsorted(D.values, np.datetime64(d)))
        pk = [k for k in range(max(2, i - 756), i - 150) if h[k] >= h[max(0, k - 10):k + 11].max() and h[k] > R * 1.01]
        near = min(pk, key=lambda k: h[k]) if pk else None
        ath = h[:i].max(); after = h[i:i + 40].max()
        msg = (f"next older peak {h[near]:,.1f} on {D[near].date()} = room {h[near] / R * 100 - 100:+.1f}%" if near is not None else "no older peak above (3y) - clear sky")
        print(f"R| {sym} {d} | resistance {R:,.1f} | {msg} | all-time high before {ath:,.1f} ({ath / R * 100 - 100:+.1f}%) | "
              f"highest in next 40 sessions {after:,.1f} ({after / R * 100 - 100:+.1f}%)", flush=True)


if __name__ == "__main__":
    main()
