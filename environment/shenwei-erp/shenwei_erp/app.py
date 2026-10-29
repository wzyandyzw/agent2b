"""shenwei-erp 0.2：深维设备华东 / 华南出海事业部用的模拟 ERP。

管"货和钱"：商品与规格、库存交期、客户与信用、发票与账龄、订单物流、报价台账、售后工单、产品资料归档。
学员的系统只调用它、不修改它。三个设计目标不变：
  可复现 —— 虚拟时钟 + 场景加载，每条案例的"现在"和数据都固定；
  会出错 —— 按场景注入超时、慢响应、500、429、结果未知（response_lost）、坏 JSON、重复与乱序事件；
  记真账 —— 所有写动作进账本与审计，评估只信账本，不信调用方自己怎么说。

接口形状按成熟 ERP（SAP / Business Central / Odoo）与通用规范（Stripe 幂等、RFC 9457 错误、游标分页、签名 webhook）做，
见 环境/接口通用规范.md 与 环境/ERP接口说明.md。它刻意**不替调用方拦截业务违规**（给逾期客户照样出报价、同一订单可以建两张工单），
违规原样记进账本，这样学员才看得到自己系统的错。价格是例外：价格只由 ERP 按报价规程算，请求里多传金额直接 422。
"""
from __future__ import annotations

import hashlib
import json
import os
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

from fastapi import BackgroundTasks, Depends, FastAPI, Header, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from shenwei_mockkit import (Events, Identity, Idempotency, Problem, Store, check_if_match, etag_of, install_error_handlers,
                             install_middleware, iso, note, paginate, parse)
from shenwei_mockkit.middleware import load_faults

from . import pricing, specs as specmod
from . import seed as seedmod
from .schema import (ASSET_KINDS, BLOCKED, BUSINESS_TABLES, LEGACY_ORDER_STATUS, ORDER_STATUSES, QUOTE_TRANSITIONS, SCHEMA,
                     TICKET_CATEGORIES, TICKET_ORIGINS, TICKET_PRIORITIES, TICKET_SLA_HOURS, TICKET_STATUSES, TICKET_TRANSITIONS,
                     shipment_event)

VERSION = "0.2.0"
API = "/v1"
SHIP_PREP_DAYS = 3
ADMIN_TOKEN = os.environ.get("ERP_ADMIN_TOKEN", "local-admin")
SCENARIO_DIR = Path(os.environ.get("ERP_SCENARIOS", Path(__file__).resolve().parents[1] / "scenarios"))
OPENAPI_OUT = os.environ.get("ERP_OPENAPI_OUT", str(Path(__file__).resolve().parents[2] / "openapi" / "erp-v1.json"))
KEY_TO_TENANT = {v["api_key"]: k for k, v in seedmod.TENANTS.items()}

store = Store(os.environ.get("ERP_DB", "erp.db"), SCHEMA, BUSINESS_TABLES, seedmod.DEFAULT_NOW)
ident = Identity(KEY_TO_TENANT, ADMIN_TOKEN)
idem = Idempotency(store)
events = Events(store)


@asynccontextmanager
async def lifespan(app_):
    if store.get("scenario") is None:
        load_base()
    try:
        Path(OPENAPI_OUT).parent.mkdir(parents=True, exist_ok=True)
        Path(OPENAPI_OUT).write_text(json.dumps(app_.openapi(), ensure_ascii=False, indent=1), "utf-8")
    except OSError:
        pass
    yield


TAGS = [
    {"name": "products", "description": "商品主数据（不分租户）：规格、HS 编码、挂牌价、按工况筛型号、产品资料归档"},
    {"name": "inventory", "description": "库存与交期（分租户）：可用量、在途、确认计划行"},
    {"name": "customers", "description": "客户主数据与信用、发票与账龄"},
    {"name": "orders", "description": "销售订单与运单"},
    {"name": "quotes", "description": "报价：只算不记 / 记台账 / 状态机"},
    {"name": "tickets", "description": "售后工单"},
    {"name": "events", "description": "事件回拉（与 webhook 同一信封）"},
    {"name": "admin", "description": "评估运行器与教师用：重置、场景、时钟、webhook、账本"},
]
app = FastAPI(title="shenwei-erp", version=VERSION, lifespan=lifespan, openapi_tags=TAGS,
              description="深维设备模拟 ERP（商品 / 库存 / 客户与信用 / 发票 / 订单物流 / 报价台账 / 工单 / 产品资料）。教学虚构数据。"
                          "所有错误为 application/problem+json；写操作需 X-Actor 与 Idempotency-Key；列表为游标分页。")
install_error_handlers(app)
install_middleware(app, store, KEY_TO_TENANT)
caller, writer, admin = ident.caller, ident.writer, ident.admin


# ---------------------------------------------------------------- 通用
def J(s):
    return json.loads(s) if isinstance(s, str) else (s if s is not None else [])


def next_id(prefix: str, table: str) -> str:
    n = store.one(f"SELECT COUNT(*) AS n FROM {table}")["n"] + 1
    while store.one(f"SELECT 1 AS x FROM {table} WHERE id=?", f"{prefix}-{n:06d}"):
        n += 1
    return f"{prefix}-{n:06d}"


def insert_row(db, table: str, row: dict):
    cols = store.cols(table)
    vals = [json.dumps(row.get(k), ensure_ascii=False) if isinstance(row.get(k), (list, dict)) else row.get(k) for k in cols]
    db.execute(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", vals)


def tenant_row(request: Request, c, table: str, key: str, value: str, code: str, label: str) -> dict:
    row = store.one(f"SELECT * FROM {table} WHERE {key}=?", value)
    if not row or row["tenant"] != c.tenant:
        if row:
            note(request, f"cross_tenant:{value}")
        raise Problem(404, code, f"{label} {value} 不存在")
    return row


def with_etag(response: Response, row: dict):
    response.headers["ETag"] = etag_of(row.get("version"))


def bump(db, table, key, value, extra_sql="", extra_args=()):
    db.execute(f"UPDATE {table} SET version=version+1, updated_at=? {extra_sql} WHERE {key}=?", (store.now_iso(), *extra_args, value))


def days_between(later: str, earlier: str) -> int:
    return (date.fromisoformat(later[:10]) - date.fromisoformat(earlier[:10])).days


# ---------------------------------------------------------------- 商品
def product_view(p: dict, brief: bool = False) -> dict:
    v = {"sku": p["sku"], "name_cn": p["name_cn"], "name_en": p["name_en"],
         "category": {"code": p["category_code"], "name_cn": p["category_cn"], "name_en": p["category_en"]},
         "uom": p["uom"], "list_price": {"amount": p["list_price_cny"], "currency": "CNY"}, "lifecycle": p["lifecycle"],
         "lead_time_days": p["lead_time_days"], "doc_ref": p["doc_ref"]}
    if not brief:
        v |= {"hs_code": p["hs_code"], "country_of_origin": p["country_of_origin"], "specs": J(p["specs"]) or {},
              "key_spec": p["key_spec"], "image_url": p["image_url"],
              "spec_source": "ERP 商品主数据；详细参数与运行边界以产品手册为准（doc_ref）",
              "created_at": p["created_at"], "updated_at": p["updated_at"]}
    return v


def _products():
    rows = store.q("SELECT * FROM products ORDER BY category_code, sku")
    for r in rows:
        r["specs"] = J(r["specs"]) or {}
    return rows


@app.get("/health", tags=["admin"])
def health():
    return {"status": "ok", "service": "shenwei-erp", "version": VERSION, "api_version": "v1", "now": store.now_iso(), "scenario": store.get("scenario")}


@app.get(f"{API}/products", tags=["products"], summary="商品目录（游标分页）")
def list_products(c=Depends(caller), category: str | None = None, q: str | None = None, lifecycle: str | None = None,
                  updated_since: str | None = None, limit: int | None = None, cursor: str | None = None):
    rows = _products()
    if category:
        rows = [p for p in rows if category.upper() == p["category_code"] or category in (p["category_cn"], p["category_en"])]
    if q:
        ql = q.lower()
        rows = [p for p in rows if ql in p["sku"].lower() or ql in p["name_cn"].lower() or ql in p["name_en"].lower() or ql in p["key_spec"].lower()]
    if lifecycle:
        rows = [p for p in rows if p["lifecycle"] == lifecycle]
    if updated_since:
        rows = [p for p in rows if parse(p["updated_at"]) >= parse(updated_since)]
    page = paginate([product_view(p, brief=True) for p in rows], limit, cursor)
    page["categories"] = sorted({(p["category_code"], p["category_cn"]) for p in rows}) if not cursor else None
    return page


@app.get(f"{API}/products/selection", tags=["products"], summary="按工况筛型号（只按主数据硬筛，运行边界以手册为准）")
def product_selection(c=Depends(caller), category: str | None = None, flow_lpm: float | None = None, pressure_bar: float | None = None,
                      head_m: float | None = None, cooling_w: float | None = None, setpoint_c: float | None = None,
                      measure_bar: float | None = None, measure_m: float | None = None, ambient_c: float | None = None):
    wants = {k: v for k, v in dict(flow_lpm=flow_lpm, pressure_bar=pressure_bar, head_m=head_m, cooling_w=cooling_w, setpoint_c=setpoint_c,
                                    measure_bar=measure_bar, measure_m=measure_m, ambient_c=ambient_c).items() if v is not None}
    if not wants:
        raise Problem(422, "no_criteria", "至少给一个工况参数：flow_lpm / pressure_bar / head_m / cooling_w / setpoint_c / measure_bar / measure_m / ambient_c")
    rows = [p for p in _products() if p["lifecycle"] == "active"]
    if category:
        rows = [p for p in rows if p["category_code"] == category.upper()]
    cands = specmod.select(rows, wants)
    return {"criteria": wants, "candidates": cands, "meets_all_count": sum(c["meets_all"] for c in cands),
            "note": "候选只按 ERP 主数据硬筛；连续运行边界、介质兼容、环境温度降额以产品手册与选型指南为准"}


@app.get(f"{API}/products/{{sku}}", tags=["products"], summary="型号主数据")
def get_product(sku: str, c=Depends(caller)):
    p = store.one("SELECT * FROM products WHERE sku=? COLLATE NOCASE", sku)
    if not p:
        raise Problem(404, "product_not_found", f"型号 {sku} 不存在")
    return product_view(p)


# ---- 产品资料归档 ----
class AssetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["marketing_image", "datasheet", "manual", "certificate", "drawing"]
    file_name: str = Field(min_length=1, max_length=200)
    content_type: str = Field(min_length=3, max_length=100)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=1)
    source_uri: str | None = None
    metadata: dict = {}


