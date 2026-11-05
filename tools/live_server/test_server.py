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
