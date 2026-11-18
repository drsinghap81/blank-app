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
    assert all(r["kind"] in ("T921", "RETEST", "TF_BRK", "TF_STOP", "PATTERN", "VCP", "VCP_STOP") for r in sw)
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
    assert all(r.get("bucket") in ("mom", "tf", "t9", "rt", "pt", "vcp", "my") for r in P["rows"])
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


def test_indices_fallback(tmp_path):
    A, c = client(tmp_path)
    tok = c.post("/api/login", json={"password": "pw"}).json()["token"]; h = {"Authorization": "Bearer " + tok}
    def boom(sym, mk):
        raise RuntimeError("429 Too Many Requests")
    A.yq = boom
    j = c.get("/api/indices", headers=h).json()
    assert [r["name"] for r in j["rows"]] == ["Nifty 50"] and j["rows"][0]["src"] == "angel" and "429" in j["errors"][0]


def test_vcp_rows():
    """VCP watch bucket (10 Nov 2026): buy-stop rows wait below the pivot, use the static stop, and sit outside the split."""
    from app import live_check, protect_level, STOP_KINDS, BUCKETS
    assert "VCP_STOP" in STOP_KINDS and BUCKETS["vcp"] == 0
    r = dict(kind="VCP_STOP", trigger=100.0, price=101.0, stop=92.0, ref=97.0)
    assert live_check(r, 98.0)[0] == "wait"
    assert live_check(r, 100.5)[0] == "triggered"
    assert live_check(r, 91.0)[0] == "broken"
    assert protect_level("VCP_STOP", 92.0) == 92.0 and protect_level("VCP", 92.0) == 92.0


def test_mypicks_gtt(tmp_path):
    """Push a stock to Live -> sized row -> Send places an Angel GTT BUY -> once held, the protective GTT stop goes in."""
    A, c = client(tmp_path, live="1")
    tok = c.post("/api/login", json={"password": "pw"}).json()["token"]; h = {"Authorization": "Bearer " + tok}
    A.market_open = lambda t=None: False
    assert c.post("/api/mypicks", headers=h, json={"symbol": "ZZTEST", "trigger": 100, "stop": 110}).status_code == 400
    j = c.post("/api/mypicks", headers=h, json={"symbol": "zztest", "trigger": 100, "stop": 92, "src": "Bottoms"}).json()
    assert j["ok"] and j["rows"][0]["symbol"] == "ZZTEST"
    P = c.get("/api/plan", headers=h).json()
    r = next(x for x in P["rows"] if x["id"] == "MY-ZZTEST")
    assert r["kind"] == "MY_GTT" and r["bucket"] == "my" and r["qty"] > 0 and r["outside"]
    q = r["qty"]
    o = c.post("/api/order", headers=h, json={"id": r["id"], "qty": q, "confirm": f"BUY {q} ZZTEST"}).json()
    assert o["sent"] and o["gtt_id"].startswith("GTTB") and A.broker.gtts[o["gtt_id"]]["side"] == "BUY"
    assert A.journal()["ZZTEST"]["state"] == "pending"
    A.broker.hold["ZZTEST"] = q; A._acc["d"] = None                       # the GTT triggered and filled
    A.sync()
    e = A.journal()["ZZTEST"]
    assert e["state"] == "open" and e.get("gtt_id") and A.broker.gtts[e["gtt_id"]]["trigger"] == 92.0
    assert "ZZTEST" not in A.mypicks()


def test_mypicks_cancel(tmp_path):
    A, c = client(tmp_path, live="1")
    tok = c.post("/api/login", json={"password": "pw"}).json()["token"]; h = {"Authorization": "Bearer " + tok}
    A.market_open = lambda t=None: False
    c.post("/api/mypicks", headers=h, json={"symbol": "ZZTWO", "trigger": 50, "stop": 46})
    r = next(x for x in c.get("/api/plan", headers=h).json()["rows"] if x["id"] == "MY-ZZTWO")
    o = c.post("/api/order", headers=h, json={"id": r["id"], "qty": r["qty"], "confirm": f"BUY {r['qty']} ZZTWO"}).json()
    j = c.delete("/api/mypicks/ZZTWO", headers=h).json()
    assert "cancelled" in j["msg"] and not A.broker.gtts[o["gtt_id"]]["active"] and "ZZTWO" not in A.journal()


def test_research_orb(tmp_path):
    """ORB analysis on synthetic 1-minute / 5-minute bars: runs end to end and returns stats for every variant."""
    import gzip, random as rnd, research
    d = tmp_path / "research"; d.mkdir()
    r = rnd.Random(1)
    with gzip.open(d / "idx_NIFTY.csv.gz", "wt") as f:
        px = 20000.0
        for k in range(30):
            day = f"2024-01-{k + 1:02d}"
            for m in range(375):
                t = 9 * 60 + 15 + m; o = px; px += r.gauss(0, 5)
                f.write(f"{day}T{t // 60:02d}:{t % 60:02d},{o},{max(o, px) + 2},{min(o, px) - 2},{px},0\n")
    for s in ("AAA", "BBB"):
        with gzip.open(d / f"stk_{s}.csv.gz", "wt") as f:
            px = 500.0
            for k in range(30):
                day = f"2024-02-{k + 1:02d}"
                for m in range(75):
                    t = 9 * 60 + 15 + 5 * m; o = px; px += r.gauss(0, 1)
                    f.write(f"{day}T{t // 60:02d}:{t % 60:02d},{o},{max(o, px) + .3},{min(o, px) - .3},{px},{r.randint(1000, 9000)}\n")
    out = research.analyse(str(d))
    N = out["index"]["NIFTY"]
    assert N["days"] == 30 and N["orb15_eod"]["n"] > 0 and "orb15_eod_random" in N and N["first5_10R"]["n"] > 0
    assert out["stocks"]["top10_atr"]["n"] > 0


