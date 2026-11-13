"""US RSI(2) trend-pullback bot for moomoo (OpenAPI via OpenD). 14 Nov 2026.

Rules (backtest: project note connors-rsi2-us-test.md):
  S&P 500 stock, 50-day avg volume > 2M, price > SMA200, RSI(2) < 10  -> buy ~10 min before the close (lowest RSI first)
  exit ~10 min before the close when price > SMA5, or after 7 trading days; protective stop entry - 3 x ATR(14) (GTC at moomoo)
  10 slots x (CAPITAL_USD + realised P&L) / 10.

Levels come from data/scan/us/rsi2.json (GitHub job tools/rsi2_prep.py, built after each US close), live prices from OpenD.

Modes (MODE in the config file / environment):
  dry    (default) quotes from OpenD, no orders at all; fills simulated at the live price; journal + state kept.
  paper  moomoo simulated account (TrdEnv.SIMULATE) — real orders in paper money.
  live   real account — needs LIVE_CONFIRM=YES_REAL_MONEY and MOOMOO_TRADE_PWD set in the environment (never in code).

Safety: the bot only ever sells shares it bought itself (state file), never touches other holdings, skips stocks you already
hold outside the bot, caps new buys per day, stops buying after a drawdown limit, and a file named PAUSE next to the state
file stops new buys (exits still run). Every order and fill goes to the journal and to Telegram if configured.

Usage:  python bot.py run [--force]     # schedule at 15:50 New York time, Mon-Fri
        python bot.py status | selftest
"""
import csv
import datetime as dt
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

ET = ZoneInfo('America/New_York')
HERE = os.path.dirname(os.path.abspath(__file__))


def load_cfg():
    cfg = dict(MODE='dry', OPEND_HOST='127.0.0.1', OPEND_PORT='11111', FIRM='FUTUAU', ACC_ID='0', CAPITAL_USD='10000', SLOTS='10',
               MAX_NEW_PER_DAY='5', MAX_DD_PCT='35', LIMIT_BUFFER_PCT='0.5', STATE_DIR=HERE,
               PREP_URL='https://raw.githubusercontent.com/drsinghap81/blank-app/main/data/scan/us/rsi2.json',
               TG_TOKEN='', TG_CHAT='', LIVE_CONFIRM='', MOOMOO_TRADE_PWD='')
    f = os.environ.get('RSI2_CONFIG', os.path.join(HERE, 'config.env'))
    if os.path.exists(f):
        for line in open(f):
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1); cfg[k.strip()] = v.strip()
    for k in list(cfg):                       # environment wins (keep secrets there)
        if os.environ.get(k):
            cfg[k] = os.environ[k]
    return cfg


C = load_cfg()
MODE = C['MODE'].lower()
SLOTS, CAPITAL, MAX_NEW = int(C['SLOTS']), float(C['CAPITAL_USD']), int(C['MAX_NEW_PER_DAY'])
STATE = os.path.join(C['STATE_DIR'], f'state_{MODE}.json')
JOURNAL = os.path.join(C['STATE_DIR'], f'journal_{MODE}.csv')
PAUSE = os.path.join(C['STATE_DIR'], 'PAUSE')
LOCK = os.path.join(C['STATE_DIR'], f'.lock_{MODE}')


def code(sym):            # BRK-B -> US.BRK.B
    return 'US.' + sym.replace('-', '.')


def tg(msg):
    print(msg)
    if C['TG_TOKEN'] and C['TG_CHAT']:
        try:
            data = urllib.parse.urlencode(dict(chat_id=C['TG_CHAT'], text=f'[RSI2 {MODE}] {msg}')).encode()
            urllib.request.urlopen(f"https://api.telegram.org/bot{C['TG_TOKEN']}/sendMessage", data, timeout=15)
        except Exception as e:  # noqa: BLE001
            print('telegram failed:', e)


SIM_NOW = None      # replay tests set this; normal runs use the clock


def now_et():
    return SIM_NOW or dt.datetime.now(ET)


