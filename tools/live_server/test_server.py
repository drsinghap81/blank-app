"""Dry-run test of the live server with a mock Angel account: python -m pytest tools/live_server/test_server.py -q"""
import importlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def client(tmp_path, live="0"):
    os.environ.update(MOCK_BROKER="1", DATA_DIR=str(tmp_path), TOKEN_SECRET="x" * 32, LIVE_ORDERS=live, CAPITAL="2000000",
                      PLAN_FILE=os.path.join(HERE, "..", "..", "data", "scan", "trade_plan.json"))
    import app as A
    A = importlib.reload(A)
    A.PW_HASH = A.make_hash("pw")
    from fastapi.testclient import TestClient
    return A, TestClient(A.app)


def test_flow(tmp_path):
    A, c = client(tmp_path)
    assert c.post("/api/login", json={"password": "no"}).status_code == 401
    tok = c.post("/api/login", json={"password": "pw"}).json()["token"]
    h = {"Authorization": "Bearer " + tok}
    assert c.get("/api/plan").status_code == 401
    P = c.get("/api/plan", headers=h).json()
    rows = [r for r in P["rows"] if not r["skip"] and r["qty"] > 0]
    assert rows and P["mode"] == "DRY RUN"
    r = rows[0]
    # sizing: 1% risk, <= 20% of capital
    E = r.get("trigger") or r["price"]
    assert r["qty"] * (E - r["stop"]) <= 0.01 * 2000000 + E and r["qty"] * E <= 0.2 * 2000000 + E
    bad = c.post("/api/order", headers=h, json={"id": r["id"], "qty": r["qty"] + 1, "confirm": "x"})
    assert bad.status_code == 400
    wrong = c.post("/api/order", headers=h, json={"id": r["id"], "qty": r["qty"], "confirm": "BUY 1 XYZ"})
    assert wrong.status_code in (400,)
    nf = c.post("/api/order", headers=h, json={"id": "HACK-RELIANCE", "qty": 1, "confirm": "BUY 1 RELIANCE"})
    assert nf.status_code == 404
    A.market_open = lambda t=None: False; A.amo_window = lambda t=None: True
    ok = c.post("/api/order", headers=h, json={"id": r["id"], "qty": r["qty"], "confirm": f"BUY {r['qty']} {r['symbol']}"})
    if r["kind"] in ("ATH_STOP", "TF_STOP"):
        assert ok.status_code == 400
    else:
        j = ok.json(); assert ok.status_code == 200 and j["sent"] is False and j["order"]["variety"] == "AMO", j
        assert j["order"]["ordertype"] == "LIMIT" and j["order"]["producttype"] == "DELIVERY"
    assert not A.broker.placed            # dry run never reaches the broker


def test_live_once(tmp_path):
    A, c = client(tmp_path, live="1")
    tok = c.post("/api/login", json={"password": "pw"}).json()["token"]; h = {"Authorization": "Bearer " + tok}
    A.market_open = lambda t=None: False; A.amo_window = lambda t=None: True
    P = c.get("/api/plan", headers=h).json()
    r = next(r for r in P["rows"] if not r["skip"] and r["qty"] > 0 and r["kind"] not in ("ATH_STOP", "TF_STOP"))
    body = {"id": r["id"], "qty": r["qty"], "confirm": f"BUY {r['qty']} {r['symbol']}"}
    a = c.post("/api/order", headers=h, json=body); assert a.status_code == 200 and a.json()["sent"] is True
    b = c.post("/api/order", headers=h, json=body); assert b.status_code == 409     # once a day per row
    assert len(A.broker.placed) == 1