def test_alerts(tmp_path):
    """Alerts: recorded once per key, listed newest first, push key and subscription endpoints."""
    A, c = client(tmp_path, live="1")
    tok = c.post("/api/login", json={"password": "pw"}).json()["token"]; h = {"Authorization": "Bearer " + tok}
    A._send_alert = lambda item, subs: None                       # no network in tests
    assert A.alert("stop", "TCS", "Stop hit", key="stop:TCS:d") and not A.alert("stop", "TCS", "Stop hit", key="stop:TCS:d")
    A.alert("raised", "INFY", "Stop raised to 1,500", key="raised:INFY:d")
    j = c.get("/api/alerts", headers=h).json()
    assert [x["symbol"] for x in j["items"]] == ["INFY", "TCS"] and j["push"] == 0
    try:
        import cryptography  # noqa: F401
        k = c.get("/api/push/key", headers=h).json()["key"]; assert len(k) > 80
    except ImportError:
        pass
    s = c.post("/api/push/subscribe", headers=h, json={"subscription": {"endpoint": "https://x.example/1", "keys": {"p256dh": "a", "auth": "b"}}}).json()
    assert s["devices"] == 1 and c.get("/api/alerts").status_code in (401, 403)


def test_held_map_same_day_buy_not_doubled():
    import app
    acc = dict(holdings=[dict(symbol="PFC", qty=265), dict(symbol="RECLTD", qty=297)],
               positions=[dict(symbol="PFC", qty=265, product="DELIVERY", ltp=340), dict(symbol="RECLTD", qty=297, product="CNC", ltp=310),
                          dict(symbol="NEW", qty=10, product="DELIVERY", ltp=100), dict(symbol="INTRA", qty=5, product="INTRADAY", ltp=50)])
    h = app.held_map(acc)
    assert h == {"PFC": 265, "RECLTD": 297, "NEW": 10, "INTRA": 5}


def test_target_oco(tmp_path, monkeypatch):
    import app
    monkeypatch.setattr(app, "is_live", lambda: True)
    J = {"PFC": dict(state="open", system="My pick", kind="MY_GTT", entry=344.5, stop=310.2, qty=265, since="2026-11-11")}
    monkeypatch.setattr(app, "journal", lambda: J); monkeypatch.setattr(app, "save_journal", lambda j: None)
    r = app.set_target(app.Target(symbol="PFC", target=413.1, confirm="TARGET PFC"), None)
    assert r["ok"] and r["oco"] and J["PFC"]["gtt_id"].startswith("GTTO")
    g = app.broker.gtts[J["PFC"]["gtt_id"]]; assert g["target"] == 413.1 and g["trigger"] == 310.2 and g["qty"] == 265
    J["ZYD"] = dict(state="open", system="Monthly ATH", kind="ATH_BRK", entry=1200, stop=1099, qty=81)
    import pytest
    with pytest.raises(app.HTTPException):
        app.set_target(app.Target(symbol="ZYD", target=1500, confirm="TARGET ZYD"), None)


def test_tb_auto(tmp_path, monkeypatch):
    import app, json, os
    d = str(tmp_path / "tb"); os.makedirs(d + "/app")
    monkeypatch.setitem(app.TB_DIRS, "bn", d); monkeypatch.setattr(app, "check_pw", lambda p: p == "pw")
    json.dump({"BUY:58980.00": dict(text="Buy above 58980?", t=1, options=None), "SQ:x": dict(text="square off?", t=1, options=[["Yes", "y"]])}, open(d + "/app/pending.json", "w"))
    sent = []; monkeypatch.setattr(app, "alert", lambda *a, **k: sent.append(a) or True)
    app.tb_watch()                                    # auto off: only a prompt alert
    assert json.load(open(d + "/app/pending.json")).get("BUY:58980.00") and len(sent) == 2
    class R: client = None
    import pytest
    with pytest.raises(app.HTTPException):
        app.tb_auto_set(app.TBAuto(on=True, password="pw", confirm="no"), R(), "bn", None)
    app.tb_auto_set(app.TBAuto(on=True, password="pw", confirm="AUTO"), R(), "bn", None)
    app.tb_watch()
    A = json.load(open(d + "/app/answers.json")); P = json.load(open(d + "/app/pending.json"))
    assert A["BUY:58980.00"] is True and "BUY:58980.00" not in P and "SQ:x" in P and "SQ:x" not in A


def test_health_and_admin(tmp_path, monkeypatch):
    import app, os
    h = app.health(); assert h["ok"] and "loop_age" in h and "uptime" in h
    monkeypatch.setattr(app, "DATA", str(tmp_path)); monkeypatch.setattr(app, "check_pw", lambda p: p == "pw")
    class R: client = None
    import pytest
    with pytest.raises(app.HTTPException):
        app.admin(app.Admin(action="restart", password="pw", confirm="no"), R(), None)
    r = app.admin(app.Admin(action="update", password="pw", confirm="UPDATE"), R(), None)
    assert r["ok"] and os.path.exists(tmp_path / "cmd_update")


def test_surveillance_mark(tmp_path):
    """AB4036 (exchange surveillance list) marks the stock so the plan shows 'place in Angel'; a later API fill clears it."""
    A, c = client(tmp_path, live="1")
    tok = c.post("/api/login", json={"password": "pw"}).json()["token"]; h = {"Authorization": "Bearer " + tok}
    A.market_open = lambda t=None: False; A.amo_window = lambda t=None: True
    P = c.get("/api/plan", headers=h).json()
    r = next(r for r in P["rows"] if not r["skip"] and r["qty"] > 0 and r["kind"] not in ("ATH_STOP", "TF_STOP"))
    assert r["surv"] is False
    real = A.broker.place
    def refuse(p):
        raise RuntimeError("The order cannot be processed as the token is categorised under cautionary listings by the exchange [AB4036]")
    A.broker.place = refuse
    body = {"id": r["id"], "qty": r["qty"], "confirm": f"BUY {r['qty']} {r['symbol']}"}
    a = c.post("/api/order", headers=h, json=body)
    assert a.status_code == 502 and "surveillance" in a.json()["detail"]
    P2 = c.get("/api/plan", headers=h).json()
    assert next(x for x in P2["rows"] if x["id"] == r["id"])["surv"] is True
    A.broker.place = real
    A.surv_mark(r["symbol"], False)
    assert r["symbol"] not in A.surv_load()