def journal(**kw):
    new = not os.path.exists(JOURNAL)
    with open(JOURNAL, 'a', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['time_et', 'mode', 'action', 'sym', 'qty', 'price', 'stop', 'reason', 'order_id', 'pnl'])
        if new:
            w.writeheader()
        w.writerow({k: kw.get(k, '') for k in w.fieldnames} | dict(time_et=now_et().strftime('%Y-%m-%d %H:%M:%S'), mode=MODE))


def load_state():
    if os.path.exists(STATE):
        return json.load(open(STATE))
    return dict(positions={}, realized=0.0, peak=CAPITAL, last_run='', trades=0, wins=0)


def save_state(S):
    tmp = STATE + '.tmp'; json.dump(S, open(tmp, 'w'), indent=1); os.replace(tmp, STATE)


def fetch_prep():
    with urllib.request.urlopen(C['PREP_URL'] + f'?t={int(time.time())}', timeout=60) as r:
        return json.loads(r.read().decode())


# ---------------------------------------------------------------- brokers
class Moomoo:
    """Thin wrapper over the moomoo SDK. paper -> TrdEnv.SIMULATE, live -> TrdEnv.REAL (after unlock)."""

    def __init__(self, trade=True):
        try:
            import moomoo as m
        except ImportError:          # futu-api speaks the same OpenD protocol
            import futu as m
        self.m = m
        host, port = C['OPEND_HOST'], int(C['OPEND_PORT'])
        self.q = m.OpenQuoteContext(host=host, port=port)
        self.t = None
        if trade:
            self.env = m.TrdEnv.REAL if MODE == 'live' else m.TrdEnv.SIMULATE
            self.t = m.OpenSecTradeContext(filter_trdmarket=m.TrdMarket.US, host=host, port=port, security_firm=getattr(m.SecurityFirm, C['FIRM']))
            self.acc = int(C['ACC_ID'])
            if MODE == 'live':
                ret, d = self.t.unlock_trade(password=C['MOOMOO_TRADE_PWD'])
                if ret != m.RET_OK:
                    raise RuntimeError(f'unlock_trade failed: {d}')

    def close(self):
        for x in (self.q, self.t):
            if x is not None:
                x.close()

    def _ok(self, ret, d, what):
        if ret != self.m.RET_OK:
            raise RuntimeError(f'{what}: {d}')
        return d

    def snapshot(self, syms):
        out = {}
        for i in range(0, len(syms), 380):
            part = syms[i:i + 380]
            d = self._ok(*self.q.get_market_snapshot([code(s) for s in part]), 'snapshot')
            for r in d.itertuples():
                s = r.code[3:].replace('.', '-')
                out[s] = dict(last=float(r.last_price), low=float(r.low_price), open=float(r.open_price), prev=float(r.prev_close_price), ut=str(r.update_time))
        return out

    def positions(self):
        d = self._ok(*self.t.position_list_query(trd_env=self.env, acc_id=self.acc, refresh_cache=True), 'positions')
        return {r.code[3:].replace('.', '-'): float(r.qty) for r in d.itertuples() if r.code.startswith('US.') and float(r.qty) > 0}

    def cash(self):
        d = self._ok(*self.t.accinfo_query(trd_env=self.env, acc_id=self.acc, refresh_cache=True, currency=self.m.Currency.USD), 'accinfo')
        r = d.iloc[0]
        for k in ('us_cash', 'cash', 'power'):
            try:
                v = float(r[k])
                if v == v:
                    return v
            except (KeyError, TypeError, ValueError):
                pass
        return 0.0

    def place(self, sym, side, qty, otype, price, aux=None, tif='DAY', remark='rsi2'):
        m = self.m
        d = self._ok(*self.t.place_order(price=price, qty=qty, code=code(sym), trd_side=getattr(m.TrdSide, side), order_type=getattr(m.OrderType, otype),
                                         trd_env=self.env, acc_id=self.acc, time_in_force=getattr(m.TimeInForce, tif), aux_price=aux, remark=remark), f'place {side} {sym}')
        return str(d['order_id'].iloc[0])

    def order(self, oid):
        d = self._ok(*self.t.order_list_query(order_id=oid, trd_env=self.env, acc_id=self.acc, refresh_cache=True), 'order')
        if d.empty:
            d = self._ok(*self.t.history_order_list_query(trd_env=self.env, acc_id=self.acc), 'history orders'); d = d[d.order_id == oid]
        if d.empty:
            return dict(status='UNKNOWN', dealt=0.0, avg=0.0)
        r = d.iloc[0]
        return dict(status=str(r.order_status), dealt=float(r.dealt_qty or 0), avg=float(r.dealt_avg_price or 0))

    def cancel(self, oid):
        m = self.m
        ret, d = self.t.modify_order(m.ModifyOrderOp.CANCEL, oid, 0, 0, trd_env=self.env, acc_id=self.acc)
        return ret == m.RET_OK


