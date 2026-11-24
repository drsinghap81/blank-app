"""24 Nov 2026: prove orders reach moomoo - on the PAPER account only (refuses if MOOMOO_ENV is not SIMULATE).
For each market: a LIMIT buy of 1 share at ~half the last price (can't fill), and a STOP_LIMIT buy whose trigger is ~50% above
the price (can't trigger) - the order type the Top Bottom automation uses. Each is read back, then cancelled.
   sudo -u trenddesk /opt/trenddesk/venv/bin/python /opt/trenddesk/repo/tools/live_server/deploy/mm_test_order.py"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
ENV = {}
for ln in open("/opt/trenddesk/.env"):
    if "=" in ln and not ln.lstrip().startswith("#"):
        k, v = ln.split("=", 1); ENV[k.strip()] = v.split(" #")[0].strip()
from brokers import MoomooTrade  # noqa: E402

mm = MoomooTrade(ENV)
print("moomoo env:", mm.env_name, "| trading on:", mm.trade_on)
if mm.env_name != "SIMULATE":
    sys.exit("REFUSED: this test only runs on the paper account (MOOMOO_ENV=SIMULATE)")
for mk, sym in (("AU", "TECH"), ("US", "QQQ")):
    try:
        last = mm.snapshot([sym], mk=mk)[sym]["last"]
    except Exception as ex:  # noqa: BLE001
        print(mk, sym, "price check failed:", str(ex)[:160]); last = {"AU": 119.0, "US": 651.0}[mk]
    try:
        print(mk, sym, "last", last, "| paper cash", round(mm.cash(mk), 2))
    except Exception as ex:  # noqa: BLE001
        print(mk, "cash check failed:", str(ex)[:160])
    for otype, price, aux in (("NORMAL", round(last * 0.5, 2), None), ("STOP_LIMIT", round(last * 1.51, 2), round(last * 1.5, 2))):
        try:
            oid = mm.place(sym, "BUY", 1, otype, price, aux=aux, tif="DAY", mk=mk, remark="trenddesk-test")
            time.sleep(2); o = mm.order(oid, mk=mk)
            ok = mm.cancel(oid, mk=mk); time.sleep(1); o2 = mm.order(oid, mk=mk)
            print(f"  {mk} {otype:10s} BUY 1 {sym} @ {price}{' trigger ' + str(aux) if aux else ''}: ACCEPTED id {oid} status {o['status']} -> cancel {'ok' if ok else 'failed'} ({o2['status']})")
        except Exception as ex:  # noqa: BLE001
            print(f"  {mk} {otype:10s}: REJECTED - {str(ex)[:200]}")
print("TEST DONE")