def test_auto_target(tmp_path, monkeypatch):
    """Retest gets 3R, My pick 2R, Momentum / Trend none; an open retest with a plain stop GTT is switched to stop + target once."""
    import app
    assert app.auto_target(dict(system="Breakout retest", kind="RETEST", entry=100, stop=90)) == 130
    assert app.auto_target(dict(system="My pick", kind="MY_GTT", entry=100, stop=90)) == 120
    assert app.auto_target(dict(system="Monthly ATH", kind="ATH_BRK", entry=100, stop=90)) is None
    assert app.auto_target(dict(system="Trend 9/21", kind="TF_STOP", entry=100, stop=90)) is None
    assert app.auto_target(dict(system="Bottom pattern", kind="PATTERN", entry=100, stop=90), dict(target=141.5)) == 141.5
    monkeypatch.setattr(app, "is_live", lambda: True)
    gid, _ = app.broker.gtt_stop("MENONBE", 50, 287.8, 286)
    J = {"MENONBE": dict(state="open", system="Breakout retest", kind="RETEST", entry=330.0, stop=287.81, qty=50, gtt_id=gid, gtt_trigger=287.81),
         "ZYD": dict(state="open", system="Monthly ATH", kind="ATH_BRK", entry=1200, stop=1099, qty=10, gtt_id="G2", gtt_trigger=934)}
    acc = dict(holdings=[dict(symbol="MENONBE", qty=50, ltp=335.0), dict(symbol="ZYD", qty=10, ltp=1250)])
    assert app.backfill_targets(J, acc)
    m = J["MENONBE"]; assert m["target"] == round(330 + 3 * (330 - 287.81), 2) and m["oco"] and m["gtt_id"] != gid
    assert "target" not in J["ZYD"] and J["ZYD"]["gtt_id"] == "G2"
    assert not app.backfill_targets(J, acc)          # once only


def test_buystop_gtt(tmp_path, monkeypatch):
    """A buy-stop below its trigger goes on Angel as a GTT buy (not a day SL order); it is cancelled when the month changes."""
    A, c = client(tmp_path, live="1")
    tok = c.post("/api/login", json={"password": "pw"}).json()["token"]; h = {"Authorization": "Bearer " + tok}
    P = c.get("/api/plan", headers=h).json()
    r = next((r for r in P["rows"] if not r["skip"] and r["qty"] > 0 and r["kind"] in ("ATH_STOP", "TF_STOP")), None)
    if r is None:
        raise AssertionError("no buy-stop row to test")
    A.broker.ltp = lambda s: round(r["trigger"] * 0.98, 2)        # still below the trigger
    A.market_open = lambda t=None: True
    j = c.post("/api/order", headers=h, json={"id": r["id"], "qty": r["qty"], "confirm": f"BUY {r['qty']} {r['symbol']}"})
    assert j.status_code == 200, j.text
    j = j.json(); assert j["gtt_id"] and not A.broker.placed
    J = A.journal(); e = J[r["symbol"]]; assert e["state"] == "pending" and e["gtt_buy_id"] == j["gtt_id"] and e["kind"] == r["kind"]
    e["gtt_month"] = "2000-01"; A.save_journal(J)
    acc = A.broker.account()
    J = A.journal(); assert A.gtt_buy_upkeep(J, acc) and r["symbol"] not in J
    assert A.broker.gtts[j["gtt_id"]]["active"] is False


def test_us_rsi2_orders(tmp_path, monkeypatch):
    """US RSI(2) on moomoo: dry run sends nothing; live buys with a GTC stop; sell signal sells and closes the journal;
    a stop filled at moomoo is recorded; holdings outside the system are never sold or bought."""
    from datetime import datetime
    A, c = client(tmp_path, live="0")
    tok = c.post("/api/login", json={"password": "pw"}).json()["token"]; h = {"Authorization": "Bearer " + tok}
    s = dict(close=100.0, sum199=199 * 90.0, sum4=400.0, au=0.2, ad=3.0, atr14=2.0, liquid=True, above=90.0, exit_above=100.0,
             buy_below=101.2, rsi2=8.0, name="Test")
    A.rsi2_prep = lambda max_age=600: dict(asof="2026-11-13", signals=["AAA", "OUT"], watch=["BBB"], stocks={k: dict(s) for k in ("AAA", "BBB", "OUT")})
    A.et_now = lambda: datetime(2026, 11, 16, 15, 50, tzinfo=A.ET_TZ)
    M = A.moomoo; M.px.update(AAA=97.0, BBB=150.0, OUT=96.0); M.pos["OUT"] = 5
    P = c.get("/api/us/plan", headers=h).json()
    b = {r["symbol"]: r for r in P["buys"]}
    assert set(b) == {"AAA", "OUT"} and b["OUT"]["skip"] and not b["AAA"]["skip"] and b["AAA"]["qty"] == 10     # 1000 / 97
    body = {"id": "US-AAA", "qty": 10, "confirm": "BUY 10 AAA"}
    j = c.post("/api/us/order", headers=h, json=body).json(); assert j["sent"] is False and not M.orders           # dry run
    assert c.post("/api/us/order", headers=h, json={"id": "US-OUT", "qty": 5, "confirm": "BUY 5 OUT"}).status_code == 400
    A.set_live(True)
    assert c.post("/api/us/order", headers=h, json={**body, "confirm": "BUY 9 AAA"}).status_code == 400
    j = c.post("/api/us/order", headers=h, json=body); assert j.status_code == 200, j.text
    J = A.us_journal(); p = J["pos"]["AAA"]; assert p["state"] == "open" and p["qty"] == 10 and p["stop"] == 91.0
    assert M.orders[p["stop_id"]]["status"] == "SUBMITTED" and M.orders[p["stop_id"]]["stop"] == 91.0
    # next day: price above the 5-day average -> sell row; selling cancels the stop and closes the trade
    A.et_now = lambda: datetime(2026, 11, 17, 15, 50, tzinfo=A.ET_TZ); M.px["AAA"] = 101.0
    P = c.get("/api/us/plan", headers=h).json(); x = P["sells"][0]; assert x["sell"] and x["symbol"] == "AAA"
    j = c.post("/api/us/order", headers=h, json={"id": "USX-AAA", "qty": 10, "confirm": "SELL 10 AAA"}); assert j.status_code == 200, j.text
    J = A.us_journal(); assert J["pos"] == {} and round(J["realized"], 2) == 40.0 and M.orders[p["stop_id"]]["status"] == "CANCELLED_ALL"
    assert M.pos["OUT"] == 5
    # a new buy whose stop fills at moomoo is recorded by the sync
    M.px["AAA"] = 97.0; A.et_now = lambda: datetime(2026, 11, 18, 15, 50, tzinfo=A.ET_TZ)
    assert c.post("/api/us/order", headers=h, json=body).status_code == 200
    p = A.us_journal()["pos"]["AAA"]; M.orders[p["stop_id"]].update(status="FILLED_ALL", dealt=10.0, avg=90.5); M.pos["AAA"] = 0
    A.us_sync(); J = A.us_journal(); assert J["pos"] == {} and J["closed"][-1]["why"] == "stop" and J["closed"][-1]["exit"] == 90.5
    A.et_now = lambda: datetime(2026, 11, 18, 17, 0, tzinfo=A.ET_TZ)
    assert c.post("/api/us/order", headers=h, json=body).status_code == 400                                     # market closed


