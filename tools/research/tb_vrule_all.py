"""'Proper V' rule (decoded from the course's live record 2019-22) on every live Top Bottom sleeve (28 Nov 2026, Amritpal: "can you
backtest the V rule for other bots we have"). Rule: when the move INTO a top / bottom (from the previous opposite turn) is under L%,
add 0.5% to the entry / stop buffer; a deep V is traded at its level. Honest entry-day stops (exit at the close).
Variants (shown in the 'swing' column of tb_min_swing's output):
  0 = live rules | 1 = V rule L 3%, live buffer kept | 2 = V rule L 3%, no other buffer (as decoded) | 3 = V rule L 5%, live buffer kept"""
import os
import sys
os.environ["FILL"] = "close"; os.environ["SWINGS"] = "0,1,2,3"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tb_min_swing as M  # noqa: E402

V = {0.0: {}, 1.0: dict(vbuf_leg_pct=3.0), 2.0: dict(vbuf_leg_pct=3.0, zero=True), 3.0: dict(vbuf_leg_pct=5.0)}


def trades(df, rules, side, trend, buf_pts, sw):
    kw = dict(V[sw]); zero = kw.pop("zero", False)
    if zero:
        bp, bpct = 0, 0.0
    else:
        bp, bpct = buf_pts, (0.0 if buf_pts else 0.05)
    p = M.tbb.Params(buffer_pct=bpct, buffer_pts=bp, event_exit=False, long_only=side == "buy", day_sl_fill="close", **kw, **rules)
    t = M.tbb.run_live(df, p); t = t[~t.Open] if "Open" in t else t
    if trend and len(t):
        above = (df.Close > df.Close.rolling(200).mean()).to_numpy(); ix = df.index.get_indexer(M.pd.to_datetime(t.EntryDate))
        t = t[[bool(above[max(0, i - 1)]) for i in ix]]
    return t


M.trades = trades
M.main()