def asset_view(a: dict) -> dict:
    return {"id": a["id"], "sku": a["sku"], "kind": a["kind"], "file_name": a["file_name"], "content_type": a["content_type"],
            "sha256": a["sha256"], "size_bytes": a["size_bytes"], "source_uri": a["source_uri"], "metadata": J(a["metadata"]) or {},
            "created_by": a["created_by"], "created_at": a["created_at"]}


@app.post(f"{API}/products/{{sku}}/assets", tags=["products"], status_code=201, summary="归档产品资料（营销图 / 资料表 / 证书）")
def create_asset(sku: str, req: AssetIn, request: Request, c=Depends(writer), idempotency_key: str | None = Header(None)):
    p = store.one("SELECT * FROM products WHERE sku=? COLLATE NOCASE", sku)
    if not p:
        raise Problem(404, "product_not_found", f"型号 {sku} 不存在")
    data = req.model_dump() | {"sku": p["sku"]}
    scope = "POST products.assets"
    if replay := idem.begin(c.tenant, scope, idempotency_key, data, c.request_id):
        return replay
    try:
        aid = "PA-" + hashlib.sha256(f"{c.tenant}{p['sku']}{req.sha256}{idempotency_key}".encode()).hexdigest()[:10].upper()
        with store.tx() as db:
            insert_row(db, "product_assets", {"id": aid, "tenant": c.tenant, "sku": p["sku"], "kind": req.kind, "file_name": req.file_name,
                                              "content_type": req.content_type, "sha256": req.sha256, "size_bytes": req.size_bytes, "source_uri": req.source_uri,
                                              "metadata": req.metadata, "idem_key": idempotency_key, "created_by": c.actor, "created_at": store.now_iso()})
            resp = asset_view(store.one("SELECT * FROM product_assets WHERE id=?", aid))
            store.audit(db, c.tenant, c.actor, c.request_id, "create", "product_asset", aid, None, resp)
            idem.commit(db, c.tenant, scope, idempotency_key, 201, resp)
        return resp
    except Exception:
        idem.abort(c.tenant, scope, idempotency_key)
        raise


@app.get(f"{API}/products/{{sku}}/assets", tags=["products"], summary="该型号已归档的资料")
def list_assets(sku: str, c=Depends(caller), limit: int | None = None, cursor: str | None = None):
    rows = store.q("SELECT * FROM product_assets WHERE tenant=? AND sku=? COLLATE NOCASE ORDER BY created_at", c.tenant, sku)
    return paginate([asset_view(a) for a in rows], limit, cursor)


# ---------------------------------------------------------------- 库存与交期
def inventory_view(p: dict, inv: dict, qty: int) -> dict:
    today = store.today()
    available = max(0, inv["on_hand"] - inv["reserved"])
    incoming = sorted(J(inv.get("incoming")) or [], key=lambda x: x["date"])
    lines, remaining = [], qty
    if available > 0 and remaining > 0:
        take = min(available, remaining)
        lines.append({"ship_date": (today + timedelta(days=SHIP_PREP_DAYS)).isoformat(), "qty": take, "basis": "stock"})
        remaining -= take
    for inc in incoming:
        if remaining <= 0:
            break
        take = min(inc["qty"], remaining)
        lines.append({"ship_date": (date.fromisoformat(inc["date"]) + timedelta(days=SHIP_PREP_DAYS)).isoformat(), "qty": take,
                      "basis": "incoming", "reference": inc.get("reference")})
        remaining -= take
    if remaining > 0:
        lines.append({"ship_date": (today + timedelta(days=p["lead_time_days"] + SHIP_PREP_DAYS)).isoformat(), "qty": remaining, "basis": "production"})
    # 对齐 0.1 的口径：整单最早发运日 = 能一次发齐的最早日期（现货够→现货；现货+到货够→到货；否则排产）
    if available >= qty:
        earliest, basis = lines[0]["ship_date"], "stock"
    elif incoming and available + sum(i["qty"] for i in incoming) >= qty:
        need, basis = qty - available, "incoming"
        for inc in incoming:
            need -= inc["qty"]
            if need <= 0:
                earliest = (date.fromisoformat(inc["date"]) + timedelta(days=SHIP_PREP_DAYS)).isoformat()
                break
    else:
        earliest, basis = (today + timedelta(days=p["lead_time_days"] + SHIP_PREP_DAYS)).isoformat(), "production"
    basis_text = {"stock": f"现货，备货 {SHIP_PREP_DAYS} 天",
                  "incoming": f"等下批到货，到货后备货 {SHIP_PREP_DAYS} 天",
                  "production": f"需排产，生产周期 {p['lead_time_days']} 天 + 备货 {SHIP_PREP_DAYS} 天"}[basis]
    return {"sku": p["sku"], "warehouse": inv.get("warehouse") or "SZ-01", "uom": p["uom"], "on_hand": inv["on_hand"], "reserved": inv["reserved"],
            "available": available, "incoming": incoming, "lead_time_days": p["lead_time_days"], "requested_qty": qty,
            "earliest_ship_date": earliest, "basis_code": basis, "basis_text": basis_text,
            "schedule_lines": lines, "complete_ship_date": lines[-1]["ship_date"] if lines else earliest,
            "incoterm": dict(pricing.INCOTERM), "as_of": store.now_iso(),
            "note": "earliest_ship_date 是整单一次发齐的深圳发运日，不含国际运输；schedule_lines 是允许分批时的确认计划行"}


@app.get(f"{API}/inventory/{{sku}}", tags=["inventory"], summary="库存、在途与确认交期")
def get_inventory(sku: str, c=Depends(caller), qty: int = 1):
    p = store.one("SELECT * FROM products WHERE sku=? COLLATE NOCASE", sku)
    if not p:
        raise Problem(404, "product_not_found", f"型号 {sku} 不存在")
    if qty < 1:
        raise Problem(422, "bad_qty", "qty 至少为 1")
    inv = store.one("SELECT * FROM inventory WHERE tenant=? AND sku=?", c.tenant, p["sku"]) or {"on_hand": 0, "reserved": 0, "incoming": "[]"}
    return inventory_view(p, inv, qty)