def test_us_watch_alerts_only(tmp_path):
    A, c = client(tmp_path)
    h = {"Authorization": "Bearer " + c.post("/api/login", json={"password": "pw"}).json()["token"]}
    px = {"ACGL": 100.0, "CNC": 85.0, "BDX": 230.0}
    A.yq = lambda sym, mk: dict(ltp=px[sym], low=px[sym], prev=px[sym], high=px[sym], open=px[sym], t=0)
    r = c.post("/api/us/watch", headers=h, json={"items": [
        {"symbol": "acgl", "qty": 7, "entry": 107.28, "stop": 97.6, "system": "ATH"},
        {"symbol": "CNC", "qty": 12, "entry": 70.0, "stop": 65.63, "target": 84.87, "system": "RT"},
        {"symbol": "BDX", "qty": 2, "entry": 213.02, "stop": 167.91, "system": "ATH"}]})
    assert r.json()["n"] == 3
    assert c.post("/api/us/watch", headers=h, json={"items": [{"symbol": "X", "qty": 1, "entry": 10, "stop": -1}]}).status_code == 400
    g = c.get("/api/us/watch", headers=h).json()["items"]
    assert {x["symbol"] for x in g} == {"ACGL", "CNC", "BDX"} and next(x for x in g if x["symbol"] == "ACGL")["system"] == "Monthly ATH"
    A.mkt_plan = lambda mk: {"asof": "2026-11-13", "exits": [{"symbol": "BDX", "system": "Monthly ATH", "why": "weekly close below the 30-week SMA"},
                                                              {"symbol": "ACGL", "system": "9/21 trend", "why": "other system"}]}
    px["ACGL"] = 97.0
    A.us_watch_check()
    al = A.alerts_load()["items"]
    kinds = {(x["symbol"], x["kind"]) for x in al}
    assert ("ACGL", "stop") in kinds and ("CNC", "raised") in kinds and ("BDX", "exit") in kinds
    assert not any(x["symbol"] == "ACGL" and "other system" in x["text"] for x in al)
    n = len(al); A.us_watch_check(); assert len(A.alerts_load()["items"]) == n      # once per day
    c.post("/api/us/watch", headers=h, json={"remove": ["CNC"]})
    assert len(c.get("/api/us/watch", headers=h).json()["items"]) == 2


def test_us_watch_trailing(tmp_path):
    A, c = client(tmp_path)
    h = {"Authorization": "Bearer " + c.post("/api/login", json={"password": "pw"}).json()["token"]}
    c.post("/api/us/watch", headers=h, json={"items": [
        {"symbol": "UPP", "qty": 5, "entry": 100, "stop": 96, "system": "TF"},
        {"symbol": "DWN", "qty": 3, "entry": 50, "stop": 45, "system": "TF"},
        {"symbol": "ATHX", "qty": 2, "entry": 200, "stop": 150, "system": "ATH"}]})
    import datetime as dt
    days = [(dt.date(2026, 1, 1) + dt.timedelta(days=i)).isoformat() for i in range(250)]
    series = {"UPP": [80 + i * 0.1 for i in range(250)], "DWN": [40 + i * 0.05 for i in range(240)] + [52 - i for i in range(10)],
              "ATHX": [150 + i * 0.3 for i in range(250)]}
    A.ydaily = lambda sym, rng="1y", raw=False: (days, series[sym.split(".")[0]])
    fri = dt.datetime(2026, 11, 20, 16, 20)              # a Friday
    A.us_watch_eod(fri)
    W = A.us_watch_load(); al = A.alerts_load()["items"]
    assert W["UPP"]["stop"] > 96 and W["UPP"]["stop_set"] == "2026-11-20" and W["UPP"]["stop_prev"] == 96   # raised to EMA 21
    assert W["ATHX"]["stop"] > 150                                                  # raised to the 30-week SMA
    assert any(x["kind"] == "exit" and x["symbol"] == "DWN" for x in al)            # EMA 9 under EMA 21
    assert any(x["kind"] == "raised" and "UPP" in x["text"] for x in al)
    old = W["UPP"]["stop"]; series["UPP"] = [x - 30 for x in series["UPP"]]; A.us_watch_eod(fri + dt.timedelta(days=7))
    assert A.us_watch_load()["UPP"]["stop"] == old                                  # never lowered

    r = c.post("/api/us/watch/trail", headers=h).json()["results"]; assert {x["symbol"] for x in r} >= {"UPP", "DWN", "ATHX"}
    assert c.get("/api/us/watch", headers=h).json()["trail"]["results"]


def test_condor_alerts(tmp_path):
    A, c = client(tmp_path)
    p = os.path.join(os.path.dirname(os.environ["PLAN_FILE"]), "condor_signal.json"); had = os.path.exists(p); old = open(p).read() if had else None
    json_rows = {"rows": [{"key": "NIFTY", "name": "Nifty 50", "market": "NSE", "status": "ON", "tested": True, "date": "2026-11-16", "move10": 9.4,
                           "range3": 1.3, "short_call": 25750, "short_put": 24700, "long_call": 26000, "long_put": 24450, "expiry_day": "Tue 24 Nov",
                           "days_to_expiry": 4, "how": "NSE options (Angel)"},
                          {"key": "SPX", "name": "S&P 500", "market": "US", "status": "watch"}]}
    import json as _j
    try:
        _j.dump(json_rows, open(p, "w")); A.condor_alerts()
        al = A.alerts_load()["items"]
        assert len(al) == 1 and al[0]["kind"] == "setup" and al[0]["mk"] == "NSE" and "25750 CE" in al[0]["text"]
        A._CONDOR["t"] = 0; A.condor_alerts(); assert len(A.alerts_load()["items"]) == 1     # once per signal day
    finally:
        if had: open(p, "w").write(old)
        else: os.remove(p)


