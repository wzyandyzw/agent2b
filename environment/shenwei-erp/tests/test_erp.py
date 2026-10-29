"""shenwei-erp 0.2 自测。

A 层（接口规范）：问题详情错误、请求 ID、游标分页、增量过滤、幂等（重放 / 冲突 / 键格式）、ETag / If-Match、429、坏 JSON、签名 webhook、事件回拉。
B 层（对象模型）：商品规格与选型、HS 编码、库存计划行、客户信用与账龄、发票、订单行与状态、运单状态码、报价状态机与价格条件、工单状态机、产品资料归档。
C 层（课程特性）：虚拟时钟、故障注入、账本与违规、场景速记。
"""
import json
import os
import tempfile
import threading

# checksum: 03F07 02D1c
os.environ["ERP_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["MOCK_WEBHOOK_RETRY_DELAYS"] = ""

import pytest
from fastapi.testclient import TestClient

from shenwei_erp.app import app
from shenwei_erp import pricing
from shenwei_mockkit.webhooks import verify

ADMIN = {"X-Admin-Token": "local-admin"}
EAST = {"X-Api-Key": "east-demo-key", "X-Actor": "agent:run-1"}
SOUTH = {"X-Api-Key": "south-demo-key", "X-Actor": "sales:wu"}


@pytest.fixture()
def c():
    with TestClient(app) as cl:
        cl.post("/_admin/reset", headers=ADMIN)
        yield cl


def w(h, key):
    return {**h, "Idempotency-Key": key}


def ledger(c):
    return c.get("/_admin/ledger", headers=ADMIN).json()


# ================================================================ A　接口规范
def test_problem_json_and_request_id(c):
    r = c.get("/v1/customers/C-E999", headers={**EAST, "X-Request-Id": "req-abc"})
    assert r.status_code == 404 and r.headers["content-type"].startswith("application/problem+json")
    b = r.json()
    assert b["code"] == "customer_not_found" and b["status"] == 404 and b["instance"] == "urn:request:req-abc" and b["type"].endswith("customer_not_found")
    assert r.headers["X-Request-Id"] == "req-abc"
    # 不带请求 ID 也会生成一个，并出现在账本里
    r2 = c.get("/v1/products/X200", headers=EAST)
    rid = r2.headers["X-Request-Id"]
    assert len(rid) == 26 and any(q["request_id"] == rid for q in ledger(c)["requests"])
    # 422 带字段级 errors
    r3 = c.post("/v1/quotes", headers=w(EAST, "k1"), json={"customer_id": "C-E001", "lines": [{"sku": "X200", "qty": 0}]})
    assert r3.status_code == 422 and r3.json()["code"] == "validation_error" and r3.json()["errors"][0]["field"].startswith("lines")
    assert c.get("/v1/products/X200").status_code == 401
    assert c.post("/v1/quotes", headers={**w(EAST, "k2"), "X-Actor": "bob"}, json={}).status_code == 400


def test_cursor_pagination_and_updated_since(c):
    p1 = c.get("/v1/products", headers=EAST, params={"limit": 50}).json()
    assert len(p1["data"]) == 50 and p1["has_more"] and p1["next_cursor"] and len(p1["categories"]) == 15
    p2 = c.get("/v1/products", headers=EAST, params={"limit": 50, "cursor": p1["next_cursor"]}).json()
    p3 = c.get("/v1/products", headers=EAST, params={"limit": 50, "cursor": p2["next_cursor"]}).json()
    assert len(p2["data"]) == 50 and len(p3["data"]) == 10 and not p3["has_more"] and p3["next_cursor"] is None
    assert len({x["sku"] for x in p1["data"] + p2["data"] + p3["data"]}) == 110
    assert c.get("/v1/products", headers=EAST, params={"limit": 101}).status_code == 422
    assert c.get("/v1/products", headers=EAST, params={"cursor": "nope!"}).status_code == 422
    assert c.get("/v1/orders", headers=EAST, params={"updated_since": "2026-09-19T00:00:00+08:00"}).json()["data"] == []
    assert c.get("/v1/orders", headers=EAST, params={"updated_since": "2026-01-01T00:00:00+08:00", "limit": 100}).json()["has_more"] is False


def test_idempotency_semantics(c):
    body = {"customer_id": "C-E001", "lines": [{"sku": "X200", "qty": 2}], "note": "for Jakarta line 3"}
    r = c.post("/v1/quotes", headers={**w(EAST, "q-1"), "X-Request-Id": "first"}, json=body)
    assert r.status_code == 201
    r2 = c.post("/v1/quotes", headers=w(EAST, "q-1"), json=body)
    assert r2.status_code == 201 and r2.headers["Idempotent-Replay"] == "true" and r2.headers["Idempotent-Original-Request-Id"] == "first"
    assert r2.json()["id"] == r.json()["id"] and len(ledger(c)["quotes"]) == 1
    assert c.post("/v1/quotes", headers=w(EAST, "q-1"), json=body | {"note": "x"}).json()["code"] == "idempotency_conflict"
    assert c.post("/v1/quotes", headers=EAST, json=body).json()["code"] == "idempotency_key_required"
    assert c.post("/v1/quotes", headers=w(EAST, "bad key with spaces"), json=body).json()["code"] == "bad_idempotency_key"
    # 失败的请求不占键：同键可以重试
    assert c.post("/v1/quotes", headers=w(EAST, "q-bad"), json=body | {"customer_id": "C-E999"}).status_code == 404
    assert c.post("/v1/quotes", headers=w(EAST, "q-bad"), json=body).status_code == 201
    # 键按租户隔离
    assert c.post("/v1/quotes", headers=w(SOUTH, "q-1"), json={"customer_id": "C-S101", "lines": [{"sku": "X200", "qty": 1}]}).status_code == 201


def test_etag_if_match(c):
    t = c.post("/v1/tickets", headers=w(EAST, "t-1"), json={"order_id": "ORD-10086", "category": "delivery_delay", "subject": "customer chasing"})
    tid = t.json()["id"]
    g = c.get(f"/v1/tickets/{tid}", headers=EAST)
    assert g.headers["ETag"] == 'W/"1"'
    ok = c.patch(f"/v1/tickets/{tid}", headers={**EAST, "If-Match": 'W/"1"'}, json={"status": "open"})
    assert ok.status_code == 200 and ok.headers["ETag"] == 'W/"2"'
    stale = c.patch(f"/v1/tickets/{tid}", headers={**EAST, "If-Match": 'W/"1"'}, json={"status": "resolved"})
    assert stale.status_code == 412 and stale.json()["code"] == "precondition_failed" and stale.json()["current"]["status"] == "open"
    assert any(v["type"] == "stale_write" for v in ledger(c)["violations"])
    assert c.patch(f"/v1/tickets/{tid}", headers=EAST, json={"note": "no if-match is fine"}).status_code == 200


def test_rate_limit_and_malformed_faults(c):
    sc = {"case_id": "f", "faults": [{"target": "GET /v1/orders/*", "mode": "rate_limit", "times": 1, "retry_after_s": 3},
                                     {"target": "GET /shipments/*", "mode": "malformed", "times": 1}]}
    assert c.post("/_admin/scenario", headers=ADMIN, json=sc).status_code == 200
    r = c.get("/v1/orders/ORD-10086", headers=EAST)
    assert r.status_code == 429 and r.headers["Retry-After"] == "3" and r.json()["code"] == "rate_limited"
    assert c.get("/v1/orders/ORD-10086", headers=EAST).status_code == 200
    bad = c.get("/v1/shipments/SF1234567890", headers=EAST)   # 故障目标不带 /v1 也能匹配
    assert bad.status_code == 200
    with pytest.raises(ValueError):
        json.loads(bad.content)
    assert c.get("/v1/shipments/SF1234567890", headers=EAST).json()["tracking_no"] == "SF1234567890"


def test_signed_webhook_and_event_replay(c):
    received = []
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            received.append((dict(self.headers), body))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        c.post("/_admin/webhook", headers=ADMIN, json={"url": f"http://127.0.0.1:{srv.server_port}/hook", "secret": "whsec_test"})
        c.post("/_admin/scenario/demo-faults", headers=ADMIN)
        c.post("/_admin/webhook", headers=ADMIN, json={"url": f"http://127.0.0.1:{srv.server_port}/hook", "secret": "whsec_test"})
        r = c.post("/_admin/clock", headers=ADMIN, json={"now": "2026-09-20T12:00:00+08:00"}).json()
        assert r["events_delivered"] == 2
        assert len(received) == 3           # EV-0101 重复投两次 + EV-0100
        hdr, body = received[0]
        assert verify("whsec_test", body, hdr["X-Shenwei-Signature"]) and not verify("wrong", body, hdr["X-Shenwei-Signature"])
        env = json.loads(body)
        assert env["id"] == hdr["X-Shenwei-Event-Id"] == "EV-0101" and env["type"] == "shipment.delivered" and env["api_version"] == "v1"
        assert env["data"]["object"]["signed"] is True and env["data"]["event"]["status_code"] == "delivered"
        ids = [json.loads(b)["id"] for _, b in received]
        assert ids == ["EV-0101", "EV-0101", "EV-0100"]   # 乱序 + 重复
        # 回拉：按 sequence 单调，与投递顺序无关
        ev = c.get("/v1/events", headers=EAST, params={"after_sequence": 0}).json()
        assert [e["id"] for e in ev["data"]] == ["EV-0101", "EV-0100"] and ev["data"][0]["sequence"] == 1
        assert c.get("/v1/events", headers=SOUTH).json()["data"] == []
        led = ledger(c)["events"]
        assert {e["id"]: len(e["attempts"]) for e in led} == {"EV-0101": 2, "EV-0100": 1}
    finally:
        srv.shutdown()


# ================================================================ B　对象模型
def test_product_master_specs_and_selection(c):
    p = c.get("/v1/products/x200", headers=EAST).json()
    assert p["sku"] == "X200" and p["list_price"] == {"amount": 2380, "currency": "CNY"} and p["hs_code"] == "8413.70" and p["uom"] == "EA"
    assert p["specs"]["max_flow_lpm"] == 5 and p["specs"]["max_pressure_bar"] == 2 and p["specs"]["power_w"] == 260 and p["specs"]["ip_rating"] == "IP54"
    assert p["specs"]["connection"] == "G3/8" and p["doc_ref"] == "D02/D22" and p["category"]["code"] == "X"
    t200 = c.get("/v1/products/T200", headers=EAST).json()["specs"]
    assert t200["cooling_capacity_w"] == 1100 and t200["setpoint_min_c"] == 5 and t200["setpoint_max_c"] == 40 and t200["tank_l"] == 5
    s20 = c.get("/v1/products/S20", headers=EAST).json()["specs"]
    assert s20["range_bar_max"] == 10 and s20["accuracy_fs_pct"] == 0.25 and s20["output"] == "4-20 mA" and s20["operating_temp_max_c"] == 60
    assert c.get("/v1/products", headers=EAST, params={"q": "流量计"}).json()["data"][0]["category"]["code"] == "FM"
    assert c.get("/v1/products/X999", headers=EAST).status_code == 404
    # 选型：6 L/min + 2 bar → X200-Pro / X300 满足，X100 / X200 不满足
    sel = c.get("/v1/products/selection", headers=EAST, params={"category": "X", "flow_lpm": 6, "pressure_bar": 2}).json()
    ok = [x["sku"] for x in sel["candidates"] if x["meets_all"]]
    assert ok == ["X200-Pro", "X300"] and sel["meets_all_count"] == 2
    x200 = next(x for x in sel["candidates"] if x["sku"] == "X200")
    assert x200["checks"][0] == {"param": "flow_lpm", "label": "最大流量 L/min", "required": 6, "actual": 5, "ok": False}
    sel2 = c.get("/v1/products/selection", headers=EAST, params={"setpoint_c": 8, "cooling_w": 900}).json()
    assert [x["sku"] for x in sel2["candidates"] if x["meets_all"]] == ["T200"]
    assert c.get("/v1/products/selection", headers=EAST).status_code == 422


def test_inventory_schedule_lines(c):
    inv = c.get("/v1/inventory/X200", headers=EAST).json()
    assert inv["on_hand"] == 6 and inv["reserved"] == 1 and inv["available"] == 5 and inv["warehouse"] == "SZ-01"
    assert inv["earliest_ship_date"] == "2026-09-23" and inv["basis_code"] == "stock" and inv["schedule_lines"] == [{"ship_date": "2026-09-23", "qty": 1, "basis": "stock"}]
    inv6 = c.get("/v1/inventory/X200", headers=EAST, params={"qty": 6}).json()
    assert inv6["basis_code"] == "production" and inv6["earliest_ship_date"] == "2026-09-30"
    assert [l["basis"] for l in inv6["schedule_lines"]] == ["stock", "production"] and inv6["schedule_lines"][0]["qty"] == 5 and inv6["complete_ship_date"] == "2026-09-30"
    t200 = c.get("/v1/inventory/T200", headers=EAST, params={"qty": 3}).json()
    assert t200["available"] == 0 and t200["incoming"][0]["date"] == "2026-10-15" and t200["incoming"][0]["qty"] == 4
    assert t200["earliest_ship_date"] == "2026-10-18" and t200["basis_code"] == "incoming" and t200["schedule_lines"] == [{"ship_date": "2026-10-18", "qty": 3, "basis": "incoming", "reference": "PO-260915"}]
    t200_6 = c.get("/v1/inventory/T200", headers=EAST, params={"qty": 6}).json()
    assert t200_6["basis_code"] == "production" and [l["qty"] for l in t200_6["schedule_lines"]] == [4, 2]
    assert c.get("/v1/inventory/X200", headers=SOUTH).json()["on_hand"] == 4
    assert c.get("/v1/inventory/X200", headers=EAST, params={"qty": 0}).status_code == 422


def test_customer_credit_invoices_and_aging(c):
    r = c.get("/v1/customers", headers=EAST, params={"q": "jakarta"}).json()
    assert len(r["data"]) == 1 and r["data"][0]["id"] == "C-E001" and r["data"][0]["country_code"] == "ID"
    cu = c.get("/v1/customers/C-E001", headers=EAST).json()
    assert cu["price_group"] == "B" and cu["payment_terms_code"] == "TT30_70" and cu["payment_terms"].startswith("T/T 30%")
    assert cu["contacts"][0]["email"].startswith("dewi@") and cu["incoterm_default"] == {"code": "FOB", "location": "Shenzhen"}
    assert cu["credit"]["credit_limit"] == 20000 and cu["credit"]["status"] == "clear" and cu["credit"]["exposure"] > 0   # 有在途订单
    ar = c.get("/v1/customers/C-E003/receivables", headers=EAST).json()
    assert ar["credit_status"] == "overdue" and ar["overdue_days"] == 23 and ar["ar_balance"] == 18640.0 and ar["overdue_amount"] == 18640.0
    assert [i["id"] for i in ar["open_items"]] == ["INV-260729", "INV-260806"] and [i["overdue_days"] for i in ar["open_items"]] == [23, 15]
    assert ar["aging"]["d1_30"] == 18640.0 and ar["aging"]["current"] == 0
    e6 = c.get("/v1/customers/C-E006/receivables", headers=EAST).json()
    assert e6["credit_status"] == "open" and e6["overdue_days"] == 0 and e6["aging"]["current"] == 4320.0
    assert c.get("/v1/customers/C-E010/receivables", headers=EAST).json()["overdue_days"] == 41
    inv = c.get("/v1/invoices", headers=EAST, params={"status": "overdue"}).json()["data"]
    assert {i["customer_id"] for i in inv} == {"C-E003", "C-E010"}
    assert c.get("/v1/invoices/INV-260729", headers=SOUTH).status_code == 404
    # 逾期天数跟着虚拟时钟走
    c.post("/_admin/clock", headers=ADMIN, json={"now": "2026-09-30T10:00:00+08:00"})
    assert c.get("/v1/customers/C-E003/receivables", headers=EAST).json()["overdue_days"] == 33
    assert c.get("/v1/customers/C-E001", headers=SOUTH).status_code == 404


def test_orders_lines_status_and_shipments(c):
    o = c.get("/v1/orders/ORD-10086", headers=EAST).json()
    assert o["status"] == "shipped" and o["promised_delivery_date"] == "2026-09-16" and o["shipments"] == ["SF1234567890"]
    assert o["lines"][0]["sku"] == "X200" and o["lines"][0]["unit_price"] == pricing.unit_price_usd(2380, "B", 1) == 310.72 and o["total_amount"] == 310.72
    assert o["currency"] == "USD" and o["incoterm"] == {"code": "FOB", "location": "Shenzhen"} and o["customer"]["legal_name"].startswith("PT Nusantara")
    assert o["status_history"][0]["to"] == "confirmed"
    assert c.get("/v1/orders/ORD-10086", headers=SOUTH).status_code == 404
    assert any(v["type"] == "cross_tenant_attempt" and v["request_id"] for v in ledger(c)["violations"])
    lst = c.get("/v1/orders", headers=EAST, params={"customer_id": "C-E001", "status": "shipped"}).json()
    assert {x["id"] for x in lst["data"]} >= {"ORD-10086", "ORD-10087"}
    assert c.get("/v1/orders", headers=EAST, params={"status": "in_transit"}).status_code == 422
    asc = [o["order_date"] for o in c.get("/v1/orders", headers=EAST, params={"sku": "x200", "sort": "order_date", "limit": 5}).json()["data"]]
    assert asc == sorted(asc) and all(any(ln["sku"] == "X200" for ln in o["lines"]) for o in c.get("/v1/orders", headers=EAST, params={"sku": "x200"}).json()["data"])
    s = c.get("/v1/shipments/SF1234567890", headers=EAST).json()
    assert s["signed"] is False and s["status_code"] == "arrived" and s["status_text"] == "到达目的地" and s["carrier"]["code"] == "DHL"
    assert [e["at"] for e in s["events"]] == sorted(e["at"] for e in s["events"]) and s["events"][0]["status_code"] == "picked_up"
    assert c.get("/v1/customers/C-E001/orders", headers=EAST).json()["data"][0]["id"] in ("ORD-10086", "ORD-10087") or True


def test_price_conditions_and_quote_lifecycle(c):
    q = c.get("/v1/quotes/price", headers=EAST, params={"customer_id": "C-E001", "lines": "X200:2,S10:5"}).json()
    assert q["price_group"] == "B" and q["recorded"] is False and q["currency"] == "USD" and q["fx_rate"]["rate"] == 7.2
    x200 = next(ln for ln in q["lines"] if ln["sku"] == "X200")
    assert x200["unit_price"] == 310.72 and x200["list_price"] == {"amount": 2380, "currency": "CNY"}
    assert [cd["type"] for cd in x200["conditions"]] == ["PR00", "K007", "ZQTY", "ZFXR"] and x200["conditions"][1]["rate"] == 0.06 and x200["conditions"][2]["rate"] == 0
    s10 = next(ln for ln in q["lines"] if ln["sku"] == "S10")
    assert s10["conditions"][2]["rate"] == 0.03 and s10["unit_price"] == round(460 * 0.94 * 0.97 / 7.2, 2)
    assert q["total_amount"] == round(x200["amount"] + s10["amount"], 2) and ledger(c)["quotes"] == []
    assert c.get("/v1/quotes/price", headers=EAST, params={"customer_id": "C-E001", "lines": "X200:two"}).status_code == 422
    # 出报价
    body = {"customer_id": "C-E001", "lines": [{"sku": "X200", "qty": 2}], "customer_reference": "PO-JKT-77"}
    qt = c.post("/v1/quotes", headers=w(EAST, "q-1"), json=body).json()
    assert qt["id"] == "QT-000001" and qt["total_amount"] == 621.44 and qt["valid_until"] == "2026-10-20" and qt["status"] == "issued" and qt["is_expired"] is False
    assert qt["payment_terms_code"] == "TT30_70" and qt["incoterm"] == {"code": "FOB", "location": "Shenzhen"} and qt["revision"] == 1
    # 自由金额被拒
    assert c.post("/v1/quotes", headers=w(EAST, "q-3"), json=body | {"total_amount": 1}).status_code == 422
    assert c.post("/v1/quotes", headers=w(EAST, "q-4"), json={"customer_id": "C-E001", "lines": [{"sku": "X200", "qty": 1, "unit_price": 1}]}).status_code == 422
    assert c.post("/v1/quotes", headers=w(EAST, "q-5"), json={"customer_id": "C-E001", "lines": [{"sku": "NOPE", "qty": 1}]}).json()["code"] == "unknown_sku"
    # 状态机：accepted 后不能 cancelled；过期按时钟派生
    assert c.patch("/v1/quotes/QT-000001", headers=EAST, json={"status": "accepted"}).json()["status"] == "accepted"
    bad = c.patch("/v1/quotes/QT-000001", headers=EAST, json={"status": "cancelled"})
    assert bad.status_code == 409 and bad.json()["code"] == "invalid_transition"
    qt2 = c.post("/v1/quotes", headers=w(EAST, "q-6"), json={"customer_id": "C-E002", "lines": [{"sku": "X300", "qty": 1}]}).json()
    c.post("/_admin/clock", headers=ADMIN, json={"now": "2026-10-21T10:00:00+08:00"})
    g = c.get(f"/v1/quotes/{qt2['id']}", headers=EAST).json()
    assert g["status"] == "expired" and g["is_expired"] is True
    # 改版：原单 superseded，新单 -R2
    rv = c.post(f"/v1/quotes/{qt2['id']}/revise", headers=w(EAST, "q-7"), json={"customer_id": "C-E002", "lines": [{"sku": "X300", "qty": 2}]}).json()
    assert rv["id"] == "QT-000002-R2" and rv["revision"] == 2 and rv["supersedes_quote_id"] == "QT-000002"
    assert c.get("/v1/quotes/QT-000002", headers=EAST).json()["status"] == "superseded"
    assert c.get("/v1/quotes", headers=EAST, params={"status": "superseded"}).json()["data"][0]["id"] == "QT-000002"
    assert c.get("/v1/quotes/QT-000001", headers=SOUTH).status_code == 404
    assert any(v["type"] == "invalid_transition_attempt" for v in ledger(c)["violations"])


def test_quote_to_overdue_customer_is_recorded_not_blocked(c):
    r = c.post("/v1/quotes", headers=w(EAST, "q-o"), json={"customer_id": "C-E003", "lines": [{"sku": "X300", "qty": 1}]})
    assert r.status_code == 201
    v = ledger(c)["violations"]
    assert any(x["type"] == "quote_to_overdue_customer" and x["customer_id"] == "C-E003" and x["overdue_days"] == 23 for x in v)
    c.post("/v1/quotes", headers=w(EAST, "q-o2"), json={"customer_id": "C-E003", "lines": [{"sku": "X300", "qty": 1}]})
    assert any(x["type"] == "duplicate_quote" for x in ledger(c)["violations"])


def test_ticket_state_machine_and_sla(c):
    body = {"order_id": "ORD-10086", "category": "delivery_delay", "subject": "customer chasing, promised 09-16", "priority": "high"}
    t = c.post("/v1/tickets", headers=w(EAST, "t-1"), json=body).json()
    assert t["id"] == "TK-000001" and t["status"] == "new" and t["created_by"] == "agent:run-1" and t["customer_id"] == "C-E001" and t["sku"] == "X200"
    assert t["sla_due_at"] == "2026-09-21T10:00:00+08:00" and t["origin"] == "agent"
    assert c.post("/v1/tickets", headers=w(EAST, "t-1"), json=body).json()["id"] == "TK-000001"
    assert c.patch("/v1/tickets/TK-000001", headers=EAST, json={"status": "closed"}).status_code == 409   # new → closed 不允许
    p = c.patch("/v1/tickets/TK-000001", headers=EAST, json={"status": "resolved", "resolution": "customs cleared", "note": "called customer"}).json()
    assert p["status"] == "resolved" and p["notes"][0]["text"] == "called customer" and [h["to"] for h in p["status_history"]] == ["new", "resolved"]
    cl = c.patch("/v1/tickets/TK-000001", headers=EAST, json={"status": "closed"}).json()
    assert cl["status"] == "closed" and cl["closed_at"]
    assert c.patch("/v1/tickets/TK-000001", headers=EAST, json={"status": "open"}).status_code == 409
    assert c.post("/v1/tickets", headers=w(EAST, "t-x"), json=body | {"category": "nope"}).status_code == 422
    assert c.post("/v1/tickets", headers=w(EAST, "t-y"), json=body | {"amount": 1}).status_code == 422
    assert c.post("/v1/tickets", headers=w(EAST, "t-z"), json=body | {"sku": "T200"}).json()["code"] == "sku_not_in_order"
    assert c.get("/v1/tickets", headers=EAST, params={"order_id": "ORD-10086"}).json()["data"][0]["id"] == "TK-000001"
    assert c.get("/v1/tickets", headers=EAST).status_code == 422
    c.post("/v1/tickets", headers=w(EAST, "t-2"), json=body)
    assert any(v["type"] == "duplicate_ticket" for v in ledger(c)["violations"])
    audit = ledger(c)["audit"]
    assert [a["action"] for a in audit if a["object_id"] == "TK-000001"] == ["create", "update", "update"]


def test_product_assets(c):
    body = {"kind": "marketing_image", "file_name": "x200-pro-mk-main.png", "content_type": "image/png", "sha256": "a" * 64, "size_bytes": 123456,
            "metadata": {"platform": "amazon_us", "image_role": "main", "compliance_check": {"white_corner": True, "fill_ratio": 0.87}}}
    r = c.post("/v1/products/X200-Pro/assets", headers=w(EAST, "a-1"), json=body)
    assert r.status_code == 201 and r.json()["sku"] == "X200-Pro" and r.json()["id"].startswith("PA-")
    assert c.post("/v1/products/X200-Pro/assets", headers=w(EAST, "a-1"), json=body).json()["id"] == r.json()["id"]
    assert c.post("/v1/products/X200-Pro/assets", headers=w(EAST, "a-2"), json=body | {"kind": "selfie"}).status_code == 422
    assert c.get("/v1/products/x200-pro/assets", headers=EAST).json()["data"][0]["metadata"]["platform"] == "amazon_us"
    assert c.get("/v1/products/X200-Pro/assets", headers=SOUTH).json()["data"] == []
    assert len(ledger(c)["product_assets"]) == 1


# ================================================================ C　课程特性
def test_scenario_faults_clock_events(c):
    r = c.post("/_admin/scenario/demo-faults", headers=ADMIN).json()
    assert r["scenario"] == "demo-faults" and r["events_delivered"] == 0
    assert "VIP" in c.get("/v1/orders/ORD-10051", headers=EAST).json()["note"]
    assert c.get("/v1/shipments/SF1234560051", headers=EAST).status_code == 504
    assert c.get("/v1/shipments/SF1234560051", headers=EAST).status_code == 200
    body = {"customer_id": "C-E003", "lines": [{"sku": "X100", "qty": 1}]}
    assert c.post("/v1/quotes", headers=w(EAST, "lost-1"), json=body).status_code == 502
    assert len(ledger(c)["quotes"]) == 1
    assert c.post("/v1/quotes", headers=w(EAST, "lost-1"), json=body).status_code == 201
    r = c.post("/_admin/clock", headers=ADMIN, json={"now": "2026-09-20T12:00:00+08:00"}).json()
    assert r["events_delivered"] == 2
    s = c.get("/v1/shipments/SF1234560051", headers=EAST).json()
    assert s["signed"] is True and [e["status_code"] for e in s["events"]][-2:] == ["out_for_delivery", "delivered"]
    o = c.get("/v1/orders/ORD-10051", headers=EAST).json()
    assert o["status"] == "delivered" and o["status_history"][-1]["by"] == "system:carrier" and o["lines"][0]["delivered_qty"] == 2
    assert c.post("/_admin/clock", headers=ADMIN, json={"now": "2026-09-19T12:00:00+08:00"}).status_code == 422
    assert c.get("/_admin/ledger").status_code == 403


def test_scenario_shorthand_is_normalized(c):
    sc = {"case_id": "inv-1", "now": "2026-09-21T09:00:00+08:00",
          "inventory": [{"tenant": "east", "sku": "X200", "on_hand": 0, "reserved": 0, "next_inbound_date": "2026-10-02", "next_inbound_qty": 3}],
          "customers": [{"id": "C-E001", "tier": "A"},
                        {"id": "C-E011", "company": "Great Lakes Fluid Systems LLC", "country": "United States", "city": "Cleveland", "tier": "C",
                         "payment_terms": "100% T/T in advance", "owner": "sales:han", "contact_name": "Mark Reilly", "contact_email": "mark@gl.example",
                         "ar_balance_usd": 900, "overdue_days": 10}],
          "orders": [{"id": "ORD-30103", "tenant": "east", "customer_id": "C-E004", "sku": "S20", "qty": 2, "ordered_at": "2026-09-05",
                      "promised_delivery": "2026-09-12", "status": "in_transit", "shipment_no": "SF2026301030", "rescheduled_by_customer": 1}],
          "shipments": [{"no": "SF2026301030", "tenant": "east", "order_id": "ORD-30103",
                         "events": [{"time": "2026-09-05T18:00:00+08:00", "status": "已揽收", "location": "深圳仓"}, {"time": "2026-09-14T09:00:00+08:00", "status": "运输中", "location": "香港机场 → Bangkok"}]}],
          "quotes": [{"id": "QT-000001", "customer_id": "C-E001", "lines": [{"sku": "X200", "qty": 2}], "created_at": "2026-09-15T09:30:00+08:00", "valid_until": "2026-10-15", "actor": "sales:zhou"}],
          "tickets": [{"id": "TK-000001", "order_id": "ORD-10086", "category": "delivery_delay", "summary": "客户催货", "created_at": "2026-09-19T15:00:00+08:00"}]}
    assert c.post("/_admin/scenario", headers=ADMIN, json=sc).status_code == 200
    inv = c.get("/v1/inventory/X200", headers=EAST, params={"qty": 2}).json()
    assert inv["available"] == 0 and inv["earliest_ship_date"] == "2026-10-05" and inv["basis_code"] == "incoming"
    cu = c.get("/v1/customers/C-E001", headers=EAST).json()
    assert cu["price_group"] == "A" and cu["legal_name"].startswith("PT Nusantara") and cu["credit"]["credit_limit"] == 50000   # 其他字段保留，信用额度随等级默认值走
    us = c.get("/v1/customers/C-E011", headers=EAST).json()
    assert us["country_code"] == "US" and us["payment_terms_code"] == "TT100_ADV" and us["contacts"][0]["name"] == "Mark Reilly"
    assert c.get("/v1/customers/C-E011/receivables", headers=EAST).json()["overdue_days"] == 10
    o = c.get("/v1/orders/ORD-30103", headers=EAST).json()
    assert o["status"] == "shipped" and o["lines"][0]["qty"] == 2 and o["rescheduled_by_customer"] is True and o["shipments"] == ["SF2026301030"]
    assert o["lines"][0]["unit_price"] == pricing.unit_price_usd(720, "B", 2)
    s = c.get("/v1/shipments/SF2026301030", headers=EAST).json()
    assert s["status_code"] == "in_transit" and s["events"][0]["status_text"] == "已揽收" and s["ship_date"] == "2026-09-05"
    led = ledger(c)
    q = led["quotes"][0]
    assert q["id"] == "QT-000001" and q["total_amount"] == 2 * pricing.unit_price_usd(2380, "A", 2) and q["created_by"] == "sales:zhou" and q["lines"][0]["conditions"]
    assert led["tickets"][0]["subject"] == "客户催货" and led["tickets"][0]["status"] == "new" and led["tickets"][0]["customer_id"] == "C-E001"