class Dry:
    """No orders: fills at the live price, stops checked against the day's low at each run."""

    def __init__(self, quote):
        self.quote, self.n = quote, 0

    def close(self):
        self.quote.close()

    def snapshot(self, syms):
        return self.quote.snapshot(syms)

    def positions(self):
        return {}

    def cash(self):
        return float('inf')

    def place(self, sym, side, qty, otype, price, aux=None, tif='DAY', remark=''):
        self.n += 1; return f'dry-{self.n}'

    def order(self, oid):
        return dict(status='FILLED_ALL', dealt=None, avg=None)

    def cancel(self, oid):
        return True


# ---------------------------------------------------------------- logic
def wait_fill(B, oid, qty, secs=90):
    t0 = time.time(); o = B.order(oid)
    while o['status'] not in ('FILLED_ALL', 'CANCELLED_ALL', 'CANCELLED_PART', 'FAILED', 'DELETED') and time.time() - t0 < secs:
        time.sleep(5); o = B.order(oid)
    if o['status'] not in ('FILLED_ALL', 'CANCELLED_ALL', 'CANCELLED_PART', 'FAILED', 'DELETED'):
        B.cancel(oid); time.sleep(2); o = B.order(oid)
    return o


def place_stop(B, sym, qty, stop):
    """GTC stop-market sell at moomoo; if refused (e.g. not offered in paper trading) the bot checks the stop at each run."""
    try:
        return B.place(sym, 'SELL', qty, 'STOP', stop, aux=stop, tif='GTC')
    except Exception as e:  # noqa: BLE001
        tg(f'{sym}: stop order refused ({e}); the bot will check {stop:.2f} at each run instead.'); return None


def rsi_now(p, s):
    au = (s['au'] + max(p - s['close'], 0)) / 2; ad = (s['ad'] + max(s['close'] - p, 0)) / 2
    return 100.0 if ad == 0 else 100 - 100 / (1 + au / ad)


def run(force=False):
    now = dt.datetime.now(ET); today = now.date()
    if not force and not (now.weekday() < 5 and dt.time(15, 40) <= now.time() <= dt.time(15, 58)):
        print('Outside the 15:40-15:58 New York window; use --force to override.'); return
    if os.path.exists(LOCK) and time.time() - os.path.getmtime(LOCK) < 900:
        print('Another run is active.'); return
    open(LOCK, 'w').write(str(os.getpid()))
    try:
        _run(now, today, force)
    except Exception as e:  # noqa: BLE001
        tg(f'ERROR: {e}'); journal(action='error', reason=str(e)[:200]); raise
    finally:
        if os.path.exists(LOCK):
            os.remove(LOCK)