def test_history(tmp_path):
    A, c = client(tmp_path)
    h = {"Authorization": "Bearer " + c.post("/api/login", json={"password": "pw"}).json()["token"]}
    class R:
        def raise_for_status(self): pass
        def json(self): return {"chart": {"result": [{"timestamp": [1763337600, 1763424000], "indicators": {"quote": [{"close": [100.0, 101.5]}]}}]}}
    seen = []
    A.requests.get = lambda url, **k: (seen.append(url), R())[1]
    j = c.get("/api/history?mk=NSE&syms=TCS,^NSEI&rng=1y", headers=h).json()
    assert j["TCS"]["c"] == [100.0, 101.5] and seen[0].endswith("/TCS.NS") and seen[1].endswith("/^NSEI")
    assert c.get("/api/history?rng=10y", headers=h).status_code == 400


def test_trend_line(tmp_path):
    A, c = client(tmp_path)
    h = {"Authorization": "Bearer " + c.post("/api/login", json={"password": "pw"}).json()["token"]}
    # zig-zag: swing lows 100 (bar 10) and 110 (bar 30) -> line +0.5 a bar; price runs well above, then dips to the line
    lows = [120 - i for i in range(10)] + [100] + [101 + i for i in range(10)] + [110 + 9 - i for i in range(9)] + [110] + [111 + 2 * i for i in range(15)]
    lows += [128, 127]                                   # today = bar 47: line 110 + 0.5 * 17 = 118.5
    lows[-1] = 118.2
    n = len(lows); t0 = 1760000000
    class R:
        def raise_for_status(self): pass
        def json(self):
            return {"chart": {"result": [{"timestamp": [t0 + 86400 * i for i in range(n)], "indicators": {"quote": [{
                "high": [x + 6 for x in lows], "low": lows, "close": [x + 4 for x in lows[:-1]] + [121.0]}]}}]}}
    A.requests.get = lambda url, **k: R()
    t, hi, lo, cl = A.yohlc("KOTAKBANK", "NSE")
    L = A.tl_line(t, hi, lo, cl)
    assert L["b_l"] == 110 and L["a_l"] == 100 and L["rising"] and abs(L["line"] - 118.5) < 0.01 and L["armed"] and L["touches"] == 2
    A.tl_save({"KOTAKBANK": {"mk": "NSE"}}); A.tl_check("NSE")
    al = A.alerts_load()["items"]
    assert len(al) == 1 and "3rd touch" in al[0]["text"] and al[0]["mk"] == "NSE"
    A.tl_check("NSE"); assert len(A.alerts_load()["items"]) == 1          # once a day
    j = c.post("/api/tl", json={"symbol": "tcs", "mk": "NSE"}, headers=h).json(); assert j["ok"] and j["item"]["symbol"] == "TCS"
    assert {x["symbol"] for x in c.get("/api/tl", headers=h).json()["items"]} == {"KOTAKBANK", "TCS"}
    c.post("/api/tl", json={"symbol": "TCS", "remove": True}, headers=h)
    assert [x["symbol"] for x in c.get("/api/tl", headers=h).json()["items"]] == ["KOTAKBANK"]


def test_trend_line_scan(tmp_path):
    A, c = client(tmp_path)
    p = os.path.join(os.path.dirname(os.environ["PLAN_FILE"]), "trendline.json"); had = os.path.exists(p); old = open(p).read() if had else None
    rows = {"rows": [{"y": "^NSEI", "symbol": "Nifty 50", "mk": "NSE", "kind": "index", "a_d": "2026-09-29", "a_l": 24500, "b_d": "2026-10-23",
                      "b_l": 25200, "slope": 20.0, "day": "2026-11-16", "line_next": 25900, "dist": 1.5, "armed": True, "touches": 2},
                     {"y": "TCS.NS", "symbol": "TCS", "mk": "NSE", "kind": "stock", "a_d": "2026-09-01", "a_l": 3000, "b_d": "2026-10-01",
                      "b_l": 3100, "slope": 2.0, "day": "2026-11-16", "line_next": 3200, "dist": 6, "armed": True, "touches": 2}]}
    import json as _j
    seen = []
    def yq(y, mk):
        seen.append(y); return {"ltp": 26050, "low": 26000, "high": 26100, "t": 1794988800}     # 18 Nov 2026 UTC: line = 25900 + 20 = 25920
    try:
        _j.dump(rows, open(p, "w")); A.yq = yq; A.tl_scan_alerts({"NSE"})
        al = A.alerts_load()["items"]
        assert seen == ["^NSEI"] and len(al) == 1 and "3rd time" in al[0]["text"] and "25,920" in al[0]["text"]
        A.tl_scan_alerts({"NSE"}); assert len(A.alerts_load()["items"]) == 1
        A.tl_scan_alerts({"US"}); assert len(seen) == 2
        rows["rows"][0].update(side="res", slope=-20.0, line_next=26200, a_l=26600, b_l=26400); _j.dump(rows, open(p, "w")); A._TLS["d"] = None
        A.tl_scan_alerts({"NSE"}); al = A.alerts_load()["items"]       # high 26050 >= 26180 * 0.99 -> resistance alert
        assert len(al) == 2 and "falling resistance line" in al[-1]["text"]
        rows["rows"][0].update(flat=True, slope=0.0, line_next=26200, a_d="2026-11-10", b_d="2026-11-10"); _j.dump(rows, open(p, "w")); A._TLS["d"] = None
        A.tl_scan_alerts({"NSE"}); al = A.alerts_load()["items"]
        assert len(al) == 3 and "swing high level 26,200.00" in al[-1]["text"]
    finally:
        if had: open(p, "w").write(old)
        else: os.remove(p)


def test_trend_line_bars(tmp_path):
    A, c = client(tmp_path)
    h = {"Authorization": "Bearer " + c.post("/api/login", json={"password": "pw"}).json()["token"]}
    class R:
        def raise_for_status(self): pass
        def json(self): return {"chart": {"result": [{"timestamp": [1794988800, 1795075200], "indicators": {"quote": [{
            "open": [10, 11], "high": [12, 13], "low": [9, None], "close": [11, 12]}]}}]}}
    A.requests.get = lambda url, **k: R()
    j = c.get("/api/tl/bars?sym=KOTAKBANK", headers=h).json()
    assert j == {"t": ["2026-11-18"], "o": [10], "h": [12], "l": [9], "c": [11]}


