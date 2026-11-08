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
    if r["kind"] == "ATH_STOP":
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
    r = next(r for r in P["rows"] if not r["skip"] and r["qty"] > 0 and r["kind"] != "ATH_STOP")
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
    r = next(r for r in P["rows"] if not r["skip"] and r["qty"] > 0 and r["kind"] != "ATH_STOP")
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
    r = next(r for r in P["rows"] if not r["skip"] and r["qty"] > 0 and r["kind"] != "ATH_STOP")
    j = c.post("/api/order", headers=h, json={"id": r["id"], "qty": r["qty"], "confirm": f"BUY {r['qty']} {r['symbol']}"}).json()
    assert j["sent"] is False and j["protect"]["trigger"] < r["stop"] + 0.01
    assert not getattr(A.broker, "gtts", None) and not A.broker.placed


def test_basket(tmp_path):
    A, c = client(tmp_path, live="1")
    tok = c.post("/api/login", json={"password": "pw"}).json()["token"]; h = {"Authorization": "Bearer " + tok}
    A.market_open = lambda t=None: False; A.amo_window = lambda t=None: True
    P = c.get("/api/plan", headers=h).json()
    ok = [r for r in P["rows"] if not r["skip"] and r["qty"] > 0 and r["kind"] != "ATH_STOP"][:3]
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
    row = next(x for x in P["rows"] if not x["skip"] and x["qty"] > 0 and x["kind"] != "ATH_STOP")
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
    rs = [r for r in P["rows"] if not r["skip"] and r["qty"] > 0 and r["kind"] != "ATH_STOP"][:2]
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
    assert all(r["kind"] in ("T921", "RETEST") for r in sw)
    assert A.protect_level("RETEST", 100) == 100 and A.protect_level("T921", 100) == 100 and A.protect_level("ATH_BRK", 100) < 100
    assert not any(r["kind"] == "T921" for r in P["rows"] if r["tier"] != "swing")
    j = c.post("/api/picks", headers=h, json={"n": 5, "swing_risk": 1.0}).json(); assert j["swing_risk_pct"] == 1.0 and j["picks"] == 5
    P2 = c.get("/api/plan", headers=h).json(); assert P2["swing"]["risk_pct"] == 1.0
    for r in P2["rows"]:
        if r["tier"] == "swing" and r["qty"]:
            E = r.get("trigger") or r["price"]
            assert r["qty"] * (E - r["stop"]) <= 0.01 * 2000000 + E and r["qty"] * E <= P2["swing"]["idle_cash"] + E
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
