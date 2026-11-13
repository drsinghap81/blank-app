"""Tests for the RSI(2) moomoo bot (no OpenD needed): python -m pytest tools/moomoo_rsi2/test_bot.py -q"""
import datetime as dt
import importlib
import os
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))


@pytest.fixture()
def bot(tmp_path, monkeypatch):
    monkeypatch.setenv('MODE', 'paper'); monkeypatch.setenv('STATE_DIR', str(tmp_path)); monkeypatch.setenv('RSI2_CONFIG', '/nonexistent')
    monkeypatch.setenv('CAPITAL_USD', '10000'); monkeypatch.setenv('SLOTS', '2')
    sys.path.insert(0, HERE); import bot as b; b = importlib.reload(b)
    b.time.sleep = lambda s: None; b.tg = lambda m: None
    return b


def test_threshold_formulas_match_pandas():
    rng = np.random.default_rng(1)
    for _ in range(200):
        c = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.02, 260))))
        d = c.diff(); au = d.clip(lower=0).ewm(alpha=.5, adjust=False).mean().iloc[-2]; ad = (-d).clip(lower=0).ewm(alpha=.5, adjust=False).mean().iloc[-2]
        prev, p = c.iloc[-2], c.iloc[-1]
        d2 = c.diff(); rsi = 100 - 100 / (1 + d2.clip(lower=0).ewm(alpha=.5, adjust=False).mean() / (-d2).clip(lower=0).ewm(alpha=.5, adjust=False).mean())
        bb = prev + ad - 9 * au if ad - 9 * au <= 0 else prev + ad / 9 - au
        assert (p < bb) == (rsi.iloc[-1] < 10)                                                    # buy_below (prep)
        assert (p > c.iloc[-200:-1].sum() / 199) == (p > c.iloc[-200:].mean())                    # SMA200 with today's price
        assert (p > c.iloc[-5:-1].sum() / 4) == (p > c.iloc[-5:].mean())                          # SMA5 with today's price


class FakeBroker:
    def __init__(self):
        self.px = {}; self.low = {}; self.pos = {}; self.orders = {}; self.n = 0; self.day = None

    def close(self):
        pass

    def snapshot(self, syms):
        return {s: dict(last=self.px[s], low=self.low.get(s, self.px[s]), open=self.px[s], prev=100.0, ut=f'{self.day} 15:50:00') for s in syms if s in self.px}

    def positions(self):
        return {k: v for k, v in self.pos.items() if v > 0}

    def cash(self):
        return 1e9

    def place(self, sym, side, qty, otype, price, aux=None, tif='DAY', remark=''):
        self.n += 1; oid = str(self.n)
        if otype == 'STOP':
            self.orders[oid] = dict(sym=sym, qty=qty, stop=aux, status='SUBMITTED', avg=0, dealt=0); return oid
        self.pos[sym] = self.pos.get(sym, 0) + (qty if side == 'BUY' else -qty)
        self.orders[oid] = dict(sym=sym, qty=qty, status='FILLED_ALL', avg=self.px[sym], dealt=qty); return oid

    def order(self, oid):
        o = self.orders[oid]; return dict(status=o['status'], dealt=o['dealt'], avg=o['avg'])

    def cancel(self, oid):
        self.orders[oid]['status'] = 'CANCELLED_ALL'; return True


def prep(day):
    s = dict(close=100.0, sum199=199 * 90.0, sum4=4 * 100.0, au=0.2, ad=3.0, atr14=2.0, liquid=True, above=90.0, exit_above=100.0, buy_below=100 + 3.0 - 1.8)
    return dict(asof=str(day - dt.timedelta(days=1)), stocks={'AAA': dict(s), 'BBB': dict(s), 'OUT': dict(s)})


def step(b, F, day, px):
    F.day = day; F.px.update(px); b.fetch_prep = lambda: prep(day); b.Moomoo = lambda trade=True: F
    b.SIM_NOW = dt.datetime.combine(day, dt.time(15, 50), tzinfo=b.ET); b._run(b.SIM_NOW, day, True)


def test_buy_stop_and_exit(bot):
    F = FakeBroker(); F.pos['OUT'] = 5                     # a holding outside the bot: must never be bought or sold
    d0 = dt.date(2026, 11, 16)
    step(bot, F, d0, dict(AAA=97.0, BBB=98.0, OUT=96.0))   # both below buy_below (101.2), above SMA200 (90)
    S = bot.load_state()
    assert set(S['positions']) == {'AAA', 'BBB'} and F.pos['OUT'] == 5
    assert S['positions']['AAA']['stop'] == 97.0 - 6.0 and S['positions']['AAA']['qty'] == 51       # 5000 / 97
    # day 2: AAA's stop fills intraday at the broker; BBB rallies above SMA5 -> sold at the run
    o = next(o for o in F.orders.values() if o['sym'] == 'AAA' and 'stop' in o); o.update(status='FILLED_ALL', avg=91.0, dealt=o['qty']); F.pos['AAA'] = 0
    step(bot, F, d0 + dt.timedelta(days=1), dict(AAA=102.0, BBB=101.0, OUT=96.0))   # AAA no longer oversold: not re-bought
    S = bot.load_state()
    assert S['positions'] == {} and S['trades'] == 2 and F.pos['OUT'] == 5
    assert round(S['realized'], 2) == round(51 * (91 - 97) + 51 * (101 - 98), 2)
    assert all(o['status'] != 'SUBMITTED' for o in F.orders.values())   # BBB's stop was cancelled when it was sold


def test_seven_day_exit_and_pause(bot, tmp_path):
    F = FakeBroker(); d = dt.date(2026, 11, 16)
    open(os.path.join(tmp_path, 'PAUSE'), 'w').write('x')
    step(bot, F, d, dict(AAA=97.0, BBB=150.0, OUT=150.0)); assert bot.load_state()['positions'] == {}     # paused: no buys
    os.remove(os.path.join(tmp_path, 'PAUSE'))
    step(bot, F, d + dt.timedelta(days=1), dict(AAA=97.0)); assert 'AAA' in bot.load_state()['positions']
    for k in range(2, 9):                                  # stays below SMA5; sold on the 7th trading day after entry
        step(bot, F, d + dt.timedelta(days=k), dict(AAA=95.0 + 0 * k))
    assert bot.load_state()['positions'] == {}
    assert '7 days' in open(os.path.join(tmp_path, 'journal_paper.csv')).read()


def test_live_needs_confirmation(tmp_path):
    env = dict(os.environ, MODE='live', STATE_DIR=str(tmp_path), RSI2_CONFIG='/nonexistent', LIVE_CONFIRM='', MOOMOO_TRADE_PWD='')
    r = subprocess.run([sys.executable, os.path.join(HERE, 'bot.py'), 'run'], env=env, capture_output=True, text=True)
    assert r.returncode != 0 and 'LIVE_CONFIRM' in (r.stderr + r.stdout)