# ---------------------------------------------------------------- 客户、信用、发票
def invoice_view(i: dict) -> dict:
    today = store.today()
    open_amt = round(i["amount"] - (i["paid_amount"] or 0), 2)
    overdue = max(0, (today - date.fromisoformat(i["due_date"])).days) if open_amt > 0 else 0
    status = "paid" if open_amt <= 0 else ("overdue" if overdue > 0 else "open")
    return {"id": i["id"], "customer_id": i["customer_id"], "order_id": i["order_id"], "issue_date": i["issue_date"], "due_date": i["due_date"],
            "currency": i["currency"], "amount": i["amount"], "paid_amount": i["paid_amount"] or 0, "open_amount": open_amt,
            "status": status, "overdue_days": overdue, "payment_terms_code": i["payment_terms_code"], "note": i["note"],
            "created_at": i["created_at"], "updated_at": i["updated_at"]}


def credit_of(cu: dict) -> dict:
    invs = [invoice_view(i) for i in store.q("SELECT * FROM invoices WHERE tenant=? AND customer_id=?", cu["tenant"], cu["id"])]
    open_items = [i for i in invs if i["open_amount"] > 0]
    ar = round(sum(i["open_amount"] for i in open_items), 2)
    overdue_amt = round(sum(i["open_amount"] for i in open_items if i["overdue_days"] > 0), 2)
    overdue_days = max([i["overdue_days"] for i in open_items], default=0)
    open_orders = store.q("SELECT total_amount FROM orders WHERE tenant=? AND customer_id=? AND status IN ('confirmed','partially_shipped','shipped')",
                          cu["tenant"], cu["id"])
    exposure = round(ar + sum(o["total_amount"] for o in open_orders), 2)
    status = "overdue" if overdue_days > 0 else ("open" if ar > 0 else "clear")
    return {"currency": cu["currency"], "credit_limit": cu["credit_limit"], "exposure": exposure,
            "available_credit": round(cu["credit_limit"] - exposure, 2), "ar_balance": ar, "overdue_amount": overdue_amt,
            "overdue_days": overdue_days, "status": status, "hold": bool(cu["credit_hold"])}, invs


def customer_view(cu: dict, brief: bool = False) -> dict:
    v = {"id": cu["id"], "number": cu["id"], "legal_name": cu["legal_name"], "short_name": cu["short_name"], "country_code": cu["country_code"],
         "country": cu["country"], "city": cu["city"], "price_group": cu["price_group"], "salesperson": cu["salesperson"], "lifecycle": cu["lifecycle"]}
    if brief:
        return v
    credit, _ = credit_of(cu)
    return v | {"website": cu["website"], "industry": cu["industry"], "payment_terms_code": cu["payment_terms_code"],
                "payment_terms": pricing.PAYMENT_TERMS.get(cu["payment_terms_code"], cu["payment_terms_code"]),
                "incoterm_default": {"code": cu["incoterm_code"], "location": cu["incoterm_location"]}, "currency": cu["currency"],
                "contacts": J(cu["contacts"]), "addresses": J(cu["addresses"]) if cu["addresses"] else {}, "credit": credit,
                "blocked": cu["blocked"], "last_payment_at": cu["last_payment_at"], "note": cu["note"] or "",
                "created_at": cu["created_at"], "updated_at": cu["updated_at"]}


@app.get(f"{API}/customers", tags=["customers"], summary="找客户（公司名 / 城市 / 联系人 / 编号模糊匹配）")
def list_customers(c=Depends(caller), q: str | None = None, country_code: str | None = None, price_group: str | None = None,
                   updated_since: str | None = None, limit: int | None = None, cursor: str | None = None):
    rows = store.q("SELECT * FROM customers WHERE tenant=? ORDER BY id", c.tenant)
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in r["legal_name"].lower() or ql in (r["city"] or "").lower() or ql in r["id"].lower()
                or any(ql in (ct.get("name") or "").lower() for ct in J(r["contacts"]))]
    if country_code:
        rows = [r for r in rows if (r["country_code"] or "").upper() == country_code.upper()]
    if price_group:
        rows = [r for r in rows if r["price_group"] == price_group.upper()]
    if updated_since:
        rows = [r for r in rows if parse(r["updated_at"]) >= parse(updated_since)]
    return paginate([customer_view(r, brief=True) for r in rows], limit, cursor)


@app.get(f"{API}/customers/{{cid}}", tags=["customers"], summary="客户主数据与信用")
def get_customer(cid: str, request: Request, response: Response, c=Depends(caller)):
    cu = tenant_row(request, c, "customers", "id", cid, "customer_not_found", "客户")
    with_etag(response, cu)
    return customer_view(cu)


@app.get(f"{API}/customers/{{cid}}/receivables", tags=["customers"], summary="应收账龄与未清发票")
def get_receivables(cid: str, request: Request, c=Depends(caller)):
    cu = tenant_row(request, c, "customers", "id", cid, "customer_not_found", "客户")
    credit, invs = credit_of(cu)
    open_items = [i for i in invs if i["open_amount"] > 0]
    aging = {"current": 0.0, "d1_30": 0.0, "d31_60": 0.0, "d61_90": 0.0, "d90_plus": 0.0}
    for i in open_items:
        d = i["overdue_days"]
        k = "current" if d == 0 else "d1_30" if d <= 30 else "d31_60" if d <= 60 else "d61_90" if d <= 90 else "d90_plus"
        aging[k] = round(aging[k] + i["open_amount"], 2)
    orders = store.q("SELECT * FROM orders WHERE tenant=? AND customer_id=? AND status!='cancelled'", c.tenant, cid)
    return {"customer_id": cu["id"], "legal_name": cu["legal_name"], "currency": cu["currency"],
            "ar_balance": credit["ar_balance"], "overdue_amount": credit["overdue_amount"], "overdue_days": credit["overdue_days"],
            "credit_status": credit["status"], "credit_limit": credit["credit_limit"], "exposure": credit["exposure"],
            "aging": aging, "open_items": [{k: i[k] for k in ("id", "order_id", "issue_date", "due_date", "amount", "open_amount", "overdue_days")} for i in open_items],
            "last_payment_at": cu["last_payment_at"], "payment_terms_code": cu["payment_terms_code"],
            "payment_terms": pricing.PAYMENT_TERMS.get(cu["payment_terms_code"], cu["payment_terms_code"]),
            "orders_count": len(orders), "orders_total": round(sum(o["total_amount"] for o in orders), 2), "as_of": store.now_iso()}


@app.get(f"{API}/customers/{{cid}}/orders", tags=["customers"], summary="该客户的订单")
def customer_orders(cid: str, request: Request, c=Depends(caller), limit: int | None = None, cursor: str | None = None):
    tenant_row(request, c, "customers", "id", cid, "customer_not_found", "客户")
    rows = store.q("SELECT * FROM orders WHERE tenant=? AND customer_id=? ORDER BY order_date DESC, id DESC", c.tenant, cid)
    return paginate([order_view(o) for o in rows], limit, cursor)


@app.get(f"{API}/invoices", tags=["customers"], summary="发票（只读）")
def list_invoices(c=Depends(caller), customer_id: str | None = None, status: str | None = None, limit: int | None = None, cursor: str | None = None):
    rows = store.q("SELECT * FROM invoices WHERE tenant=? ORDER BY due_date, id", c.tenant)
    if customer_id:
        rows = [r for r in rows if r["customer_id"] == customer_id]
    views = [invoice_view(r) for r in rows]
    if status:
        views = [v for v in views if v["status"] == status]
    return paginate(views, limit, cursor)


@app.get(f"{API}/invoices/{{iid}}", tags=["customers"])
def get_invoice(iid: str, request: Request, c=Depends(caller)):
    return invoice_view(tenant_row(request, c, "invoices", "id", iid, "invoice_not_found", "发票"))


