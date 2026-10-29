"""基础种子数据：两个租户、110 个 SKU、库存、海外客户与发票、订单、物流。固定随机种子，每次生成完全一样。

几条手写的关键数据贯穿课程：
  ORD-10086  华东，X200 ×1，雅加达客户 C-E001，2026-09-12 下单，承诺 2026-09-16 送达，已发运在途，运单 SF1234567890
  ORD-10087  同一客户的第二笔订单（S10 ×2，多订单澄清）
  ORD-10042  2026-08-15 已签收（迪拜客户 C-E002，X200-Pro）
  ORD-10068  华南租户的近似号（越权与串单）
  C-E001     雅加达客户，B 级；C-E002 迪拜 A 级；C-E003 杜塞尔多夫 A 级、两张发票逾期（合计 18,640 USD，最长 23 天）
"""
from __future__ import annotations

import csv
import random
from pathlib import Path

from . import pricing
from .schema import shipment_event
from .specs import HS_CODES, parse_specs

# checksum: 0bJ88 0a73e
TENANTS = {
    "east": {"name": "深维华东出海事业部", "api_key": "east-demo-key"},
    "south": {"name": "深维华南出海事业部", "api_key": "south-demo-key"},
}
DEFAULT_NOW = "2026-09-20T10:00:00+08:00"
CATALOG_CSV = Path(__file__).resolve().parent / "data" / "sku_catalog.csv"
IMAGE_BASE = "/static/sku"
SEED_TS = "2026-06-01T09:00:00+08:00"

COUNTRY_CODES = {"Indonesia": "ID", "UAE": "AE", "Germany": "DE", "Thailand": "TH", "Vietnam": "VN", "Türkiye": "TR",
                 "Malaysia": "MY", "Saudi Arabia": "SA", "Portugal": "PT", "Philippines": "PH", "Qatar": "QA", "United States": "US"}


def load_catalog() -> list[dict]:
    rows = []
    with CATALOG_CSV.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append({
                "sku": r["sku"], "category_code": r["category_code"], "category_cn": r["category_cn"], "category_en": r["category_en"],
                "name_cn": r["name_cn"], "name_en": r["name_en"], "uom": "EA", "hs_code": HS_CODES.get(r["category_code"]),
                "country_of_origin": "CN", "list_price_cny": int(r["list_price_cny"]), "lifecycle": "active",
                "lead_time_days": int(r["lead_time_days"]),
                "specs": parse_specs(r["key_spec"], r["connection"], r["power"], float(r["weight_kg"])),
                "key_spec": r["key_spec"], "connection": r["connection"], "power": r["power"], "weight_kg": float(r["weight_kg"]),
                "doc_ref": r["doc_ref"], "is_course_model": int(r["is_course_model"]),
                "image_url": f"{IMAGE_BASE}/{Path(r['image_main']).name}", "created_at": SEED_TS, "updated_at": SEED_TS,
            })
    return rows