def test_guard(tmp_path):
    os.environ["DD_BUDGET_PCT"] = "10"; os.environ.pop("RISK_PCT", None)
    A, c = client(tmp_path)
    assert abs(A.RISK - 0.25 / 100 * (1 + (10 - 8.6) / (16.4 - 8.6))) < 1e-9 and A.MAX_POS_PCT == 0.10
    acc = A.broker.account()
    g = A.guard(dict(acc, net=2_000_000)); assert g["status"] == "ok" and g["dd_pct"] == 0
    g = A.guard(dict(acc, net=1_840_000)); assert g["status"] == "warn" and g["dd_pct"] == -8.0
    g = A.guard(dict(acc, net=1_790_000)); assert g["status"] == "over"
    J = {f"S{i}": dict(entry=100.0) for i in range(5)}; A.save_journal(J)
    for i in range(5):
        A.record_exit(f"S{i}", 90.0)
    assert A.guard(acc)["status"] == "paused"
    tok = c.post("/api/login", json={"password": "pw"}).json()["token"]
    P = c.get("/api/plan", headers={"Authorization": "Bearer " + tok}).json()
    assert all(r["skip"] for r in P["rows"]) and P["guard"]["status"] == "paused"
    os.environ.pop("DD_BUDGET_PCT", None)


def test_mode_switch(tmp_path):
    A, c = client(tmp_path)
    tok = c.post("/api/login", json={"password": "pw"}).json()["token"]; h = {"Authorization": "Bearer " + tok}
    assert c.post("/api/mode", json={"live": True, "password": "pw", "confirm": "LIVE"}).status_code == 401   # needs token
    assert c.post("/api/mode", headers=h, json={"live": True, "password": "pw", "confirm": "yes"}).status_code == 400
    assert c.post("/api/mode", headers=h, json={"live": True, "password": "no", "confirm": "LIVE"}).status_code == 401
    assert c.get("/api/health").json()["mode"] == "DRY RUN"
    assert c.post("/api/mode", headers=h, json={"live": True, "password": "pw", "confirm": "live"}).json()["mode"] == "LIVE"
    assert c.get("/api/health").json()["mode"] == "LIVE"
    assert c.post("/api/mode", headers=h, json={"live": False}).json()["mode"] == "DRY RUN"   # one tap, no password
    assert c.get("/api/health").json()["mode"] == "DRY RUN"


def test_fill_protect_exit(tmp_path):
    A, c = client(tmp_path, live="1")
    tok = c.post("/api/login", json={"password": "pw"}).json()["token"]; h = {"Authorization": "Bearer " + tok}
    A.market_open = lambda t=None: False; A.amo_window = lambda t=None: True
    P = c.get("/api/plan", headers=h).json()
    r = next(r for r in P["rows"] if not r["skip"] and r["qty"] > 0 and r["kind"] not in ("ATH_STOP", "TF_STOP"))
    j = c.post("/api/order", headers=h, json={"id": r["id"], "qty": r["qty"], "confirm": f"BUY {r['qty']} {r['symbol']}"}).json()
    lv = r["stop"] if r["kind"] == "T921" else r["stop"] * 0.85
    assert abs(j["protect"]["trigger"] - round(lv, 2)) < 0.02
    P2 = c.get("/api/plan", headers=h).json()                 # sync: mock fills at once -> open + GTT
    t = next(t for t in P2["trades"] if t["symbol"] == r["symbol"])
    assert t["state"] == "open" and t["gtt_id"] and abs(t["gtt_trigger"] - round(lv, 2)) < 0.02
    assert next(x for x in P2["rows"] if x["id"] == r["id"])["skip"] == "already held"
    # the stop fires on Angel's side: holding disappears -> recorded as stopped, streak counted
    A.broker.hold[r["symbol"]] = 0; A._acc["d"] = None
    P3 = c.get("/api/plan", headers=h).json()
    assert not any(t["symbol"] == r["symbol"] for t in P3["trades"])
    assert P3["recent"][0]["symbol"] == r["symbol"] and "stopped" in P3["recent"][0]["state"]
    assert P3["guard"]["streak"] == 1


def test_dry_shows_protect(tmp_path):
    A, c = client(tmp_path)
    tok = c.post("/api/login", json={"password": "pw"}).json()["token"]; h = {"Authorization": "Bearer " + tok}
    A.market_open = lambda t=None: False; A.amo_window = lambda t=None: True
    P = c.get("/api/plan", headers=h).json()
    r = next(r for r in P["rows"] if not r["skip"] and r["qty"] > 0 and r["kind"] not in ("ATH_STOP", "TF_STOP"))
    j = c.post("/api/order", headers=h, json={"id": r["id"], "qty": r["qty"], "confirm": f"BUY {r['qty']} {r['symbol']}"}).json()
    assert j["sent"] is False and j["protect"]["trigger"] < r["stop"] + 0.01
    assert not getattr(A.broker, "gtts", None) and not A.broker.placed