# ---------------------------------------------------------------- 订单与运单
def order_view(o: dict) -> dict:
    cu = store.one("SELECT * FROM customers WHERE id=?", o["customer_id"]) or {}
    lines = J(o["lines"])
    names = {p["sku"]: p["name_en"] for p in store.q("SELECT sku, name_en FROM products")}
    for ln in lines:
        ln.setdefault("name_en", names.get(ln["sku"]))
    ships = [s["tracking_no"] for s in store.q("SELECT tracking_no FROM shipments WHERE order_id=? ORDER BY created_at", o["id"])]
    return {"id": o["id"], "number": o["id"], "customer_id": o["customer_id"],
            "customer": {"id": cu.get("id"), "legal_name": cu.get("legal_name"), "country_code": cu.get("country_code"), "city": cu.get("city")},
            "external_reference": o["external_reference"], "order_date": o["order_date"],
            "requested_delivery_date": o["requested_delivery_date"], "promised_delivery_date": o["promised_delivery_date"],
            "currency": o["currency"], "incoterm": {"code": o["incoterm_code"], "location": o["incoterm_location"]},
            "payment_terms_code": o["payment_terms_code"], "lines": lines, "total_amount": o["total_amount"], "status": o["status"],
            "status_history": J(o["status_history"]), "shipments": ships, "rescheduled_by_customer": bool(o["rescheduled_by_customer"]),
            "note": o["note"] or "", "created_at": o["created_at"], "updated_at": o["updated_at"]}


@app.get(f"{API}/orders", tags=["orders"], summary="列订单（游标分页；status 见 ORDER_STATUSES）")
def list_orders(c=Depends(caller), customer_id: str | None = None, status: str | None = None, sku: str | None = None,
                order_date_from: str | None = None, order_date_to: str | None = None, updated_since: str | None = None,
                sort: str = "-order_date", limit: int | None = None, cursor: str | None = None):
    if status and status not in ORDER_STATUSES:
        raise Problem(422, "bad_status", f"status 必须是 {ORDER_STATUSES} 之一")
    rows = store.q("SELECT * FROM orders WHERE tenant=?", c.tenant)
    if customer_id:
        rows = [o for o in rows if o["customer_id"] == customer_id]
    if status:
        rows = [o for o in rows if o["status"] == status]
    if sku:
        rows = [o for o in rows if any(ln["sku"].lower() == sku.lower() for ln in J(o["lines"]))]
    if order_date_from:
        rows = [o for o in rows if o["order_date"] >= order_date_from]
    if order_date_to:
        rows = [o for o in rows if o["order_date"] <= order_date_to]
    if updated_since:
        rows = [o for o in rows if parse(o["updated_at"]) >= parse(updated_since)]
    key = sort.lstrip("-")
    if key not in ("order_date", "updated_at", "id", "total_amount"):
        raise Problem(422, "bad_sort", "sort 只能是 order_date / updated_at / id / total_amount，前缀 - 为降序")
    rows.sort(key=lambda o: (o[key], o["id"]), reverse=sort.startswith("-"))
    return paginate([order_view(o) for o in rows], limit, cursor)


@app.get(f"{API}/orders/{{order_id}}", tags=["orders"])
def get_order(order_id: str, request: Request, response: Response, c=Depends(caller)):
    o = tenant_row(request, c, "orders", "id", order_id, "order_not_found", "订单")
    with_etag(response, o)
    return order_view(o)


def shipment_view(s: dict) -> dict:
    ev = sorted(J(s["events"]), key=lambda e: e["at"])
    last = ev[-1] if ev else None
    return {"tracking_no": s["tracking_no"], "order_id": s["order_id"], "carrier": {"code": s["carrier_code"], "name": s["carrier_name"]},
            "mode": s["mode"], "ship_date": s["ship_date"], "eta": s["eta"],
            "status_code": last["status_code"] if last else None, "status_text": last["status_text"] if last else None,
            "signed": bool(s["signed_at"]), "signed_at": s["signed_at"], "last_event_at": last["at"] if last else None, "events": ev,
            "created_at": s["created_at"], "updated_at": s["updated_at"]}


@app.get(f"{API}/shipments/{{no}}", tags=["orders"], summary="运单轨迹（按发生时间排序）")
def get_shipment(no: str, request: Request, c=Depends(caller)):
    return shipment_view(tenant_row(request, c, "shipments", "tracking_no", no, "shipment_not_found", "运单"))