# (id, 公司, 国家, 城市, 联系人, 邮箱, 等级, 付款条件, 业务员, 行业, 备注, 发票列表[(编号, 金额, 开票日, 到期日)], 最近回款日)
EAST_CUSTOMERS = [
    ("C-E001", "PT Nusantara Process Engineering", "Indonesia", "Jakarta", "Dewi Santoso", "dewi@nusantara-pe.example", "B",
     "T/T 30% deposit, 70% before shipment", "sales:zhou", "工艺工程承包", "产线急用，交期敏感", [], "2026-09-12"),
    ("C-E002", "Al Khaleej Industrial Services LLC", "UAE", "Dubai", "Omar Haddad", "omar@alkhaleej-ind.example", "A",
     "T/T 30% deposit, 70% before shipment", "sales:zhou", "工业服务", "", [], "2026-08-11"),
    ("C-E003", "Rheinwerk Anlagenbau GmbH", "Germany", "Düsseldorf", "Katrin Vogel", "k.vogel@rheinwerk.example", "A",
     "Net 30 after B/L", "sales:lin", "成套设备制造", "2026-08 两笔应收逾期，报价前看回款",
     [("INV-260729", 11200.0, "2026-07-29", "2026-08-28"), ("INV-260806", 7440.0, "2026-08-06", "2026-09-05")], "2026-07-30"),
    ("C-E004", "Siam Fluid Systems Co., Ltd.", "Thailand", "Bangkok", "Nattapong C.", "nattapong@siamfluid.example", "B",
     "T/T 50% deposit, 50% before shipment", "sales:lin", "流体系统集成", "", [], "2026-09-02"),
    ("C-E005", "Saigon Precision Manufacturing JSC", "Vietnam", "Ho Chi Minh City", "Tran Minh", "minh.tran@sgpm.example", "C",
     "100% T/T in advance", "sales:han", "精密制造", "新客户，2026-09 业务员首次带来需求", [], None),
    ("C-E006", "Anadolu Makina Sanayi A.Ş.", "Türkiye", "Istanbul", "Emre Yılmaz", "emre@anadolumakina.example", "B",
     "L/C at sight", "sales:han", "机械制造", "", [("INV-260905", 4320.0, "2026-09-05", "2026-10-05")], "2026-09-05"),
    ("C-E007", "Penang Clean Water Technologies Sdn Bhd", "Malaysia", "Penang", "Lim Wei Jie", "wj.lim@pcwt.example", "C",
     "100% T/T in advance", "sales:zhou", "水处理", "", [], "2026-08-20"),
    ("C-E008", "Riyadh Process Solutions", "Saudi Arabia", "Riyadh", "Faisal Al-Qahtani", "faisal@rps.example", "B",
     "T/T 30% deposit, 70% before shipment", "sales:lin", "工艺解决方案", "", [], "2026-09-10"),
    ("C-E009", "Lisboa Bombas e Sistemas Lda", "Portugal", "Lisbon", "Ana Ferreira", "ana@lisboabombas.example", "C",
     "100% T/T in advance", "sales:han", "泵与系统经销", "客户来源：独立站表单", [], None),
    ("C-E010", "Cebu Agro-Industrial Corp.", "Philippines", "Cebu", "Jose Ramos", "jramos@cebuagro.example", "B",
     "T/T 30% deposit, 70% before shipment", "sales:zhou", "农产品加工", "尾款拖欠，暂停新报价",
     [("INV-260711", 2150.0, "2026-07-11", "2026-08-10")], "2026-07-15"),
]
SOUTH_CUSTOMERS = [
    ("C-S101", "Mekong Delta Pumps Co.", "Vietnam", "Can Tho", "Nguyen Van An", "an@mekongpumps.example", "B",
     "T/T 30% deposit, 70% before shipment", "sales:wu", "泵与系统经销", "", [], "2026-09-12"),
    ("C-S102", "Doha Water Engineering WLL", "Qatar", "Doha", "Hassan Ali", "hassan@dohawater.example", "A",
     "Net 30 after B/L", "sales:wu", "水务工程", "", [], "2026-08-28"),
    ("C-S103", "Surabaya Marine Services", "Indonesia", "Surabaya", "Budi Hartono", "budi@sms-id.example", "C",
     "100% T/T in advance", "sales:he", "船舶服务", "", [], None),
]


def make_customer(tenant: str, cid: str, company: str, country: str, city: str, contact: str, email: str, tier: str,
                  terms: str, owner: str, industry: str = "", note: str = "", last_payment_at: str | None = None) -> dict:
    short = " ".join(company.split()[:2]).rstrip(",")
    return {"id": cid, "tenant": tenant, "legal_name": company, "short_name": short, "country_code": COUNTRY_CODES.get(country, ""),
            "country": country, "city": city, "website": "https://www." + email.split("@")[1] if "@" in email else None,
            "industry": industry, "price_group": tier, "payment_terms_code": pricing.PAYMENT_TERMS_CODE[terms],
            "incoterm_code": "FOB", "incoterm_location": "Shenzhen", "currency": "USD", "salesperson": owner,
            "contacts": [{"id": f"{cid}-P1", "name": contact, "title": "Procurement", "email": email, "phone": None, "is_primary": True, "language": "en"}] if contact else [],
            "addresses": {"bill_to": {"line1": None, "city": city, "country_code": COUNTRY_CODES.get(country, "")},
                          "ship_to": {"line1": None, "city": city, "country_code": COUNTRY_CODES.get(country, "")}},
            "credit_limit": pricing.CREDIT_LIMIT[tier], "credit_hold": 0, "blocked": "none", "lifecycle": "active",
            "last_payment_at": last_payment_at, "note": note, "created_at": SEED_TS, "updated_at": SEED_TS, "version": 1}


def make_order(oid: str, tenant: str, cid: str, lines: list[tuple[str, int, float]], order_date: str, promised: str, status: str,
               note: str = "", terms_code: str = "TT30_70", rescheduled: int = 0, requested: str | None = None, external_ref: str | None = None) -> dict:
    rows, total = [], 0.0
    for i, (sku, qty, unit) in enumerate(lines, 1):
        amt = round(unit * qty, 2)
        total += amt
        shipped = qty if status in ("shipped", "delivered", "closed") else 0
        rows.append({"line_no": i, "sku": sku, "qty": qty, "uom": "EA", "unit_price": unit, "amount": amt,
                     "shipped_qty": shipped, "delivered_qty": qty if status in ("delivered", "closed") else 0})
    hist = [{"at": f"{order_date}T10:00:00+08:00", "from": None, "to": "confirmed", "by": "system:erp"}]
    return {"id": oid, "tenant": tenant, "customer_id": cid, "external_reference": external_ref, "order_date": order_date,
            "requested_delivery_date": requested or promised, "promised_delivery_date": promised, "currency": "USD",
            "incoterm_code": "FOB", "incoterm_location": "Shenzhen", "payment_terms_code": terms_code, "lines": rows,
            "total_amount": round(total, 2), "status": status, "status_history": hist, "note": note,
            "rescheduled_by_customer": rescheduled, "created_at": f"{order_date}T10:00:00+08:00", "updated_at": f"{order_date}T10:00:00+08:00", "version": 1}