def test_basket(tmp_path):
    A, c = client(tmp_path, live="1")
    tok = c.post("/api/login", json={"password": "pw"}).json()["token"]; h = {"Authorization": "Bearer " + tok}
    A.market_open = lambda t=None: False; A.amo_window = lambda t=None: True
    P = c.get("/api/plan", headers=h).json()
    ok = [r for r in P["rows"] if not r["skip"] and r["qty"] > 0 and r["kind"] not in ("ATH_STOP", "TF_STOP")][:3]
    items = [{"id": r["id"], "qty": r["qty"]} for r in ok] + [{"id": "HACK-X", "qty": 1}]
    assert c.post("/api/basket", headers=h, json={"items": items, "confirm": "BASKET 3"}).status_code == 400   # count must match
    j = c.post("/api/basket", headers=h, json={"items": items, "confirm": f"BASKET {len(items)}"}).json()
    res = {x["id"]: x for x in j["results"]}
    assert all(res[r["id"]]["ok"] and res[r["id"]]["sent"] for r in ok) and not res["HACK-X"]["ok"]
    assert len(A.broker.placed) == len(ok)
    j2 = c.post("/api/basket", headers=h, json={"items": items[:1], "confirm": "BASKET 1"}).json()   # once a day per row
    assert not j2["results"][0]["ok"]


def test_quotes(tmp_path):
    A, c = client(tmp_path)
    tok = c.post("/api/login", json={"password": "pw"}).json()["token"]; h = {"Authorization": "Bearer " + tok}
    assert c.get("/api/quotes").status_code == 401
    j = c.get("/api/quotes", headers=h).json()
    assert j["rows"] and all(v["ltp"] > 0 for v in j["rows"].values())


def test_live_checks(tmp_path):
    A, c = client(tmp_path)
    tok = c.post("/api/login", json={"password": "pw"}).json()["token"]; h = {"Authorization": "Bearer " + tok}
    A.market_open = lambda t=None: True
    r = dict(kind="ATH_STOP", trigger=100.0, price=101.0, stop=80.0, ref=96.0)
    assert A.live_check(r, 95)[0] == "wait" and A.live_check(r, 102)[0] == "triggered" and A.live_check(r, 104)[0] == "missed"
    assert A.live_check(r, 79)[0] == "broken"
    b = dict(kind="ATH_BRK", price=101.0, ref=100.0, stop=80.0)
    assert A.live_check(b, 102)[0] == "ok" and A.live_check(b, 102)[1] == 103.0 and A.live_check(b, 104)[0] == "ran"
    P = c.get("/api/plan", headers=h).json()
    row = next(x for x in P["rows"] if not x["skip"] and x["qty"] > 0 and x["kind"] not in ("ATH_STOP", "TF_STOP"))
    A.broker.ltp = lambda s: row["ref"] * 1.10            # ran away -> refused
    j = c.post("/api/order", headers=h, json={"id": row["id"], "qty": row["qty"], "confirm": f"BUY {row['qty']} {row['symbol']}"})
    assert j.status_code == 400 and "plan close" in j.json()["detail"]
    A.broker.ltp = lambda s: row["ref"] * 1.01
    j = c.post("/api/order", headers=h, json={"id": row["id"], "qty": row["qty"], "confirm": f"BUY {row['qty']} {row['symbol']}"}).json()
    assert j["order"]["ordertype"] == "LIMIT" and j["order"]["variety"] == "NORMAL"