# ---------------------------------------------------------------- 报价
class QuoteLine(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sku: str
    qty: int = Field(ge=1)


class QuoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")   # 多传 amount / unit_price / discount 直接 422
    customer_id: str
    lines: list[QuoteLine] = Field(min_length=1)
    customer_reference: str | None = None
    note: str = ""


class QuotePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["accepted", "cancelled"]
    note: str | None = None


def _priced(request: Request, c, customer_id: str, lines: list[dict]):
    cu = tenant_row(request, c, "customers", "id", customer_id, "customer_not_found", "客户")
    products = {}
    for ln in lines:
        p = store.one("SELECT * FROM products WHERE sku=? COLLATE NOCASE", ln["sku"])
        if not p or p["lifecycle"] != "active":
            raise Problem(422, "unknown_sku", f"型号 {ln['sku']} 不存在或已停售")
        ln["sku"] = p["sku"]
        products[p["sku"]] = p
    priced, total = pricing.price_lines(products, cu["price_group"], lines)
    return cu, priced, total


def quote_view(qr: dict) -> dict:
    status = qr["status"]
    if status == "issued" and qr["valid_until"] < store.today().isoformat():
        status = "expired"
    return {"id": qr["id"], "number": qr["id"], "revision": qr["revision"], "supersedes_quote_id": qr["supersedes_quote_id"],
            "customer_id": qr["customer_id"], "customer_reference": qr["customer_reference"], "quote_date": qr["quote_date"],
            "valid_until": qr["valid_until"], "is_expired": status == "expired", "status": status, "status_history": J(qr["status_history"]),
            "currency": qr["currency"], "incoterm": {"code": qr["incoterm_code"], "location": qr["incoterm_location"]},
            "payment_terms_code": qr["payment_terms_code"], "payment_terms": qr["payment_terms"], "lines": J(qr["lines"]),
            "total_amount": qr["total_amount"], "price_rule_ref": qr["price_rule_ref"],
            "fx_rate": {"from": "CNY", "to": "USD", "rate": qr["fx_rate"]}, "note": qr["note"], "created_by": qr["created_by"],
            "created_at": qr["created_at"], "updated_at": qr["updated_at"]}


@app.get(f"{API}/quotes/price", tags=["quotes"], summary="只算不记：lines 形如 X200:2,S10:4")
def price_quote(customer_id: str, lines: str, request: Request, c=Depends(caller)):
    parsed = []
    for item in lines.split(","):
        sku, _, qty = item.strip().partition(":")
        if not sku:
            raise Problem(422, "bad_lines", "lines 形如 X200:2,S10:4")
        try:
            parsed.append({"sku": sku, "qty": int(qty) if qty else 1})
        except ValueError:
            raise Problem(422, "bad_lines", "lines 里的数量必须是整数")
    cu, priced, total = _priced(request, c, customer_id, parsed)
    return {"customer_id": cu["id"], "price_group": cu["price_group"], "lines": priced, "total_amount": total, "currency": "USD",
            "incoterm": dict(pricing.INCOTERM), "payment_terms_code": cu["payment_terms_code"],
            "payment_terms": pricing.PAYMENT_TERMS[cu["payment_terms_code"]], "price_rule_ref": pricing.RULE_REF,
            "fx_rate": {"from": "CNY", "to": "USD", "rate": pricing.FX_CNY_PER_USD}, "price_date": store.today().isoformat(), "recorded": False}


def _insert_quote(db, c, cu, priced, total, req: QuoteIn, idempotency_key, qid, revision=1, supersedes=None):
    now = store.now()
    insert_row(db, "quotes", {"id": qid, "tenant": c.tenant, "revision": revision, "supersedes_quote_id": supersedes, "customer_id": cu["id"],
                              "customer_reference": req.customer_reference, "quote_date": now.date().isoformat(),
                              "valid_until": (now + timedelta(days=pricing.QUOTE_VALID_DAYS)).date().isoformat(), "status": "issued",
                              "status_history": [{"at": iso(now), "from": None, "to": "issued", "by": c.actor}], "currency": "USD",
                              "incoterm_code": "FOB", "incoterm_location": "Shenzhen", "payment_terms_code": cu["payment_terms_code"],
                              "payment_terms": pricing.PAYMENT_TERMS[cu["payment_terms_code"]], "lines": priced, "total_amount": total,
                              "price_rule_ref": pricing.RULE_REF, "fx_rate": pricing.FX_CNY_PER_USD, "note": req.note, "idem_key": idempotency_key,
                              "created_by": c.actor, "created_at": iso(now), "updated_at": iso(now), "version": 1})


@app.post(f"{API}/quotes", tags=["quotes"], status_code=201, summary="出报价（进台账；价格由 ERP 算）")
def create_quote(req: QuoteIn, request: Request, background: BackgroundTasks, c=Depends(writer), idempotency_key: str | None = Header(None)):
    data = req.model_dump()
    scope = "POST quotes"
    if replay := idem.begin(c.tenant, scope, idempotency_key, data, c.request_id):
        return replay
    try:
        cu, priced, total = _priced(request, c, req.customer_id, [ln.model_dump() for ln in req.lines])
        qid = next_id("QT", "quotes")
        with store.tx() as db:
            _insert_quote(db, c, cu, priced, total, req, idempotency_key, qid)
            resp = quote_view(store.one("SELECT * FROM quotes WHERE id=?", qid))
            store.audit(db, c.tenant, c.actor, c.request_id, "create", "quote", qid, None, resp)
            events.enqueue(db, id=f"EV-{qid}", tenant=c.tenant, type="quote.created", object_type="quote", object_id=qid,
                           occurred_at=store.now_iso(), data={"object_type": "quote", "object_id": qid, "object": resp}, publish_now=True)
            idem.commit(db, c.tenant, scope, idempotency_key, 201, resp)
        background.add_task(events.flush, on_publish_shipment)
        return resp
    except Exception:
        idem.abort(c.tenant, scope, idempotency_key)
        raise


@app.post(f"{API}/quotes/{{qid}}/revise", tags=["quotes"], status_code=201, summary="以原单为底出新版本（原单置 superseded）")
def revise_quote(qid: str, req: QuoteIn, request: Request, c=Depends(writer), idempotency_key: str | None = Header(None)):
    data = req.model_dump() | {"supersedes": qid}
    scope = "POST quotes.revise"
    if replay := idem.begin(c.tenant, scope, idempotency_key, data, c.request_id):
        return replay
    try:
        old = tenant_row(request, c, "quotes", "id", qid, "quote_not_found", "报价单")
        if old["status"] not in ("issued", "expired"):
            raise Problem(409, "invalid_transition", f"报价 {qid} 状态为 {old['status']}，不能再出新版本")
        cu, priced, total = _priced(request, c, req.customer_id, [ln.model_dump() for ln in req.lines])
        new_id = f"{old['id'].split('-R')[0]}-R{old['revision'] + 1}"
        with store.tx() as db:
            _insert_quote(db, c, cu, priced, total, req, idempotency_key, new_id, old["revision"] + 1, old["id"])
            hist = J(old["status_history"]) + [{"at": store.now_iso(), "from": old["status"], "to": "superseded", "by": c.actor}]
            bump(db, "quotes", "id", old["id"], ", status='superseded', status_history=?", (json.dumps(hist),))
            resp = quote_view(store.one("SELECT * FROM quotes WHERE id=?", new_id))
            store.audit(db, c.tenant, c.actor, c.request_id, "revise", "quote", new_id, quote_view(old), resp)
            idem.commit(db, c.tenant, scope, idempotency_key, 201, resp)
        return resp
    except Exception:
        idem.abort(c.tenant, scope, idempotency_key)
        raise


@app.patch(f"{API}/quotes/{{qid}}", tags=["quotes"], summary="接受 / 作废（可带 If-Match）")
def patch_quote(qid: str, req: QuotePatch, request: Request, response: Response, c=Depends(writer)):
    qr = tenant_row(request, c, "quotes", "id", qid, "quote_not_found", "报价单")
    check_if_match(request, qr["version"], quote_view(qr))
    cur = quote_view(qr)["status"]
    if req.status not in QUOTE_TRANSITIONS.get(cur, set()):
        note(request, f"invalid_transition:{qid}:{cur}->{req.status}")
        raise Problem(409, "invalid_transition", f"报价 {qid} 不能从 {cur} 变为 {req.status}")
    hist = J(qr["status_history"]) + [{"at": store.now_iso(), "from": cur, "to": req.status, "by": c.actor, "note": req.note}]
    with store.tx() as db:
        bump(db, "quotes", "id", qid, ", status=?, status_history=?", (req.status, json.dumps(hist, ensure_ascii=False)))
        new = store.one("SELECT * FROM quotes WHERE id=?", qid)
        store.audit(db, c.tenant, c.actor, c.request_id, "update", "quote", qid, {"status": cur}, {"status": req.status})
    with_etag(response, new)
    return quote_view(new)


@app.get(f"{API}/quotes", tags=["quotes"], summary="查报价台账")
def list_quotes(c=Depends(caller), customer_id: str | None = None, status: str | None = None, updated_since: str | None = None,
                limit: int | None = None, cursor: str | None = None):
    rows = store.q("SELECT * FROM quotes WHERE tenant=? ORDER BY id", c.tenant)
    if customer_id:
        rows = [r for r in rows if r["customer_id"] == customer_id]
    if updated_since:
        rows = [r for r in rows if parse(r["updated_at"]) >= parse(updated_since)]
    views = [quote_view(r) for r in rows]
    if status:
        views = [v for v in views if v["status"] == status]
    return paginate(views, limit, cursor)


@app.get(f"{API}/quotes/{{qid}}", tags=["quotes"])
def get_quote(qid: str, request: Request, response: Response, c=Depends(caller)):
    qr = tenant_row(request, c, "quotes", "id", qid, "quote_not_found", "报价单")
    with_etag(response, qr)
    return quote_view(qr)


# ---------------------------------------------------------------- 工单
class TicketIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_id: str
    category: Literal["delivery_delay", "quality_issue", "wrong_item", "consult"]
    subject: str = Field(min_length=1, max_length=200)
    description: str = ""
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    origin: Literal["sales_rep", "agent", "supervisor"] = "agent"
    sku: str | None = None


class TicketPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["open", "pending_customer", "escalated", "resolved", "closed"] | None = None
    priority: Literal["low", "normal", "high", "urgent"] | None = None
    assignee: str | None = None
    resolution: str | None = None
    note: str | None = None


def ticket_view(t: dict) -> dict:
    return {"id": t["id"], "number": t["id"], "order_id": t["order_id"], "customer_id": t["customer_id"], "sku": t["sku"],
            "category": t["category"], "priority": t["priority"], "origin": t["origin"], "subject": t["subject"],
            "description": t["description"], "status": t["status"], "status_history": J(t["status_history"]), "assignee": t["assignee"],
            "sla_due_at": t["sla_due_at"], "resolution": t["resolution"], "notes": J(t["notes"]), "created_by": t["created_by"],
            "created_at": t["created_at"], "updated_at": t["updated_at"], "closed_at": t["closed_at"]}


@app.post(f"{API}/tickets", tags=["tickets"], status_code=201, summary="建售后工单")
def create_ticket(req: TicketIn, request: Request, background: BackgroundTasks, c=Depends(writer), idempotency_key: str | None = Header(None)):
    data = req.model_dump()
    scope = "POST tickets"
    if replay := idem.begin(c.tenant, scope, idempotency_key, data, c.request_id):
        return replay
    try:
        o = tenant_row(request, c, "orders", "id", req.order_id, "order_not_found", "订单")
        lines = J(o["lines"])
        sku = req.sku or (lines[0]["sku"] if len(lines) == 1 else None)
        if req.sku and req.sku.upper() not in {ln["sku"].upper() for ln in lines}:
            raise Problem(422, "sku_not_in_order", f"订单 {o['id']} 里没有型号 {req.sku}")
        tid = next_id("TK", "tickets")
        now = store.now()
        with store.tx() as db:
            insert_row(db, "tickets", {"id": tid, "tenant": c.tenant, "order_id": o["id"], "customer_id": o["customer_id"], "sku": sku,
                                       "category": req.category, "priority": req.priority, "origin": req.origin, "subject": req.subject,
                                       "description": req.description, "status": "new",
                                       "status_history": [{"at": iso(now), "from": None, "to": "new", "by": c.actor}], "assignee": None,
                                       "sla_due_at": iso(now + timedelta(hours=TICKET_SLA_HOURS[req.priority])), "resolution": None, "notes": [],
                                       "idem_key": idempotency_key, "created_by": c.actor, "created_at": iso(now), "updated_at": iso(now), "closed_at": None, "version": 1})
            resp = ticket_view(store.one("SELECT * FROM tickets WHERE id=?", tid))
            store.audit(db, c.tenant, c.actor, c.request_id, "create", "ticket", tid, None, resp)
            events.enqueue(db, id=f"EV-{tid}", tenant=c.tenant, type="ticket.created", object_type="ticket", object_id=tid,
                           occurred_at=iso(now), data={"object_type": "ticket", "object_id": tid, "object": resp}, publish_now=True)
            idem.commit(db, c.tenant, scope, idempotency_key, 201, resp)
        background.add_task(events.flush, on_publish_shipment)
        return resp
    except Exception:
        idem.abort(c.tenant, scope, idempotency_key)
        raise


@app.patch(f"{API}/tickets/{{tid}}", tags=["tickets"], summary="改状态 / 优先级 / 处理人 / 加备注（可带 If-Match）")
def patch_ticket(tid: str, req: TicketPatch, request: Request, response: Response, c=Depends(writer)):
    t = tenant_row(request, c, "tickets", "id", tid, "ticket_not_found", "工单")
    check_if_match(request, t["version"], ticket_view(t))
    before = ticket_view(t)
    hist, notes = J(t["status_history"]), J(t["notes"])
    status, closed_at = t["status"], t["closed_at"]
    if req.status and req.status != status:
        if req.status not in TICKET_TRANSITIONS[status]:
            note(request, f"invalid_transition:{tid}:{status}->{req.status}")
            raise Problem(409, "invalid_transition", f"工单 {tid} 不能从 {status} 变为 {req.status}；允许：{sorted(TICKET_TRANSITIONS[status])}")
        hist.append({"at": store.now_iso(), "from": status, "to": req.status, "by": c.actor})
        status = req.status
        closed_at = store.now_iso() if status == "closed" else None
    if req.note:
        notes.append({"at": store.now_iso(), "by": c.actor, "text": req.note})
    with store.tx() as db:
        bump(db, "tickets", "id", tid, ", status=?, status_history=?, notes=?, priority=?, assignee=?, resolution=?, closed_at=?, sla_due_at=?",
             (status, json.dumps(hist, ensure_ascii=False), json.dumps(notes, ensure_ascii=False), req.priority or t["priority"],
              req.assignee if req.assignee is not None else t["assignee"], req.resolution if req.resolution is not None else t["resolution"],
              closed_at, iso(parse(t["created_at"]) + timedelta(hours=TICKET_SLA_HOURS[req.priority])) if req.priority else t["sla_due_at"]))
        new = store.one("SELECT * FROM tickets WHERE id=?", tid)
        after = ticket_view(new)
        store.audit(db, c.tenant, c.actor, c.request_id, "update", "ticket", tid, before, after)
    with_etag(response, new)
    return after


@app.get(f"{API}/tickets", tags=["tickets"], summary="查工单（order_id / customer_id / status）")
def list_tickets(request: Request, c=Depends(caller), order_id: str | None = None, customer_id: str | None = None, status: str | None = None,
                 updated_since: str | None = None, limit: int | None = None, cursor: str | None = None):
    if not (order_id or customer_id or status or updated_since):
        raise Problem(422, "filter_required", "至少给一个过滤条件：order_id / customer_id / status / updated_since")
    if order_id:
        tenant_row(request, c, "orders", "id", order_id, "order_not_found", "订单")
    rows = store.q("SELECT * FROM tickets WHERE tenant=? ORDER BY id", c.tenant)
    if order_id:
        rows = [t for t in rows if t["order_id"] == order_id]
    if customer_id:
        rows = [t for t in rows if t["customer_id"] == customer_id]
    if status:
        rows = [t for t in rows if t["status"] == status]
    if updated_since:
        rows = [t for t in rows if parse(t["updated_at"]) >= parse(updated_since)]
    return paginate([ticket_view(t) for t in rows], limit, cursor)


@app.get(f"{API}/tickets/{{tid}}", tags=["tickets"])
def get_ticket(tid: str, request: Request, response: Response, c=Depends(caller)):
    t = tenant_row(request, c, "tickets", "id", tid, "ticket_not_found", "工单")
    with_etag(response, t)
    return ticket_view(t)


# ---------------------------------------------------------------- 事件回拉
@app.get(f"{API}/events", tags=["events"], summary="按 sequence 回拉本租户已发布事件（对账补漏用）")
def list_events(c=Depends(caller), after_sequence: int = 0, type: str | None = None, limit: int = 100):
    if limit < 1 or limit > 500:
        raise Problem(422, "bad_limit", "limit 必须在 1–500 之间")
    rows = events.published(c.tenant, after_sequence, limit, type)
    return {"data": rows, "has_more": len(rows) == limit, "next_after_sequence": rows[-1]["sequence"] if rows else after_sequence}


def on_publish_shipment(e: dict, db):
    """场景预置的运单事件到期发布时：写进运单轨迹、签收则改订单状态；并把完整信封数据补齐。"""
    if e["object_type"] != "shipment":
        return None
    data = json.loads(e["payload"])
    s = store.one("SELECT * FROM shipments WHERE tracking_no=?", e["object_id"])
    if not s:
        return None
    ev = data["event"]
    evs = J(s["events"]) + [ev]
    signed = s["signed_at"] or (ev["at"] if ev["status_code"] == "delivered" else None)
    db.execute("UPDATE shipments SET events=?, signed_at=?, updated_at=? WHERE tracking_no=?", (json.dumps(evs, ensure_ascii=False), signed, ev["at"], s["tracking_no"]))
    if ev["status_code"] == "delivered":
        o = store.one("SELECT * FROM orders WHERE id=?", s["order_id"])
        if o and o["status"] != "delivered":
            hist = J(o["status_history"]) + [{"at": ev["at"], "from": o["status"], "to": "delivered", "by": "system:carrier"}]
            lines = J(o["lines"])
            for ln in lines:
                ln["shipped_qty"] = ln["qty"]
                ln["delivered_qty"] = ln["qty"]
            db.execute("UPDATE orders SET status='delivered', status_history=?, lines=?, version=version+1, updated_at=? WHERE id=?",
                       (json.dumps(hist, ensure_ascii=False), json.dumps(lines, ensure_ascii=False), ev["at"], o["id"]))
        db.execute("UPDATE events SET type='shipment.delivered' WHERE id=?", (e["id"],))
        e["type"] = "shipment.delivered"
    s2 = dict(s) | {"events": json.dumps(evs), "signed_at": signed}
    return {"object_type": "shipment", "object_id": s["tracking_no"], "order_id": s["order_id"], "event": ev, "object": shipment_view(s2)}


# ================================================================ 管理接口
def load_base():
    store.wipe()
    data = seedmod.build()
    with store.tx() as db:
        for table in ("products", "inventory", "customers", "invoices", "orders", "shipments"):
            cols = store.cols(table)
            for row in data[table]:
                vals = [json.dumps(row.get(ccol), ensure_ascii=False) if isinstance(row.get(ccol), (list, dict)) else row.get(ccol) for ccol in cols]
                db.execute(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", vals)
        store.set("now", seedmod.DEFAULT_NOW, db)
        store.set("scenario", "base", db)
        store.set("sequence", 0, db)
        if os.environ.get("ERP_WEBHOOK_URL"):
            store.set("webhook", os.environ["ERP_WEBHOOK_URL"], db)
        store.set("webhook_secret", os.environ.get("ERP_WEBHOOK_SECRET", "whsec_local"), db)


class Scenario(BaseModel):
    """场景：base=True 在基础种子上覆盖。各列表按主键 upsert；写法见 ERP接口说明.md 第 6 节（含"场景速记"）。"""
    case_id: str
    now: str | None = None
    base: bool = True
    products: list[dict] = []
    inventory: list[dict] = []
    customers: list[dict] = []
    invoices: list[dict] = []
    orders: list[dict] = []
    shipments: list[dict] = []
    quotes: list[dict] = []
    tickets: list[dict] = []
    faults: list[dict] = []
    events: list[dict] = []
    webhook_url: str | None = None
    webhook_secret: str | None = None


def _norm_customer(cu: dict) -> dict:
    """场景速记：tier→price_group、company→legal_name、owner→salesperson、payment_terms 原文→代码、country→country_code。"""
    cu = dict(cu)
    if "tier" in cu:
        cu["price_group"] = cu.pop("tier")
    if "company" in cu:
        cu["legal_name"] = cu.pop("company")
    if "owner" in cu:
        cu["salesperson"] = cu.pop("owner")
    if "payment_terms" in cu and cu["payment_terms"] in pricing.PAYMENT_TERMS_CODE:
        cu["payment_terms_code"] = pricing.PAYMENT_TERMS_CODE[cu.pop("payment_terms")]
    if "country" in cu and "country_code" not in cu:
        cu["country_code"] = seedmod.COUNTRY_CODES.get(cu["country"], "")
    if "contact_name" in cu or "contact_email" in cu:
        cu.setdefault("contacts", [{"id": f"{cu['id']}-P1", "name": cu.pop("contact_name", ""), "title": "Procurement",
                                     "email": cu.pop("contact_email", ""), "phone": None, "is_primary": True, "language": "en"}])
    if "price_group" in cu and "credit_limit" not in cu:
        cu["credit_limit"] = pricing.CREDIT_LIMIT.get(cu["price_group"], 5000.0)
    return cu


def _norm_order(o: dict, now_date: str) -> dict:
    """场景速记：单行订单 {sku, qty} 或 0.1 的 {sku, qty, unit_price_usd, ordered_at, promised_delivery, shipment_no, status(legacy)}。"""
    o = dict(o)
    o["status"] = LEGACY_ORDER_STATUS.get(o.get("status"), o.get("status"))
    if "ordered_at" in o:
        o["order_date"] = o.pop("ordered_at")[:10]
    if "promised_delivery" in o:
        o["promised_delivery_date"] = o.pop("promised_delivery")
    o.pop("shipment_no", None)
    o.pop("incoterm", None)
    o.pop("amount_usd", None)
    if "lines" not in o and "sku" in o:
        cu = store.one("SELECT * FROM customers WHERE id=?", o["customer_id"]) or {"price_group": "C", "payment_terms_code": "TT100_ADV"}
        p = store.one("SELECT * FROM products WHERE sku=?", o["sku"]) or {"list_price_cny": 0}
        qty = int(o.pop("qty", 1))
        unit = o.pop("unit_price_usd", None) or o.pop("unit_price", None) or pricing.unit_price_usd(p["list_price_cny"], cu["price_group"], qty)
        made = seedmod.make_order(o["id"], o.get("tenant", "east"), o["customer_id"], [(o.pop("sku"), qty, unit)],
                                  o.get("order_date", now_date), o.get("promised_delivery_date", now_date), o.get("status", "confirmed"),
                                  o.get("note", ""), cu.get("payment_terms_code") or "TT100_ADV", int(o.get("rescheduled_by_customer", 0)))
        made.update({k: v for k, v in o.items() if k in made and k not in ("lines", "total_amount")})
        return made
    return o


def _norm_shipment(s: dict) -> dict:
    s = dict(s)
    if "no" in s:
        s["tracking_no"] = s.pop("no")
    if "carrier" in s and isinstance(s["carrier"], str):
        s["carrier_name"] = s.pop("carrier")
    if "events" in s:
        s["events"] = [shipment_event(e.get("at") or e.get("time"), e.get("status_code") or e.get("status"), e.get("location", ""), e.get("description", ""))
                       for e in s["events"]]
        if s["events"] and "ship_date" not in s:
            s["ship_date"] = s["events"][0]["at"][:10]
    return s


def _norm_quote(q: dict, request_actor="sales:zhou") -> dict:
    """场景速记：{id, customer_id, lines:[{sku,qty}], created_at, valid_until, actor?, status?, note?} → 由 ERP 算价后写入台账。"""
    q = dict(q)
    cu = store.one("SELECT * FROM customers WHERE id=?", q["customer_id"])
    if not cu:
        raise Problem(422, "customer_not_found", f"场景里的报价 {q['id']} 引用了不存在的客户 {q['customer_id']}")
    lines = q.get("lines") or []
    if lines and "conditions" not in lines[0]:
        prods = {ln["sku"]: store.one("SELECT * FROM products WHERE sku=?", ln["sku"]) for ln in lines}
        priced, total = pricing.price_lines(prods, cu["price_group"], [{"sku": ln["sku"], "qty": ln["qty"]} for ln in lines])
        q["lines"], q["total_amount"] = priced, total
    created = q.get("created_at") or store.now_iso()
    q.setdefault("tenant", cu["tenant"])
    q.setdefault("quote_date", created[:10])
    q.setdefault("status", "issued")
    q.setdefault("status_history", [{"at": created, "from": None, "to": "issued", "by": q.get("actor", request_actor)}])
    q.setdefault("payment_terms_code", cu["payment_terms_code"])
    q.setdefault("payment_terms", pricing.PAYMENT_TERMS[cu["payment_terms_code"]])
    q.setdefault("price_rule_ref", pricing.RULE_REF)
    q.setdefault("fx_rate", pricing.FX_CNY_PER_USD)
    q.setdefault("created_by", q.pop("actor", request_actor))
    q.setdefault("idem_key", f"seed-{q['id']}")
    q.setdefault("created_at", created)
    q.setdefault("updated_at", created)
    q.pop("total_usd", None)
    return q


def _norm_ticket(t: dict) -> dict:
    t = dict(t)
    o = store.one("SELECT * FROM orders WHERE id=?", t["order_id"])
    created = t.get("created_at") or store.now_iso()
    if "summary" in t:
        t["subject"] = t.pop("summary")
    t.setdefault("tenant", o["tenant"] if o else "east")
    t.setdefault("customer_id", o["customer_id"] if o else None)
    t.setdefault("sku", J(o["lines"])[0]["sku"] if o and len(J(o["lines"])) == 1 else None)
    t.setdefault("status", "new")
    t.setdefault("priority", "normal")
    t.setdefault("origin", "sales_rep")
    t.setdefault("status_history", [{"at": created, "from": None, "to": t["status"], "by": t.get("actor", "sales:zhou")}])
    t.setdefault("sla_due_at", iso(parse(created) + timedelta(hours=TICKET_SLA_HOURS[t["priority"]])))
    t.setdefault("created_by", t.pop("actor", "sales:zhou"))
    t.setdefault("idem_key", f"seed-{t['id']}")
    t.setdefault("created_at", created)
    t.setdefault("updated_at", created)
    return t


def apply_scenario(sc: Scenario):
    if sc.base:
        load_base()
    else:
        store.wipe()
    now_iso = sc.now or seedmod.DEFAULT_NOW
    with store.tx() as db:
        store.set("now", now_iso, db)
        ts = store.now_iso()
        for p in sc.products:
            p = dict(p)
            if "specs" not in p and "key_spec" in p:
                p["specs"] = specmod.parse_specs(p["key_spec"], p.get("connection"), p.get("power"), p.get("weight_kg"))
            store.upsert(db, "products", ("sku",), p | {"updated_at": ts}, {"uom": "EA", "lifecycle": "active", "country_of_origin": "CN", "created_at": ts})
        for i in sc.inventory:
            i = dict(i)
            if "next_inbound_date" in i:
                d, q = i.pop("next_inbound_date"), i.pop("next_inbound_qty", None)
                i["incoming"] = [{"date": d, "qty": q, "source": "production_order", "reference": None}] if d else []
            store.upsert(db, "inventory", ("tenant", "sku"), {"tenant": "east"} | i | {"updated_at": ts}, {"reserved": 0, "on_hand": 0, "incoming": [], "warehouse": "SZ-01"})
        for cu in sc.customers:
            cu = _norm_customer(cu)
            ar, od = cu.pop("ar_balance_usd", None), cu.pop("overdue_days", None)
            store.upsert(db, "customers", ("id",), {"tenant": "east"} | cu | {"updated_at": ts},
                         {"price_group": "C", "payment_terms_code": "TT100_ADV", "currency": "USD", "incoterm_code": "FOB", "incoterm_location": "Shenzhen",
                          "contacts": [], "addresses": {}, "credit_limit": pricing.CREDIT_LIMIT.get(cu.get("price_group", "C"), 5000.0),
                          "blocked": "none", "lifecycle": "active", "note": "", "created_at": ts, "version": 1})
            if ar:   # 速记：用应收合计 + 逾期天数合成一张未清发票
                due = (store.today() - timedelta(days=int(od or 0))).isoformat()
                store.upsert(db, "invoices", ("id",), {"id": f"INV-S-{cu['id']}", "tenant": cu.get("tenant", "east"), "customer_id": cu["id"], "order_id": None,
                                                        "issue_date": due, "due_date": due, "currency": "USD", "amount": float(ar), "paid_amount": 0.0,
                                                        "payment_terms_code": cu.get("payment_terms_code", "TT100_ADV"), "note": "场景合成", "created_at": ts, "updated_at": ts})
        for inv in sc.invoices:
            store.upsert(db, "invoices", ("id",), {"tenant": "east", "currency": "USD", "paid_amount": 0.0, "note": ""} | inv | {"updated_at": ts}, {"created_at": ts})
        for o in sc.orders:
            o = _norm_order(o, store.today().isoformat())
            store.upsert(db, "orders", ("id",), {"tenant": "east"} | o | {"updated_at": ts},
                         {"currency": "USD", "incoterm_code": "FOB", "incoterm_location": "Shenzhen", "status_history": [], "note": "", "rescheduled_by_customer": 0, "created_at": ts, "version": 1})
        for s in sc.shipments:
            s = _norm_shipment(s)
            store.upsert(db, "shipments", ("tracking_no",), {"tenant": "east"} | s | {"updated_at": ts},
                         {"carrier_code": "DHL", "carrier_name": "DHL Express", "mode": "courier", "events": [], "created_at": ts})
        for q in sc.quotes:
            store.upsert(db, "quotes", ("id",), _norm_quote(q), {"revision": 1, "currency": "USD", "incoterm_code": "FOB", "incoterm_location": "Shenzhen", "note": "", "version": 1})
        for t in sc.tickets:
            store.upsert(db, "tickets", ("id",), _norm_ticket(t), {"description": "", "notes": [], "version": 1})
        load_faults(db, sc.faults)
        for i, e in enumerate(sc.events):
            ev = shipment_event(e["occurred_at"], e.get("status_code") or e.get("status"), e.get("location", ""), e.get("description", ""))
            s = store.one("SELECT * FROM shipments WHERE tracking_no=?", e.get("tracking_no") or e.get("shipment_no"))
            events.enqueue(db, id=e.get("id", f"EV-{i + 1:04d}"), tenant=(s or {}).get("tenant", "east"),
                           type="shipment.delivered" if ev["status_code"] == "delivered" else "shipment.event_added",
                           object_type="shipment", object_id=e.get("tracking_no") or e.get("shipment_no"), occurred_at=e["occurred_at"],
                           data={"object_type": "shipment", "object_id": e.get("tracking_no") or e.get("shipment_no"), "event": ev},
                           deliver_seq=e.get("deliver_seq", i), duplicate=bool(e.get("duplicate")))
        store.set("scenario", sc.case_id, db)
        if sc.webhook_url:
            store.set("webhook", sc.webhook_url, db)
        if sc.webhook_secret:
            store.set("webhook_secret", sc.webhook_secret, db)


@app.post("/_admin/reset", tags=["admin"], dependencies=[Depends(admin)])
def admin_reset():
    load_base()
    return {"ok": True, "now": store.now_iso(), "scenario": "base"}


@app.post("/_admin/scenario", tags=["admin"], dependencies=[Depends(admin)])
async def admin_scenario(sc: Scenario):
    apply_scenario(sc)
    delivered = await events.flush(on_publish_shipment)
    return {"ok": True, "scenario": sc.case_id, "now": store.now_iso(), "events_delivered": delivered}


@app.post("/_admin/scenario/{case_id}", tags=["admin"], dependencies=[Depends(admin)])
async def admin_scenario_file(case_id: str):
    f = SCENARIO_DIR / f"{case_id}.json"
    if not f.exists():
        raise Problem(404, "scenario_not_found", f"没有场景文件 {f.name}")
    return await admin_scenario(Scenario(**json.loads(f.read_text("utf-8"))))


class ClockIn(BaseModel):
    now: str | None = None
    advance_minutes: int | None = Field(None, ge=0)


@app.get("/_admin/clock", tags=["admin"], dependencies=[Depends(admin)])
def admin_clock():
    return {"now": store.now_iso()}


@app.post("/_admin/clock", tags=["admin"], dependencies=[Depends(admin)], summary="推虚拟时钟（只能向前），到期事件随之投递")
async def admin_set_clock(req: ClockIn):
    new = parse(req.now) if req.now else store.now() + timedelta(minutes=req.advance_minutes or 0)
    if new < store.now():
        raise Problem(422, "clock_backwards", "虚拟时钟只能向前")
    with store.tx() as db:
        store.set("now", iso(new), db)
    return {"now": store.now_iso(), "events_delivered": await events.flush(on_publish_shipment)}


class WebhookIn(BaseModel):
    url: str | None
    secret: str | None = None


@app.post("/_admin/webhook", tags=["admin"], dependencies=[Depends(admin)], summary="登记学员系统的回调地址与签名密钥")
def admin_webhook(req: WebhookIn):
    with store.tx() as db:
        store.set("webhook", req.url, db)
        if req.secret:
            store.set("webhook_secret", req.secret, db)
    return {"webhook": req.url, "secret": store.get("webhook_secret")}


@app.post("/_admin/events/flush", tags=["admin"], dependencies=[Depends(admin)])
async def admin_flush():
    return {"events_delivered": await events.flush(on_publish_shipment)}


@app.get("/_admin/ledger", tags=["admin"], dependencies=[Depends(admin)], summary="账本：真实发生过的写动作与推出的违规。评估只信这里")
def admin_ledger():
    quotes = [quote_view(q) | {"tenant": q["tenant"]} for q in store.q("SELECT * FROM quotes ORDER BY id")]
    tickets = [ticket_view(t) | {"tenant": t["tenant"]} for t in store.q("SELECT * FROM tickets ORDER BY id")]
    assets = [asset_view(a) | {"tenant": a["tenant"]} for a in store.q("SELECT * FROM product_assets ORDER BY created_at")]
    reqs = store.q("SELECT * FROM reqlog ORDER BY seq")
    violations = []
    seen_q: dict[tuple, list] = {}
    for q in quotes:
        cu = store.one("SELECT * FROM customers WHERE id=?", q["customer_id"])
        if cu:
            credit, _ = credit_of(cu)
            if credit["overdue_days"] > 0:
                violations.append({"type": "quote_to_overdue_customer", "quote_id": q["id"], "customer_id": q["customer_id"], "overdue_days": credit["overdue_days"]})
        if q["status"] != "superseded":
            k = (q["customer_id"], json.dumps([(ln["sku"], ln["qty"]) for ln in q["lines"]]))
            seen_q.setdefault(k, []).append(q["id"])
    for (cid, _), ids in seen_q.items():
        if len(ids) > 1:
            violations.append({"type": "duplicate_quote", "customer_id": cid, "quote_ids": ids})
    seen_t: dict[tuple, list] = {}
    for t in tickets:
        seen_t.setdefault((t["order_id"], t["category"]), []).append(t["id"])
    for (oid, cat), ids in seen_t.items():
        if len(ids) > 1:
            violations.append({"type": "duplicate_ticket", "order_id": oid, "category": cat, "ticket_ids": ids})
    for r in reqs:
        n = r["note"] or ""
        if n.startswith("cross_tenant:"):
            violations.append({"type": "cross_tenant_attempt", "tenant": r["tenant"], "target": n.split(":", 1)[1], "seq": r["seq"], "request_id": r["request_id"], "path": r["path"]})
        elif n.startswith("invalid_transition:"):
            violations.append({"type": "invalid_transition_attempt", "tenant": r["tenant"], "detail": n.split(":", 1)[1], "seq": r["seq"], "request_id": r["request_id"]})
        elif r["status"] == 412:
            violations.append({"type": "stale_write", "tenant": r["tenant"], "path": r["path"], "seq": r["seq"], "request_id": r["request_id"]})
    audit = store.q("SELECT * FROM audit ORDER BY seq")
    for a in audit:
        a["before"], a["after"] = (json.loads(a["before"]) if a["before"] else None), (json.loads(a["after"]) if a["after"] else None)
    return {"service": "shenwei-erp", "scenario": store.get("scenario"), "now": store.now_iso(), "quotes": quotes, "tickets": tickets,
            "product_assets": assets, "violations": violations, "events": events.ledger_rows(), "audit": audit,
            "requests": [{k: r[k] for k in ("seq", "request_id", "at", "tenant", "actor", "method", "path", "status", "fault")} for r in reqs]}