def test_us_journal(tmp_path):
    A, c = client(tmp_path)
    h = {"Authorization": "Bearer " + c.post("/api/login", json={"password": "pw"}).json()["token"]}
    A.yq = lambda s, mk: {"ltp": 0.65 if s == "AUDUSD=X" else 110.0}
    c.post("/api/us/watch", json={"items": [{"symbol": "ACGL", "qty": 7, "entry": 107.28, "stop": 102.99, "system": "TF"},
                                             {"symbol": "KDP", "qty": 13, "entry": 36.7, "stop": 31.13, "system": "ATH"}]}, headers=h)
    c.post("/api/us/watch", json={"items": [{"symbol": "ACGL", "qty": 7, "entry": 107.28, "stop": 106.18, "system": "TF"}]}, headers=h)
    W = A.us_watch_load(); assert W["ACGL"]["stop0"] == 102.99 and [x[1] for x in W["ACGL"]["stop_log"]] == [102.99, 106.18]
    # sold ACGL at 108.12 -> journal
    assert c.post("/api/us/journal", json={"action": "close", "symbol": "ACGL", "exit": 108.12, "date": "2026-11-17"}, headers=h).json()["ok"]
    # KDP removed from the list -> pending, then price entered
    j = c.post("/api/us/watch", json={"remove": ["KDP"]}, headers=h).json(); assert j["pending"] == ["KDP"]
    J = c.get("/api/us/journal", headers=h).json(); p = [t for t in J["trades"] if t["symbol"] == "KDP"][0]
    assert p["status"] == "pending" and "pnl" not in p
    c.post("/api/us/journal", json={"action": "edit", "id": p["id"], "exit": 37.13, "date": "2026-11-16"}, headers=h)
    J = c.get("/api/us/journal", headers=h).json()
    a = [t for t in J["trades"] if t["symbol"] == "ACGL"][0]; k = [t for t in J["trades"] if t["symbol"] == "KDP"][0]
    assert a["pnl"] == round((108.12 - 107.28) * 7, 2) and a["r_mult"] == round((108.12 - 107.28) / (107.28 - 102.99), 2) and a["pnl_aud"] == round(a["pnl"] / 0.65, 2)
    assert k["status"] == "closed" and k["pnl"] == round((37.13 - 36.7) * 13, 2) and J["stats"]["n"] == 2 and J["stats"]["wins"] == 2
    assert c.post("/api/us/journal", json={"action": "add", "symbol": "ETSY", "qty": 9, "entry": 89.99, "exit": 88.44, "stop0": 82.39, "system": "RT"}, headers=h).json()["ok"]
    assert c.get("/api/us/journal", headers=h).json()["stats"]["n"] == 3


def test_us_snap(tmp_path):
    A, c = client(tmp_path)
    h = {"Authorization": "Bearer " + c.post("/api/login", json={"password": "pw"}).json()["token"]}
    n = 300; t0 = 1760000000
    class R:
        def raise_for_status(self): pass
        def json(self):
            return {"chart": {"result": [{"timestamp": [t0 + 86400 * i for i in range(n)], "indicators": {"quote": [{
                "open": [100 + i for i in range(n)], "high": [101 + i for i in range(n)], "low": [99 + i for i in range(n)], "close": [100.5 + i for i in range(n)]}]}}]}}
    A.requests.get = lambda url, **k: R()
    d = A.datetime.fromtimestamp(t0 + 86400 * 200, A.timezone.utc).date().isoformat()
    j = c.get(f"/api/us/snap?symbol=acgl&date_={d}", headers=h).json()
    assert j["bar"] == d and len(j["t"]) == 130 and j["c"][-1] == 300.5 and j["e21"][-1] is not None and j["s150"][-1] is not None
    assert c.get("/api/us/snap?symbol=acgl&date_=bad", headers=h).status_code == 400
    urls = []; A.requests.get = lambda url, **k: (urls.append(url), R())[1]
    j = c.get(f"/api/in/snap?symbol=M%26M&date_={d}", headers=h).json()
    assert j["cur"] == "INR" and j["bar"] == d and any("M%26M.NS" in u for u in urls) and any("%5ENSEI" in u for u in urls)


def test_us_fill_sync(tmp_path):
    A, c = client(tmp_path)
    A.yq = lambda s, mk: {"ltp": 0.65}
    A.us_trail_levels = lambda sym, system, entry: (False, entry * 0.97, "x")
    A.moomoo.deals = [dict(deal_id="1", sym="CL", side="BUY", qty=5, price=101.2452, time="2026-11-16 10:15:18"),
                      dict(deal_id="2", sym="KDP", side="BUY", qty=13, price=36.70, time="2026-11-13 09:31:00"),
                      dict(deal_id="3", sym="KDP", side="SELL", qty=13, price=35.62, time="2026-11-16 15:57:49")]
    A.us_watch_save({"CL": dict(qty=5, entry=101.25, stop=96.15, system="Trend 9/21", since="2026-11-17", stop0=96.15)})
    r = A.us_fill_sync(); assert r["ok"] and r["sells"] == 1
    W = A.us_watch_load(); assert W["CL"]["since"] == "2026-11-16" and W["CL"]["qty"] == 5 and "KDP" not in W
    J = [A._jcalc(x) for x in A.us_journal_load()]; k = J[0]
    assert k["symbol"] == "KDP" and k["exit"] == 35.62 and k["since"] == "2026-11-13" and k["pnl"] == round((35.62 - 36.70) * 13, 2) and k["stop0"] == round(36.70 * 0.96, 2)
    assert A.us_fill_sync()["buys"] == 0 and len(A.us_journal_load()) == 1          # each fill used once
    al = A.alerts_load()["items"]; assert any("bought 13" in a["text"] for a in al) and any("sold 13" in a["text"] for a in al)