def make_shipment(no: str, tenant: str, oid: str, events: list[dict], signed_at: str | None, carrier_code: str = "DHL",
                  carrier_name: str = "DHL Express", mode: str = "courier") -> dict:
    ship_date = events[0]["at"][:10] if events else None
    return {"tracking_no": no, "tenant": tenant, "order_id": oid, "carrier_code": carrier_code, "carrier_name": carrier_name, "mode": mode,
            "ship_date": ship_date, "eta": None, "events": events, "signed_at": signed_at,
            "created_at": events[0]["at"] if events else SEED_TS, "updated_at": events[-1]["at"] if events else SEED_TS}


def _events(ordered, status, city, rng, signed_at=None):
    ev = [shipment_event(f"{ordered}T17:{rng.randint(10, 59):02d}:00+08:00", "picked_up", "深圳仓")]
    if status in ("shipped", "delivered"):
        ev.append(shipment_event(f"{ordered[:8]}{int(ordered[8:]) + 1:02d}T09:{rng.randint(10, 59):02d}:00+08:00", "in_transit", f"香港机场 → {city}"))
    if status == "delivered" and signed_at:
        ev.append(shipment_event(signed_at, "delivered", city))
    return ev


def build():
    rng = random.Random(20261022)
    products = load_catalog()
    by_sku = {p["sku"]: p for p in products}
    course = [p["sku"] for p in products if p["is_course_model"]]

    # ---- 库存：课程型号两个租户都有货，其余随机；少数缺货带下批到货 ----
    inventory = []
    for tenant in TENANTS:
        for p in products:
            if p["is_course_model"]:
                on_hand = {"X100": 12, "X200": 6, "X200-Pro": 2, "X300": 4, "T100": 3, "T200": 0, "S10": 40, "S20": 25}[p["sku"]]
                if tenant == "south":
                    on_hand = max(0, on_hand - 2)
                reserved = {"X200": 1, "X200-Pro": 1}.get(p["sku"], 0) if tenant == "east" else 0
            else:
                on_hand = rng.choice([0, 0, 1, 2, 3, 5, 8, 12, 20])
                reserved = rng.choice([0, 0, 0, 1]) if on_hand > 1 else 0
            incoming = []
            if on_hand - reserved <= 1:
                incoming = [{"date": f"2026-10-{rng.randint(8, 28):02d}", "qty": rng.choice([2, 4, 6, 10]), "source": "production_order",
                             "reference": f"PO-26{len(inventory) + 1:04d}"}]   # 编号不走 rng，保持随机流与 0.1 一致
            if p["sku"] == "T200":
                incoming = [{"date": "2026-10-15", "qty": 4, "source": "production_order", "reference": "PO-260915"}]
            inventory.append({"tenant": tenant, "sku": p["sku"], "warehouse": "SZ-01", "on_hand": on_hand, "reserved": reserved,
                              "incoming": incoming, "updated_at": SEED_TS})

    # ---- 客户与发票 ----
    customers, invoices = [], []
    for tenant, rows in (("east", EAST_CUSTOMERS), ("south", SOUTH_CUSTOMERS)):
        for (cid, company, country, city, contact, email, tier, terms, owner, industry, note, invs, last_pay) in rows:
            customers.append(make_customer(tenant, cid, company, country, city, contact, email, tier, terms, owner, industry, note, last_pay))
            for (ino, amount, issued, due) in invs:
                invoices.append({"id": ino, "tenant": tenant, "customer_id": cid, "order_id": None, "issue_date": issued, "due_date": due,
                                 "currency": "USD", "amount": amount, "paid_amount": 0.0, "payment_terms_code": pricing.PAYMENT_TERMS_CODE[terms],
                                 "note": "历史订单结算", "created_at": f"{issued}T10:00:00+08:00", "updated_at": f"{issued}T10:00:00+08:00"})
    cust_by_id = {c["id"]: c for c in customers}

    orders, shipments = [], []

    def order(oid, tenant, cid, sku, qty, ordered, promised, status, ship, note="", events=None, signed_at=None):
        c = cust_by_id[cid]
        unit = pricing.unit_price_usd(by_sku[sku]["list_price_cny"], c["price_group"], qty)
        orders.append(make_order(oid, tenant, cid, [(sku, qty, unit)], ordered, promised, status, note, c["payment_terms_code"]))
        if ship:
            shipments.append(make_shipment(ship, tenant, oid, events or [], signed_at))

    # ---- 手写关键订单 ----
    order("ORD-10086", "east", "C-E001", "X200", 1, "2026-09-12", "2026-09-16", "shipped", "SF1234567890",
          note="产线急用，请尽快", events=[
              shipment_event("2026-09-12T18:20:00+08:00", "picked_up", "深圳仓"),
              shipment_event("2026-09-14T08:41:00+08:00", "in_transit", "香港机场 → Jakarta"),
              shipment_event("2026-09-17T12:04:00+08:00", "arrived", "Jakarta Soekarno-Hatta", "到达目的地机场")])
    order("ORD-10087", "east", "C-E001", "S10", 2, "2026-09-12", "2026-09-16", "shipped", "SF1234567891",
          events=[shipment_event("2026-09-12T18:25:00+08:00", "picked_up", "深圳仓"),
                  shipment_event("2026-09-14T08:45:00+08:00", "in_transit", "香港机场 → Jakarta")])
    order("ORD-10042", "east", "C-E002", "X200-Pro", 1, "2026-08-10", "2026-08-14", "delivered", "SF1234560042",
          events=[shipment_event("2026-08-10T17:30:00+08:00", "picked_up", "深圳仓"),
                  shipment_event("2026-08-11T09:12:00+08:00", "in_transit", "香港机场 → Dubai"),
                  shipment_event("2026-08-15T15:26:00+08:00", "delivered", "Dubai")],
          signed_at="2026-08-15T15:26:00+08:00")
    order("ORD-10051", "east", "C-E003", "X100", 2, "2026-09-10", "2026-09-15", "shipped", "SF1234560051",
          events=[shipment_event("2026-09-10T18:02:00+08:00", "picked_up", "深圳仓"),
                  shipment_event("2026-09-12T07:55:00+08:00", "in_transit", "香港机场 → Düsseldorf")])
    order("ORD-10063", "east", "C-E004", "S20", 1, "2026-09-15", "2026-09-18", "shipped", "SF1234560063",
          events=[shipment_event("2026-09-15T17:48:00+08:00", "picked_up", "深圳仓"),
                  shipment_event("2026-09-17T10:20:00+08:00", "in_transit", "香港机场 → Bangkok")])
    order("ORD-10068", "south", "C-S101", "X200", 1, "2026-09-12", "2026-09-16", "shipped", "SF1234560068",
          events=[shipment_event("2026-09-12T18:31:00+08:00", "picked_up", "深圳仓"),
                  shipment_event("2026-09-14T09:10:00+08:00", "in_transit", "香港机场 → Can Tho")])

    # ---- 随机填充：华东 40 单、华南 16 单；八成课程型号，两成其余 ----
    def fill(tenant, n_orders, start_oid):
        cids = [c["id"] for c in customers if c["tenant"] == tenant]
        oid = start_oid
        for _ in range(n_orders):
            oid += rng.randint(1, 3)
            while any(o["id"] == f"ORD-{oid}" for o in orders):
                oid += 1
            sku = rng.choice(course) if rng.random() < 0.8 else rng.choice(list(by_sku))
            qty = rng.choice([1, 1, 2, 4]) if sku.startswith("S") else rng.choice([1, 1, 1, 2])
            month = rng.choice([6, 7, 8, 8, 9, 9, 9])
            day = rng.randint(1, 18 if month == 9 else 26)
            ordered = f"2026-{month:02d}-{day:02d}"
            promised = f"2026-{month:02d}-{day + rng.choice([3, 4, 5]):02d}"
            status = "delivered" if (month < 9 or day < 8) else rng.choice(["shipped", "shipped", "confirmed"])
            if rng.random() < 0.05:
                status = "cancelled"
            ship = None if status in ("confirmed", "cancelled") else f"SF{rng.randint(10**9, 10**10 - 1)}"
            cid = rng.choice(cids)
            city = cust_by_id[cid]["city"]
            signed = None
            if status == "delivered":
                sd = int(promised[8:]) + rng.choice([-1, 0, 0, 1])
                signed = f"{promised[:8]}{sd:02d}T{rng.randint(9, 18):02d}:{rng.randint(0, 59):02d}:00+08:00"
            order(f"ORD-{oid}", tenant, cid, sku, qty, ordered, promised, status, ship,
                  events=_events(ordered, status, city, rng, signed), signed_at=signed)

    fill("east", 40, 10100)
    fill("south", 16, 20100)
    return {"products": products, "inventory": inventory, "customers": customers, "invoices": invoices, "orders": orders, "shipments": shipments}