def _run(now, today, force):
    S = load_state()
    if S.get('last_run') == str(today) and not force:
        print('Already ran today.'); return
    P = fetch_prep(); asof = dt.date.fromisoformat(P['asof'])
    if not (asof < today and (today - asof).days <= 5):
        tg(f'Prep file is stale (as of {asof}); no new buys today, exits still checked.'); stale = True
    else:
        stale = False
    ST = P['stocks']
    B = Dry(Moomoo(trade=False)) if MODE == 'dry' else Moomoo(trade=True)
    try:
        held = S['positions']
        snap = B.snapshot(sorted(set(ST) | set(held)))
        fresh = [v for v in snap.values() if v['ut'][:10] == str(today)]
        if len(fresh) < 0.8 * max(len(snap), 1):
            tg('Market looks closed (no fresh prices today); nothing done.'); return
        if not force:   # early-close days: prices stop updating at 13:00
            uts = sorted(v['ut'] for v in fresh)
            last_ut = dt.datetime.fromisoformat(uts[len(uts) // 2]).replace(tzinfo=ET)
            if (now - last_ut).total_seconds() > 900:
                tg('Prices are not updating (early close or halt); nothing done.'); return
        broker_pos = B.positions() if MODE != 'dry' else {}
        msgs = []
        # 1) positions closed by the GTC stop since the last run
        for sym, p in list(held.items()):
            if MODE == 'dry':
                lo = snap.get(sym, {}).get('low')
                if lo and lo <= p['stop'] and p.get('last_seen') != str(today):
                    px = min(snap[sym]['open'], p['stop']); close_pos(S, sym, px, 'stop (simulated on today\'s low)', msgs); continue
            elif broker_pos.get(sym, 0) < p['qty'] - 1e-9:
                o = B.order(p['stop_id']) if p.get('stop_id') else dict(status='sold outside the bot', avg=0)
                px = o['avg'] or (p['stop'] if p.get('stop_id') else snap.get(sym, {}).get('last') or p['stop'])
                close_pos(S, sym, px, f"stop filled ({o['status']})" if p.get('stop_id') else 'sold outside the bot', msgs, qty=p['qty'] - broker_pos.get(sym, 0))
        # 2) exits: price above SMA5, or 7 trading days
        for sym, p in list(held.items()):
            q = snap.get(sym); s = ST.get(sym)
            if not q:
                continue
            p['days'] = p.get('days', 0) + (1 if p.get('last_seen') != str(today) else 0); p['last_seen'] = str(today)
            above5 = (q['last'] > s['exit_above']) if s else False
            bot_stop = MODE != 'dry' and not p.get('stop_id') and q['last'] <= p['stop']     # broker stop missing -> checked here
            if above5 or p['days'] >= 7 or bot_stop:
                if p.get('stop_id'):
                    B.cancel(p['stop_id'])
                oid = B.place(sym, 'SELL', p['qty'], 'MARKET', q['last'])
                o = wait_fill(B, oid, p['qty']) if MODE != 'dry' else dict(status='FILLED_ALL', dealt=p['qty'], avg=q['last'])
                if o['dealt']:
                    close_pos(S, sym, o['avg'] or q['last'], 'close > SMA5' if above5 else '7 days' if p['days'] >= 7 else 'stop (bot check)', msgs, qty=o['dealt'], oid=oid)
                if sym in held:   # not (fully) sold: put a stop back on what is left
                    tg(f'{sym}: exit order {o["status"]}, {held[sym]["qty"]} shares still held — check the app.')
                    if MODE != 'dry':
                        held[sym]['stop_id'] = place_stop(B, sym, held[sym]['qty'], held[sym]['stop'])
        # 3) entries
        equity = CAPITAL + S['realized'] + sum(p['qty'] * (snap.get(s, {}).get('last') or p['entry']) - p['qty'] * p['entry'] for s, p in held.items())
        if S.get('dd_paused') and not os.path.exists(PAUSE):      # you removed PAUSE after a drawdown stop -> resume, new peak
            S['dd_paused'] = False; S['peak'] = equity; tg('Resumed after the drawdown pause; peak reset.')
        S['peak'] = max(S.get('peak', CAPITAL), equity); dd = (equity / S['peak'] - 1) * 100
        if dd <= -float(C['MAX_DD_PCT']) and not S.get('dd_paused'):
            S['dd_paused'] = True; open(PAUSE, 'w').write(f'drawdown {dd:.1f}% on {today}\n')
            tg(f'Book is {dd:.1f}% below its peak (limit {C["MAX_DD_PCT"]}%). New buys PAUSED; open trades still exit normally. '
               f'Review, then delete the PAUSE file to resume.')
        block = 'PAUSE file present' if os.path.exists(PAUSE) else 'prep file stale' if stale else ''
        cands = []
        for sym, s in ST.items():
            q = snap.get(sym)
            if not q or sym in held or sym in broker_pos or q['ut'][:10] != str(today) or not s.get('liquid'):
                continue
            if abs(q['prev'] / s['close'] - 1) > 0.01:      # split / bad data: prep close must match moomoo's previous close
                continue
            px = q['last']
            r = rsi_now(px, s)
            if px > s['above'] and r < 10:
                cands.append((r, sym, px, s))
        cands.sort()
        free = SLOTS - len(held); new = 0
        if cands and block:
            tg(f'{len(cands)} signals but no new buys: {block}.')
        elif cands:
            slot = (CAPITAL + S['realized']) / SLOTS; cash = B.cash()
            for r, sym, px, s in cands:
                if free <= 0 or new >= MAX_NEW:
                    break
                amt = min(slot, cash * 0.98); qty = math.floor(amt / px)
                if qty < 1:
                    break
                lim = round(px * (1 + float(C['LIMIT_BUFFER_PCT']) / 100), 2)
                oid = B.place(sym, 'BUY', qty, 'NORMAL', lim)
                o = wait_fill(B, oid, qty) if MODE != 'dry' else dict(status='FILLED_ALL', dealt=qty, avg=px)
                if not o['dealt']:
                    journal(action='buy_unfilled', sym=sym, qty=qty, price=lim, order_id=oid, reason=o['status']); continue
                fill, q_ = o['avg'] or px, o['dealt']
                stop = round(fill - 3 * s['atr14'], 2)
                sid = place_stop(B, sym, q_, stop) if MODE != 'dry' else None
                held[sym] = dict(qty=q_, entry=fill, stop=stop, stop_id=sid, date=str(today), days=0, last_seen=str(today), rsi=round(r, 1), buy_id=oid)
                cash -= q_ * fill; free -= 1; new += 1
                journal(action='buy', sym=sym, qty=q_, price=fill, stop=stop, reason=f'RSI2 {r:.1f}', order_id=oid)
                msgs.append(f'BUY {sym} {q_:g} @ {fill:.2f} (RSI2 {r:.1f}), stop {stop:.2f}')
        S['last_run'] = str(today); save_state(S)
        tg(f"{today}: {len(msgs)} actions. " + ('; '.join(msgs) if msgs else 'No trades.') +
           f" Open {len(held)}/{SLOTS}. Book ${equity:,.0f} (realised {S['realized']:+,.0f}, {S['trades']} closed, {S['wins']} wins).")
    finally:
        B.close()


def close_pos(S, sym, px, why, msgs, qty=None, oid=''):
    p = S['positions'][sym]; q = p['qty'] if qty is None else min(qty, p['qty'])
    pnl = q * (px - p['entry']); S['realized'] += pnl
    p['qty'] -= q
    if p['qty'] <= 1e-9:
        del S['positions'][sym]; S['trades'] += 1; S['wins'] += int(px > p['entry'])
    journal(action='sell', sym=sym, qty=q, price=px, reason=why, order_id=oid, pnl=round(pnl, 2))
    msgs.append(f'SELL {sym} {q:g} @ {px:.2f} ({why}) {pnl:+.0f}')


def status():
    S = load_state(); print(json.dumps(S, indent=1))
    if os.path.exists(PAUSE):
        print('PAUSED (no new buys).')


def selftest():
    print('Mode:', MODE, '| OpenD', C['OPEND_HOST'], C['OPEND_PORT'], '| firm', C['FIRM'])
    P = fetch_prep(); print('Prep as of', P['asof'], '-', P['n'], 'stocks;', len(P['signals']), 'signals at that close:', P['signals'][:10])
    B = Moomoo(trade=MODE != 'dry')
    try:
        print('Snapshot SPY/AAPL:', B.snapshot(['SPY', 'AAPL']))
        if MODE != 'dry':
            print('Account', C['ACC_ID'], 'USD cash:', B.cash(), '| US positions:', B.positions())
    finally:
        B.close()


if __name__ == '__main__':
    if MODE not in ('dry', 'paper', 'live'):
        sys.exit('MODE must be dry, paper or live')
    if MODE == 'live' and (C['LIVE_CONFIRM'] != 'YES_REAL_MONEY' or not C['MOOMOO_TRADE_PWD']):
        sys.exit('Live mode needs LIVE_CONFIRM=YES_REAL_MONEY and MOOMOO_TRADE_PWD in the environment.')
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'status'
    {'run': lambda: run(force='--force' in sys.argv), 'status': status, 'selftest': selftest}.get(cmd, status)()