def test_angel_reject_reason(tmp_path):
    A, c = client(tmp_path, live="1")
    tok = c.post("/api/login", json={"password": "pw"}).json()["token"]; h = {"Authorization": "Bearer " + tok}
    A.market_open = lambda t=None: False; A.amo_window = lambda t=None: True
    def bad(p): raise RuntimeError("The order cannot be processed as the token is categorised under cautionary listings by the exchange. [AB4036]")
    A.broker.place = bad
    P = c.get("/api/plan", headers=h).json()
    rs = [r for r in P["rows"] if not r["skip"] and r["qty"] > 0 and r["kind"] not in ("ATH_STOP", "TF_STOP")][:2]
    j = c.post("/api/order", headers=h, json={"id": rs[0]["id"], "qty": rs[0]["qty"], "confirm": f"BUY {rs[0]['qty']} {rs[0]['symbol']}"})
    assert j.status_code == 502 and "cautionary" in j.json()["detail"]
    j = c.post("/api/basket", headers=h, json={"items": [{"id": rs[1]["id"], "qty": rs[1]["qty"]}], "confirm": "BASKET 1"}).json()
    assert not j["results"][0]["ok"] and "cautionary" in j["results"][0]["error"]


def test_tb_approvals(tmp_path):
    A, c = client(tmp_path)
    tok = c.post("/api/login", json={"password": "pw"}).json()["token"]; h = {"Authorization": "Bearer " + tok}
    sys.path.insert(0, os.path.join(HERE, "..", "angel")); from notify import AppChannel
    ch = AppChannel(A.TB_APP)
    ch.ask("BUY:55123.00", "BUY 1 lot above 55,123.00")
    j = c.get("/api/tb", headers=h).json(); assert j["mode"] == "DRY RUN" and j["pending"][0]["key"] == "BUY:55123.00"
    assert ch.get("BUY:55123.00") is None
    assert c.post("/api/tb/answer", headers=h, json={"key": "BUY:55123.00", "value": True}).json()["ok"]
    assert ch.get("BUY:55123.00") is True and not c.get("/api/tb", headers=h).json()["pending"]
    # live: approving needs YES
    assert c.post("/api/tb/mode", headers=h, json={"live": True, "password": "pw", "confirm": "LIVE"}).json()["mode"] == "LIVE"
    ch.ask("SELL:54000.00", "SELL 1 lot below 54,000.00")
    assert c.post("/api/tb/answer", headers=h, json={"key": "SELL:54000.00", "value": True}).status_code == 400
    assert c.post("/api/tb/answer", headers=h, json={"key": "SELL:54000.00", "value": True, "confirm": "yes"}).json()["ok"]
    assert c.post("/api/tb/cmd", headers=h, json={"cmd": "/stop"}).json()["ok"] and ch.poll() == ["/stop"]


def test_picks(tmp_path):
    A, c = client(tmp_path)
    tok = c.post("/api/login", json={"password": "pw"}).json()["token"]; h = {"Authorization": "Bearer " + tok}
    P10 = c.get("/api/plan", headers=h).json(); assert P10["picks"] == 10
    j = c.post("/api/picks", headers=h, json={"n": 5}).json()
    assert j["picks"] == 5 and abs(j["risk_pct"] - min(1.0, A.RISK * 100 * 2)) < 0.01
    P5 = c.get("/api/plan", headers=h).json(); assert P5["picks"] == 5 and P5["slots"] <= 5
    a = {r["id"]: r for r in P10["rows"]}; b = {r["id"]: r for r in P5["rows"]}
    assert any(b[k]["qty"] > a[k]["qty"] for k in b if a[k]["qty"])      # bigger positions at the higher risk
    for r in P5["rows"]:
        E = r.get("trigger") or r["price"]
        assert r["qty"] * (E - r["stop"]) <= 0.01 * 2000000 + E and r["qty"] * E <= 0.1 * 2000000 + E
    assert c.post("/api/picks", headers=h, json={"n": 1}).json()["picks"] == 3