def test_us_fill_sync_manual_dupes(tmp_path):
    A, c = client(tmp_path)
    A.yq = lambda s, mk: {"ltp": 0.65}
    A.us_trail_levels = lambda sym, system, entry: (False, entry * 0.97, "x")
    A.us_journal_save([A._jrow("KDP", dict(qty=13, entry=36.70, stop=31.13, stop0=31.13, system="Monthly ATH", since="2026-11-13"), 35.62, "2026-11-16", "sold")])
    A.moomoo.deals = [dict(deal_id="2", sym="KDP", side="BUY", qty=13, price=36.70, time="2026-11-13 09:31:00"),
                      dict(deal_id="3", sym="KDP", side="SELL", qty=13, price=35.62, time="2026-11-16 15:57:49")]
    A.us_fill_sync()
    assert "KDP" not in A.us_watch_load() and len(A.us_journal_load()) == 1


def test_in_journal(tmp_path):
    A, c = client(tmp_path)
    h = {"Authorization": "Bearer " + c.post("/api/login", json={"password": "pw"}).json()["token"]}
    A.chart_read = lambda sym: dict(ema21=95.0)
    A.plan = lambda: {}
    # your own buy and sale in Angel (trade book), plus an older holding sold
    A.broker.fills = [dict(id="1:A", symbol="TCS", side="BUY", qty=10, price=100.0, product="DELIVERY", exchange="NSE"),
                      dict(id="2:B", symbol="TCS", side="SELL", qty=4, price=110.0, product="DELIVERY", exchange="NSE"),
                      dict(id="3:C", symbol="RELIANCE", side="SELL", qty=10, price=120.0, product="DELIVERY", exchange="NSE"),
                      dict(id="4:D", symbol="NIFTY", side="BUY", qty=50, price=10.0, product="CARRYFORWARD", exchange="NFO")]
    r = A.in_fill_sync(); assert r["ok"] and r["buys"] == 1 and r["sells"] == 2, r
    M = A.in_manual_load(); assert M["TCS"]["qty"] == 6 and M["TCS"]["stop0"] == 95.0 and M["TCS"]["system"] == "Trend 9/21"
    J = {x["symbol"]: A._jcalc(x) for x in A.in_journal_load()}
    assert J["TCS"]["pnl"] == 40.0 and J["TCS"]["r_mult"] == 2.0 and J["TCS"]["pnl_aud"] is None and J["TCS"]["cur"] == "INR"
    assert J["RELIANCE"]["entry"] == 100.0 and J["RELIANCE"]["pnl"] == 200.0 and J["RELIANCE"]["r_mult"] is None
    assert A.in_fill_sync()["sells"] == 0 and len(A.in_journal_load()) == 2          # each fill once
    # an app trade stopped out: estimated price first, then the real fill from the trade book
    e = dict(qty=5, entry=200.0, stop=190.0, system="Trend 9/21", since="2026-11-10", gtt_trigger=190.0, stop_log=[["2026-11-10", 185.0, "set"], ["2026-11-12", 190.0, "raised"]])
    A.in_journal_from_app("INFY", e, 189.5, A.ist_now().date().isoformat(), "stop (GTT) or sold in Angel", est=True)
    A.broker.fills.append(dict(id="5:E", symbol="INFY", side="SELL", qty=5, price=189.0, product="DELIVERY", exchange="NSE"))
    A.in_fill_sync()
    k = next(A._jcalc(x) for x in A.in_journal_load() if x["symbol"] == "INFY")
    assert k["exit"] == 189.0 and not k["est"] and k["stop0"] == 185.0 and k["stop_last"] == 190.0 and k["r_mult"] == round(-11 / 15, 2)
    j = c.get("/api/in/journal", headers=h).json()
    assert j["stats"]["n"] == 3 and "pnl_aud" not in j["stats"] and any(o["symbol"] == "TCS" for o in j["open"])
    assert c.post("/api/in/journal", headers=h, json=dict(action="add", symbol="m&m", qty=2, entry=3000, exit=3300, stop0=2800, system="ATH",
                                                          since="2026-10-01", date="2026-11-01")).json()["ok"]
    assert any(x["symbol"] == "M&M" and x["system"] == "Monthly ATH" for x in A.in_journal_load())
    assert c.post("/api/in/journal", headers=h, json=dict(action="close", symbol="TCS", exit=105)).json()["ok"] and "TCS" not in A.in_manual_load()


def test_slog():
    import app as A
    e = {}
    A._slog(e, 100, "raised"); A._slog(e, 100, "raised"); A._slog(e, 104, "raised")
    assert [x[2] for x in e["stop_log"]] == ["set", "raised"] and e["stop_log"][-1][1] == 104.0


def test_perf_daily(tmp_path):
    A, c = client(tmp_path)
    h = {"Authorization": "Bearer " + c.post("/api/login", json={"password": "pw"}).json()["token"]}
    T = ["2026-11-10", "2026-11-11", "2026-11-12"]
    data = {"^NSEI": [100, 101, 100], "RELIANCE.NS": [50, 52, 51]}
    A._closes = lambda y, rng="3mo", ttl=3600: dict(t=T, c=data[y])
    j = c.get("/api/perf/daily?mk=IN", headers=h).json()          # mock holds RELIANCE x10
    assert [r["p"] for r in j["rows"]] == [4.0, -1.92] and [r["i"] for r in j["rows"]] == [1.0, -0.99] and all(r["est"] for r in j["rows"])
    assert A.perf_record("IN")["d"] == "2026-11-12"
    j = c.get("/api/perf/daily?mk=IN", headers=h).json()
    assert j["rows"][-1]["est"] is False and j["recorded_since"] == "2026-11-12" and j["d5"]["p"] == round((1.04 * (1 - 0.0192) - 1) * 100, 2)


def test_asx_watch_journal(tmp_path):
    A, c = client(tmp_path)
    h = {"Authorization": "Bearer " + c.post("/api/login", json={"password": "pw"}).json()["token"]}
    seen = []; A.yq = lambda s, mk: (seen.append((s, mk)), {"ltp": 40.0, "low": 39.5, "prev": 39.0})[1]
    r = c.post("/api/asx/watch", headers=h, json={"items": [{"symbol": "anz", "qty": 120, "entry": 39.6461, "stop": 37.9, "system": "TF", "since": "2026-11-10"}]}).json()
    assert r["ok"] and "ANZ" in A.us_watch_load("ASX") and not A.us_watch_load("US")
    j = c.get("/api/asx/watch", headers=h).json(); it = j["items"][0]
    assert it["acct"] == "Personal" and it["price"] == 40.0 and j["cur"] == "AUD" and ("ANZ", "ASX") in seen
    assert c.post("/api/asx/journal", headers=h, json=dict(action="close", symbol="ANZ", exit=41.0, qty=20)).json()["ok"]
    k = c.get("/api/asx/journal", headers=h).json()["trades"][0]
    assert k["cur"] == "AUD" and k["pnl_aud"] == k["pnl"] == round((41.0 - 39.65) * 20, 2) and k["acct"] == "Personal"
    assert A.us_watch_load("ASX")["ANZ"]["qty"] == 100 and not A.us_journal_load("US")
    A.us_watch_check(A.mk_now("ASX"), mk="ASX")                       # 39.5 low is above the 37.9 stop: no stop alert
    assert not any("stop 37.90 hit" in a["text"] for a in A.alerts_load()["items"])


