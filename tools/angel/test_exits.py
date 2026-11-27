"""27 Nov 2026: exit-safety tests for the Top Bottom futures bot (sell first, stop cancelled after; double fills undone).
    cd tools/angel && python3 -m pytest -q test_exits.py"""
import os
import sys
from datetime import date, timedelta

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.dirname(HERE))
import tb_live as tl  # noqa: E402

tl.time.sleep = lambda s: None


class LiveFake:
    """behaves like the live AngelFutures broker: orders, a resting SL, positions."""
    dry = False

    def __init__(self, held=30):
        self.pos = {"OLD": held}; self.orders = {}; self.n = 0; self.log_ = []; self.refuse_exec = False
        self.stop_fills_too = False; self.refuse_modify = False; self.refuse_stop = False; self.px = 63400.0

    def reference_contract(self, today):
        return "OLD"

    def expiry(self, con):
        return date.today()

    def next_contract(self, con):
        return "NEW"

    def lot_size(self, con):
        return 30

    def net_qty(self):
        return {k: v for k, v in self.pos.items() if v}

    def execute(self, con, side, qty, why, must_fill=False):
        self.log_.append(("exec", con, side, qty, why))
        if self.refuse_exec:
            return None
        self.pos[con] = self.pos.get(con, 0) + (qty if side == "BUY" else -qty)
        if self.stop_fills_too:                       # the resting stop fires in the same moment
            self.stop_fills_too = False
            for oid, o in self.orders.items():
                if o["status"] == "trigger pending" and o["con"] == con:
                    o.update(status="complete", filled=o["qty"], avg=self.px - 50)
                    self.pos[con] += (o["qty"] if o["side"] == "BUY" else -o["qty"])
        return self.px

    def stop_limit(self, con, side, qty, trig):
        self.log_.append(("stop", con, side, qty, round(trig, 2)))
        if self.refuse_stop:
            return None
        self.n += 1; oid = f"S{self.n}"
        self.orders[oid] = dict(con=con, side=side, qty=qty, trig=trig, status="trigger pending", filled=0, avg=0.0)
        return oid

    def modify_stop(self, oid, con, side, qty, trig):
        self.log_.append(("modify", oid, round(trig, 2)))
        if self.refuse_modify:
            return False
        self.orders[oid]["trig"] = trig
        return True

    def order(self, oid):
        o = self.orders.get(oid)
        return dict(status=o["status"], avg=o["avg"], filled=o["filled"], text="") if o else None

    def cancel(self, oid, variety="STOPLOSS"):
        self.log_.append(("cancel", oid))
        if oid in self.orders and self.orders[oid]["status"] == "trigger pending":
            self.orders[oid]["status"] = "cancelled"

    def resting(self):
        return [k for k, o in self.orders.items() if o["status"] == "trigger pending"]


class Q:
    def __init__(self):
        self.msgs = []

    def send(self, m):
        self.msgs.append(m)

    def ask(self, *a):
        pass

    def get(self, *a):
        return True


def day(br, held=30):
    cfg = dict(tl.DEFAULT_CFG) if hasattr(tl, "DEFAULT_CFG") else next(v for v in vars(tl).values() if isinstance(v, dict) and "day_sl_pct" in v)
    cfg = dict(cfg, symbol="BANKNIFTY", lots=1)
    idx = pd.bdate_range(end=date.today() - timedelta(days=1), periods=60)
    hist = pd.DataFrame(dict(Open=63000.0, High=63500.0, Low=62500.0, Close=63000.0), index=idx)
    st = tl.State(); st.lots = 1
    st.pos, st.qty, st.entry, st.entry_date, st.contract = 1, held, 63971.8, str(date.today() - timedelta(days=3)), "OLD"
    st.trades = [dict(EntryDate=st.entry_date, Side="BUY", Entry=63971.8, Fill=63965.0, Contract="OLD", Qty=30)]
    q = Q()
    d = tl.TradingDay(date.today(), hist, st, cfg, br, q, q)
    d.save = lambda: None
    st.backstop_id = br.stop_limit("OLD", "SELL", 30, 62700.0)
    return d, st, q


def test_normal_exit_sells_first_then_cancels():
    br = LiveFake(); d, st, q = day(br)
    d.exit_position("Stop", 63332.0)
    kinds = [x[0] for x in br.log_]
    assert kinds.index("exec") < kinds.index("cancel")
    assert st.pos == 0 and br.pos["OLD"] == 0 and not br.resting()


def test_refused_exit_keeps_the_stop():
    br = LiveFake(); br.refuse_exec = True; d, st, q = day(br)
    d.exit_position("Stop", 63332.0)
    assert st.halted and st.pos == 1 and br.resting() == ["S1"]
    assert "still in place" in " ".join(q.msgs)


def test_double_fill_is_undone():
    br = LiveFake(); br.stop_fills_too = True; d, st, q = day(br)
    d.exit_position("Stop", 63332.0)
    assert br.pos["OLD"] == 0, br.pos                    # the extra short was bought back
    assert any(x[0] == "exec" and x[4] == "Undo double fill" for x in br.log_)
    assert "ALSO filled" in " ".join(q.msgs)


def test_stop_filled_first_no_second_sell():
    br = LiveFake(); d, st, q = day(br)
    br.orders["S1"].update(status="complete", filled=30, avg=62650.0); br.pos["OLD"] = 0
    d.exit_position("Stop", 63332.0)
    assert not any(x[0] == "exec" for x in br.log_) and st.pos == 0 and br.pos["OLD"] == 0


def test_hand_square_off_not_doubled():
    br = LiveFake(held=0); d, st, q = day(br)
    d.exit_position("Stop", 63332.0)
    assert not any(x[0] == "exec" for x in br.log_) and br.pos["OLD"] == 0 and st.pos == 0 and not br.resting()


def test_stop_move_modifies_in_place():
    br = LiveFake(); d, st, q = day(br)
    d.place_backstop(63000.0)
    assert br.log_[-1][0] == "modify" and br.resting() == ["S1"]


def test_stop_move_when_modify_refused_new_first():
    br = LiveFake(); br.refuse_modify = True; d, st, q = day(br)
    d.place_backstop(63000.0)
    kinds = [x[0] for x in br.log_]
    assert kinds[-2:] == ["stop", "cancel"] and br.resting() == ["S2"]


def test_new_stop_refused_old_stays():
    br = LiveFake(); br.refuse_modify = True; d, st, q = day(br)
    br.refuse_stop = True
    d.place_backstop(63000.0)
    assert br.resting() == ["S1"] and st.backstop_id == "S1"


def test_roll_keeps_old_stop_until_out_filled():
    br = LiveFake(); d, st, q = day(br)
    d.roll()
    kinds = [(x[0], x[1]) for x in br.log_]
    assert kinds.index(("exec", "OLD")) < kinds.index(("cancel", "S1")) < kinds.index(("exec", "NEW"))
    assert st.contract == "NEW" and br.pos["OLD"] == 0 and br.pos["NEW"] == 30
    assert [br.orders[k]["con"] for k in br.resting()] == ["NEW"]


def test_roll_out_refused_old_stop_stays():
    br = LiveFake(); br.refuse_exec = True; d, st, q = day(br)
    d.roll()
    assert st.halted and br.resting() == ["S1"] and st.contract == "OLD"