def test_swing_sleeve(tmp_path):
    A, c = client(tmp_path)
    tok = c.post("/api/login", json={"password": "pw"}).json()["token"]; h = {"Authorization": "Bearer " + tok}
    P = c.get("/api/plan", headers=h).json()
    assert "swing" in P and P["swing"]["risk_pct"] == round(A.RISK * 100, 2)
    sw = [r for r in P["rows"] if r["tier"] == "swing"]
    assert all(r["kind"] in ("T921", "RETEST", "TF_BRK", "TF_STOP", "PATTERN") for r in sw)
    assert A.protect_level("RETEST", 100) == 100 and A.protect_level("T921", 100) == 100 and A.protect_level("ATH_BRK", 100) < 100
    assert not any(r["kind"] == "T921" for r in P["rows"] if r["tier"] != "swing")
    j = c.post("/api/picks", headers=h, json={"n": 5, "swing_risk": 1.0}).json(); assert j["swing_risk_pct"] == 1.0 and j["picks"] == 5
    P2 = c.get("/api/plan", headers=h).json(); assert P2["swing"]["risk_pct"] == 1.0
    for r in P2["rows"]:
        if r["tier"] == "swing" and r["qty"]:
            E = r.get("trigger") or r["price"]
            assert r["qty"] * (E - r["stop"]) <= 0.01 * 2000000 + E
            assert r.get("outside") or r["qty"] * E <= P2["swing"]["idle_cash"] + E          # 0% buckets are sized against your cash
    assert c.post("/api/picks", headers=h, json={"n": 5, "swing_risk": 9}).json()["swing_risk_pct"] == 1.0   # capped at 1%
    assert c.post("/api/picks", headers=h, json={"n": 6}).json()["swing_risk_pct"] == 1.0                    # kept when not sent


def test_capital_setting(tmp_path):
    A, c = client(tmp_path)
    tok = c.post("/api/login", json={"password": "pw"}).json()["token"]; h = {"Authorization": "Bearer " + tok}
    P0 = c.get("/api/plan", headers=h).json(); assert P0["capital"] == 2000000 and P0["capital_set"] is None
    assert c.post("/api/picks", headers=h, json={"n": 10, "capital": 1000000}).json()["capital"] == 1000000
    P1 = c.get("/api/plan", headers=h).json(); assert P1["capital"] == 1000000
    a = {r["id"]: r["qty"] for r in P0["rows"]}; assert any(r["qty"] < a[r["id"]] for r in P1["rows"] if a[r["id"]] > 1)
    c.post("/api/picks", headers=h, json={"n": 10, "capital": 9e9}); assert c.get("/api/plan", headers=h).json()["capital"] == 2000000   # capped at the account
    c.post("/api/picks", headers=h, json={"n": 10, "capital": 0}); assert c.get("/api/plan", headers=h).json()["capital"] == 2000000


def test_buckets(tmp_path):
    A, c = client(tmp_path)
    tok = c.post("/api/login", json={"password": "pw"}).json()["token"]; h = {"Authorization": "Bearer " + tok}
    P = c.get("/api/plan", headers=h).json()
    B = {b["key"]: b for b in P["buckets"]}; assert B["mom"]["pct"] == 60 and B["tf"]["pct"] == 40 and B["t9"]["pct"] == 0 and B["s1"]["pct"] == 0 and B["tb"]["pct"] == 100
    assert all(r.get("bucket") in ("mom", "tf", "t9", "rt", "pt") for r in P["rows"])
    j = c.post("/api/picks", headers=h, json={"alloc": {"tf": 1, "rt": 0, "t9": 0, "bogus": 50}}).json()
    assert j["alloc"]["tf"] == 1 and "bogus" not in j["alloc"] and j["picks"] == 10
    P2 = c.get("/api/plan", headers=h).json()
    tf = [r for r in P2["rows"] if r["bucket"] == "tf" and not r["skip"]]
    assert sum(r["value"] for r in tf) <= 0.01 * 2000000 + max([r.get("trigger") or r["price"] for r in tf] or [0])
    # buckets at 0% are still sized (the user decides), flagged "outside your split", and use no system room
    off = [r for r in P2["rows"] if r["bucket"] in ("rt", "t9", "pt")]
    assert off and all(r["skip"] or (r.get("outside") and "your call" in r["note"]) for r in off)
    assert any(r["kind"] == "PATTERN" and r["id"].startswith("PAT-") and r["qty"] > 0 for r in P2["rows"])
    assert A.protect_level("PATTERN", 100) == 100
    mom = [r for r in P2["rows"] if r["bucket"] == "mom" and not r["skip"]]
    assert sum(r["value"] for r in mom) <= 0.60 * 2000000 + 1
    assert A.protect_level("TF_BRK", 100) < 100           # Trend 9/21: safety net only, the system exits on the EMA cross