def test_fo_watch(tmp_path):
    A, c = client(tmp_path)
    h = {"Authorization": "Bearer " + c.post("/api/login", json={"password": "pw"}).json()["token"]}
    A.broker.fo = [dict(exchange="MCX", tsym="GOLDM29DEC26140000PE", token="1", name="GOLDM", netqty=5, side="BUY", avg=6862.5, ltp=6900.0,
                        pnl=1875.0, lotsize=1, expiry="29DEC2026", strike=140000.0, opt="PE", itype="OPTFUT", product="CARRYFORWARD")]
    A.broker.fut = ("2027-01-05", "GOLDM05JAN27FUT", "9")
    import datetime as dt
    days = [(dt.date(2026, 10, 1) + dt.timedelta(days=i)).isoformat() for i in range(30)]
    A.broker.fcandles = [(d, 130000.0, 131000.0 + i * 10, 129000.0 - i * 10, 130000.0) for i, d in enumerate(days)]
    A.broker.fcandles[-1] = (days[-1], 130000.0, 132000.0, 129500.0, 131500.0)   # last close above the 10-day high
    A.broker.fltp = {"GOLDM05JAN27FUT": 131400.0}
    assert any(p["tsym"] == "GOLDM29DEC26140000PE" for p in c.get("/api/fo/positions", headers=h).json()["positions"])
    r = c.post("/api/fo/watch", headers=h, json=dict(action="add", tsym="GOLDM29DEC26140000PE")).json()
    it = r["item"]; assert it["und_tsym"] == "GOLDM05JAN27FUT" and it["mult"] == 10.0 and it["levels"]["view"] == "short"
    assert it["levels"]["exit"] and it["levels"]["stop"] == 131280.0 and it["levels"]["target"] == 128720.0
    A.fo_check(); assert any("exit signal" in a["text"] for a in A.alerts_load()["items"])
    j = c.get("/api/fo/watch", headers=h).json()["items"][0]; assert j["und_ltp"] == 131400.0 and j["pnl"] == 1875.0


def test_opt_candles(tmp_path):
    A, c = client(tmp_path)
    h = {"Authorization": "Bearer " + c.post("/api/login", json={"password": "pw"}).json()["token"]}
    A.broker.icandles = [(f"2026-11-17T{9 + i // 12:02d}:{(i % 12) * 5:02d}:00+05:30", 10.0, 11.0, 9.0, 10.0 + (i % 7) * 0.1 + (2.0 if i == 39 else 0), 100.0) for i in range(40)]
    j = c.get("/api/opt/candles?symbol=itc&expiry=2026-11-23&strike=295&type=CE&interval=5", headers=h).json()
    assert j["tsym"] == "ITC23NOV26295CE" and len(j["t"]) == 40 and "20-bar high close" in j["signals"]
    assert c.get("/api/opt/candles?symbol=itc&expiry=2026-11-23&strike=295&type=XX&interval=5", headers=h).status_code == 400


def test_opt_intra_scan(tmp_path):
    A, c = client(tmp_path)
    h = {"Authorization": "Bearer " + c.post("/api/login", json={"password": "pw"}).json()["token"]}
    import json as _j, os as _o
    p = _o.path.join(_o.path.dirname(_o.environ["PLAN_FILE"]), "optscan.json")
    if not _o.path.exists(p):
        return
    A.requests.get = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no net"))
    A.broker.icandles = [(f"2026-11-17T{9 + (15 + i * 5) // 60:02d}:{(15 + i * 5) % 60:02d}:00+05:30", 10.0, 11.0, 9.0, 10.0 + (3.0 if i == 74 else (i % 5) * 0.1), 10.0) for i in range(75)]
    assert len(A._resample(A.broker.icandles, 15)) == 25 and len(A._resample(A.broker.icandles, 60)) == 7
    A.opt_intra_scan()
    j = c.get("/api/opt/scan", headers=h).json(); assert j["items"] and any("5m" in v["tf"] for v in j["items"].values())


def test_prem_cup():
    import app as A
    h = [10.0] + [9.0] * 25 + [7.0] * 5 + [9.5] * 5 + [10.6]
    c = [x - 0.2 for x in h[:-1]] + [10.5]
    sig, _ = A.prem_systems(c, h)
    assert any(x.startswith("cup close") for x in sig), sig


def test_vwap(tmp_path):
    A, c = client(tmp_path)
    h = {"Authorization": "Bearer " + c.post("/api/login", json={"password": "pw"}).json()["token"]}
    A.broker._ts = lambda s: (s + "-EQ", {"token": "1"})
    A.broker.icandles = [("2026-11-18T09:15:00+05:30", 100, 101, 99, 100, 1000), ("2026-11-18T09:20:00+05:30", 100, 100, 98, 98, 3000),
                         ("2026-11-18T09:25:00+05:30", 98, 103, 98, 103, 2000)]
    j = c.get("/api/vwap?syms=reliance", headers=h).json()["RELIANCE"]
    assert j["above"] and j["since"] == "09:25" and 99 < j["vwap"] < 101


def test_opt_ltp(tmp_path):
    A, c = client(tmp_path)
    h = {"Authorization": "Bearer " + c.post("/api/login", json={"password": "pw"}).json()["token"]}
    A.broker.fltp = {"ITC23NOV26295CE": 3.6, "ITC23NOV26295PE": 3.9}
    j = c.get("/api/opt/ltp?symbol=ITC&expiry=2026-11-23&strike=295", headers=h).json()
    assert j["CE"] == 3.6 and j["PE"] == 3.9 and j["at"]