def test_trail(tmp_path):
    A, c = client(tmp_path, live="1")
    tok = c.post("/api/login", json={"password": "pw"}).json()["token"]; h = {"Authorization": "Bearer " + tok}
    A.market_open = lambda t=None: False; A.amo_window = lambda t=None: True
    P = c.get("/api/plan", headers=h).json()
    r = next(r for r in P["rows"] if not r["skip"] and r["qty"] > 0 and r["kind"] not in ("ATH_STOP", "TF_STOP"))
    c.post("/api/order", headers=h, json={"id": r["id"], "qty": r["qty"], "confirm": f"BUY {r['qty']} {r['symbol']}"})
    c.get("/api/plan", headers=h)                                        # fill -> GTT placed
    J = A.journal(); e = J[r["symbol"]]; e.update(system="Monthly ATH", gtt_trigger=10.0); A.save_journal(J)
    res = c.post("/api/trail", headers=h).json()["results"]
    x = next(x for x in res if x["symbol"] == r["symbol"])
    assert x["result"] == "raised" and x["new"] > 10 and abs(x["new"] - x["level"] * 0.85) < 0.02 and x["level"] < x["close"]
    g = A.broker.gtts[e["gtt_id"]]; assert abs(g["trigger"] - x["new"]) < 0.02          # moved on the broker
    again = next(y for y in c.post("/api/trail", headers=h).json()["results"] if y["symbol"] == r["symbol"])
    assert again["result"].startswith("unchanged")                       # never lowered / not moved twice
    P2 = c.get("/api/plan", headers=h).json(); t = next(t for t in P2["trades"] if t["symbol"] == r["symbol"])
    assert t["trail_prev"] == 10.0 and t["trail_at"] and P2["trail"]["results"]
    # dry run: shows the new level, changes nothing on Angel
    J = A.journal(); J[r["symbol"]]["gtt_trigger"] = 5.0; A.save_journal(J); A.set_live(False)
    d = next(y for y in c.post("/api/trail", headers=h).json()["results"] if y["symbol"] == r["symbol"])
    assert d["result"].startswith("dry run") and abs(A.broker.gtts[e["gtt_id"]]["trigger"] - x["new"]) < 0.02
    # systems with a tested static stop are not trailed
    J = A.journal(); J[r["symbol"]]["system"] = "9/21 trend"; A.save_journal(J)
    assert not any(y["symbol"] == r["symbol"] for y in c.post("/api/trail", headers=h).json()["results"])


def test_perf():
    import app as A
    J = {"AAA": dict(state="open", qty=10, entry=100.0, system="Monthly ATH", since="2026-10-01"),
         "BBB": dict(state="pending", qty=5, entry=50.0),
         "_done": {"CCC:2026-10-20": dict(state="sold", qty=4, entry=200.0, exit=250.0, system="Trend 9/21", since="2026-09-15"),
                   "DDD:2026-10-21": dict(state="rejected", qty=3, entry=10.0)}}
    P = A.perf_view(J, {"holdings": [{"symbol": "AAA", "ltp": 110.0}]})
    assert P["open"] == dict(n=1, cost=1000.0, value=1100.0, pnl=100.0)
    assert P["closed"]["n"] == 1 and P["closed"]["pnl"] == 200.0 and P["closed"]["wins"] == 1
    assert P["total_pnl"] == 300.0 and P["total_pct"] == 16.67 and P["since"] == "2026-09-15"


def test_equity_log(tmp_path):
    A, c = client(tmp_path)
    tok = c.post("/api/login", json={"password": "pw"}).json()["token"]; h = {"Authorization": "Bearer " + tok}
    P = c.get("/api/plan", headers=h).json()
    assert P["real_value"] > 0 and P["equity"] and P["equity"][-1][1] == P["real_value"] and isinstance(P["holdings"], list)
    assert A.equity_log(P["real_value"] + 5)[-1][1] == P["real_value"] + 5 and len(A.equity_log(1.0)) == 1   # one point a day


def test_sip(tmp_path):
    A, c = client(tmp_path)
    tok = c.post("/api/login", json={"password": "pw"}).json()["token"]; h = {"Authorization": "Bearer " + tok}
    A.market_open = lambda t=None: True; A.amo_window = lambda t=None: False
    it = [{"symbol": "NIFTYBEES", "qty": 10}, {"symbol": "GOLDBEES", "qty": 20}]
    assert c.post("/api/sip", headers=h, json={"items": [{"symbol": "RELIANCE", "qty": 1}], "confirm": "SIP 1"}).status_code == 400
    assert c.post("/api/sip", headers=h, json={"items": it, "confirm": "SIP 3"}).status_code == 400
    assert c.post("/api/sip", headers=h, json={"items": [{"symbol": "NIFTYBEES", "qty": 99999}], "confirm": "SIP 1"}).status_code == 400   # above cash / limit
    r = c.post("/api/sip", headers=h, json={"items": it, "confirm": "SIP 2"}).json()
    assert r["mode"] == "DRY RUN" and not r["sent"] and len(r["orders"]) == 2 and r["orders"][0]["params"]["producttype"] == "DELIVERY"
    assert c.post("/api/sip", headers=h, json={"items": it, "confirm": "SIP 2"}).status_code == 200                          # dry runs can repeat
    A.set_live(True)
    r2 = c.post("/api/sip", headers=h, json={"items": [{"symbol": "MON100", "qty": 5}], "confirm": "SIP 1"}).json()
    assert r2["sent"] and r2["results"][0]["ok"]
    assert c.post("/api/sip", headers=h, json={"items": [{"symbol": "MON100", "qty": 5}], "confirm": "SIP 1"}).status_code == 409   # once a day
    assert "MON100" not in A.journal()                                                                                      # not a system trade


def test_tb_nifty_instance(tmp_path):
    os.environ["TB_NIFTY_DIR"] = str(tmp_path / "tbn")
    A, c = client(tmp_path)
    sys.path.insert(0, os.path.join(HERE, "..", "angel")); from notify import AppChannel
    tok = c.post("/api/login", json={"password": "pw"}).json()["token"]; h = {"Authorization": "Bearer " + tok}
    ch = AppChannel(str(tmp_path / "tbn" / "app"), lambda *a: None)
    ch.ask("BUY:25100.00", "BUY 1 lot(s) NIFTY FUT if it trades above 25,100.00")
    j = c.get("/api/tb?inst=nifty", headers=h).json(); assert j["inst"] == "nifty" and j["pending"][0]["key"] == "BUY:25100.00"
    assert not c.get("/api/tb", headers=h).json()["pending"]                                         # Bank Nifty untouched
    assert c.post("/api/tb/answer?inst=nifty", headers=h, json={"key": "BUY:25100.00", "value": True}).json()["ok"] and ch.get("BUY:25100.00") is True
    assert c.post("/api/tb/mode?inst=nifty", headers=h, json={"live": True, "password": "pw", "confirm": "LIVE"}).json()["mode"] == "LIVE"
    assert c.get("/api/tb", headers=h).json()["mode"] == "DRY RUN"                                   # separate switches
    assert c.get("/api/tb?inst=xyz", headers=h).status_code == 404
    os.environ.pop("TB_NIFTY_DIR")


def test_adopt(tmp_path):
    A, c = client(tmp_path)
    tok = c.post("/api/login", json={"password": "pw"}).json()["token"]; h = {"Authorization": "Bearer " + tok}
    A.broker.hold.update({"TITAN": 40, "NIFTYBEES": 100, "ITBEES": 3000})
    L = c.get("/api/adopt", headers=h).json()
    t = next(x for x in L["holdings"] if x["symbol"] == "TITAN")
    assert t["suggest"] == "Monthly ATH" and t["stop"] and t["protect"] < t["stop"]
    assert not any(x["symbol"] in ("NIFTYBEES", "ITBEES") for x in L["holdings"])                     # ETFs stay with the Pie
    assert c.post("/api/adopt", headers=h, json={"symbol": "TITAN", "system": "Monthly ATH", "confirm": "ADOPT XYZ"}).status_code == 400
    d = c.post("/api/adopt", headers=h, json={"symbol": "TITAN", "system": "Monthly ATH", "confirm": "ADOPT TITAN"}).json()
    assert d["mode"] == "DRY RUN" and not d["adopted"] and "TITAN" not in A.journal()        # dry run changes nothing
    A.set_live(True)
    r = c.post("/api/adopt", headers=h, json={"symbol": "TITAN", "system": "Monthly ATH", "confirm": "ADOPT TITAN"}).json()
    e = A.journal()["TITAN"]; assert r["adopted"] and e["adopted"] and e["qty"] == 40 and e["gtt_id"] in A.broker.gtts
    assert c.post("/api/adopt", headers=h, json={"symbol": "TITAN", "system": "Monthly ATH", "confirm": "ADOPT TITAN"}).status_code == 409
    assert c.post("/api/adopt", headers=h, json={"symbol": "NOTHELD", "system": "Monthly ATH", "confirm": "ADOPT NOTHELD"}).status_code == 404
    assert not any(x["symbol"] == "TITAN" for x in c.get("/api/adopt", headers=h).json()["holdings"])
    # trend breaks -> the app shows a Sell for it
    from datetime import date, timedelta
    def down(sym, days=420):
        out, d, px = [], date(2025, 8, 1), 150.0
        while len(out) < 300:
            if d.weekday() < 5:
                px *= 0.996; out.append((d.isoformat(), px, px * 1.01, px * 0.99, px))
            d += timedelta(days=1)
        return out
    A.broker.daily_candles = down; A._ADC.clear()
    P = c.get("/api/plan", headers=h).json(); x = next(x for x in P["exits"] if x["symbol"] == "TITAN")
    assert x["id"] == "EXIT-ADOPT-TITAN" and x["qty"] == 40 and "30-week" in x["why"]
    # release: stop cancelled, journal entry gone, shares untouched
    gid = e["gtt_id"]
    assert c.post("/api/adopt/release", headers=h, json={"symbol": "TITAN", "confirm": "RELEASE TITAN"}).json()["ok"]
    assert "TITAN" not in A.journal() and A.broker.hold["TITAN"] == 40


def test_quotes_mkt(tmp_path):
    A, c = client(tmp_path)
    tok = c.post("/api/login", json={"password": "pw"}).json()["token"]; h = {"Authorization": "Bearer " + tok}
    seen = []
    A.yq = lambda sym, mk: (seen.append((sym, mk)) or dict(ltp=101.0, prev=100.0, high=102.0, low=99.0, open=100.5, t=0))
    j = c.get("/api/quotes_mkt?mk=US", headers=h).json()
    assert j["mk"] == "US" and j["symbols"] and all(v["ltp"] == 101.0 for v in j["symbols"].values()) and all(m == "US" for _, m in seen)
    n = len(seen); c.get("/api/quotes_mkt?mk=US", headers=h); assert len(seen) == n                       # cached
    assert c.get("/api/quotes_mkt?mk=XX", headers=h).status_code == 404
    from datetime import datetime, timezone
    assert A.mkt_open("US", datetime(2026, 11, 9, 15, 0, tzinfo=timezone.utc)) and not A.mkt_open("US", datetime(2026, 11, 9, 22, 0, tzinfo=timezone.utc))


def test_indices(tmp_path):
    A, c = client(tmp_path)
    tok = c.post("/api/login", json={"password": "pw"}).json()["token"]; h = {"Authorization": "Bearer " + tok}
    seen = []
    A.yq = lambda sym, mk: (seen.append((sym, mk)) or dict(ltp=25000.0, prev=24900.0, high=25100.0, low=24800.0, open=24950.0, t=0))
    j = c.get("/api/indices", headers=h).json()
    assert j["rows"][0]["name"] == "Nifty 50" and j["rows"][0]["grp"] == "IN" and ("^NSEI", "RAW") in seen and len(j["rows"]) == len(A.INDICES)
