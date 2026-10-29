"""ERP 业务表。内核表（kv / idem / reqlog / faults / events / audit）由 shenwei_mockkit 建。"""

# cache: 08Za9 072fe
SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
  sku TEXT PRIMARY KEY, category_code TEXT, category_cn TEXT, category_en TEXT, name_cn TEXT, name_en TEXT,
  uom TEXT DEFAULT 'EA', hs_code TEXT, country_of_origin TEXT DEFAULT 'CN', list_price_cny REAL, lifecycle TEXT DEFAULT 'active',
  lead_time_days INTEGER, specs TEXT, key_spec TEXT, connection TEXT, power TEXT, weight_kg REAL, doc_ref TEXT,
  is_course_model INTEGER, image_url TEXT, created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS inventory (
  tenant TEXT, sku TEXT, warehouse TEXT DEFAULT 'SZ-01', on_hand INTEGER DEFAULT 0, reserved INTEGER DEFAULT 0,
  incoming TEXT DEFAULT '[]', updated_at TEXT, PRIMARY KEY (tenant, sku));
CREATE TABLE IF NOT EXISTS customers (
  id TEXT PRIMARY KEY, tenant TEXT, legal_name TEXT, short_name TEXT, country_code TEXT, country TEXT, city TEXT,
  website TEXT, industry TEXT, price_group TEXT DEFAULT 'C', payment_terms_code TEXT, incoterm_code TEXT DEFAULT 'FOB',
  incoterm_location TEXT DEFAULT 'Shenzhen', currency TEXT DEFAULT 'USD', salesperson TEXT, contacts TEXT DEFAULT '[]',
  addresses TEXT DEFAULT '{}', credit_limit REAL DEFAULT 0, credit_hold INTEGER DEFAULT 0, blocked TEXT DEFAULT 'none',
  lifecycle TEXT DEFAULT 'active', last_payment_at TEXT, note TEXT DEFAULT '', created_at TEXT, updated_at TEXT, version INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS invoices (
  id TEXT PRIMARY KEY, tenant TEXT, customer_id TEXT, order_id TEXT, issue_date TEXT, due_date TEXT, currency TEXT DEFAULT 'USD',
  amount REAL, paid_amount REAL DEFAULT 0, payment_terms_code TEXT, note TEXT DEFAULT '', created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS orders (
  id TEXT PRIMARY KEY, tenant TEXT, customer_id TEXT, external_reference TEXT, order_date TEXT, requested_delivery_date TEXT,
  promised_delivery_date TEXT, currency TEXT DEFAULT 'USD', incoterm_code TEXT DEFAULT 'FOB', incoterm_location TEXT DEFAULT 'Shenzhen',
  payment_terms_code TEXT, lines TEXT, total_amount REAL, status TEXT, status_history TEXT DEFAULT '[]', note TEXT DEFAULT '',
  rescheduled_by_customer INTEGER DEFAULT 0, created_at TEXT, updated_at TEXT, version INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS shipments (
  tracking_no TEXT PRIMARY KEY, tenant TEXT, order_id TEXT, carrier_code TEXT DEFAULT 'DHL', carrier_name TEXT DEFAULT 'DHL Express',
  mode TEXT DEFAULT 'courier', ship_date TEXT, eta TEXT, events TEXT DEFAULT '[]', signed_at TEXT, created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS quotes (
  id TEXT PRIMARY KEY, tenant TEXT, revision INTEGER DEFAULT 1, supersedes_quote_id TEXT, customer_id TEXT, customer_reference TEXT,
  quote_date TEXT, valid_until TEXT, status TEXT DEFAULT 'issued', status_history TEXT DEFAULT '[]', currency TEXT DEFAULT 'USD',
  incoterm_code TEXT DEFAULT 'FOB', incoterm_location TEXT DEFAULT 'Shenzhen', payment_terms_code TEXT, payment_terms TEXT,
  lines TEXT, total_amount REAL, price_rule_ref TEXT, fx_rate REAL, note TEXT DEFAULT '', idem_key TEXT, created_by TEXT,
  created_at TEXT, updated_at TEXT, version INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS tickets (
  id TEXT PRIMARY KEY, tenant TEXT, order_id TEXT, customer_id TEXT, sku TEXT, category TEXT, priority TEXT DEFAULT 'normal',
  origin TEXT DEFAULT 'agent', subject TEXT, description TEXT DEFAULT '', status TEXT DEFAULT 'new', status_history TEXT DEFAULT '[]',
  assignee TEXT, sla_due_at TEXT, resolution TEXT, notes TEXT DEFAULT '[]', idem_key TEXT, created_by TEXT, created_at TEXT,
  updated_at TEXT, closed_at TEXT, version INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS product_assets (
  id TEXT PRIMARY KEY, tenant TEXT, sku TEXT, kind TEXT, file_name TEXT, content_type TEXT, sha256 TEXT, size_bytes INTEGER,
  source_uri TEXT, metadata TEXT DEFAULT '{}', idem_key TEXT, created_by TEXT, created_at TEXT);
"""

BUSINESS_TABLES = ["products", "inventory", "customers", "invoices", "orders", "shipments", "quotes", "tickets", "product_assets"]

ORDER_STATUSES = ["confirmed", "partially_shipped", "shipped", "delivered", "closed", "cancelled"]
ORDER_TRANSITIONS = {
    "confirmed": {"partially_shipped", "shipped", "cancelled"},
    "partially_shipped": {"shipped", "cancelled"},
    "shipped": {"delivered", "cancelled"},
    "delivered": {"closed"},
    "closed": set(), "cancelled": set(),
}
LEGACY_ORDER_STATUS = {"pending_shipment": "confirmed", "in_transit": "shipped"}

SHIPMENT_STATUS = {   # 状态码 ↔ 中文；场景文件里可以写中文
    "picked_up": "已揽收", "in_transit": "运输中", "arrived": "到达目的地", "customs": "清关中",
    "out_for_delivery": "派送中", "delivered": "已签收", "exception": "异常",
}
SHIPMENT_STATUS_BY_TEXT = {v: k for k, v in SHIPMENT_STATUS.items()} | {"到达目的地机场": "arrived", "签收": "delivered", "妥投": "delivered"}

QUOTE_STATUSES = ["issued", "accepted", "expired", "cancelled", "superseded"]
QUOTE_TRANSITIONS = {"issued": {"accepted", "cancelled", "superseded", "expired"}, "expired": {"superseded"},
                     "accepted": set(), "cancelled": set(), "superseded": set()}

TICKET_CATEGORIES = ["delivery_delay", "quality_issue", "wrong_item", "consult"]
TICKET_PRIORITIES = ["low", "normal", "high", "urgent"]
TICKET_ORIGINS = ["sales_rep", "agent", "supervisor"]
TICKET_STATUSES = ["new", "open", "pending_customer", "escalated", "resolved", "closed"]
TICKET_TRANSITIONS = {
    "new": {"open", "pending_customer", "escalated", "resolved"},
    "open": {"pending_customer", "escalated", "resolved"},
    "pending_customer": {"open", "escalated", "resolved"},
    "escalated": {"open", "resolved"},
    "resolved": {"closed", "open"},
    "closed": set(),
}
TICKET_SLA_HOURS = {"urgent": 4, "high": 24, "normal": 72, "low": 168}

ASSET_KINDS = ["marketing_image", "datasheet", "manual", "certificate", "drawing"]
BLOCKED = ["none", "quote", "order", "all"]


def shipment_event(at: str, status: str, location: str = "", description: str = "") -> dict:
    """把场景 / 种子里的事件统一成 {at, status_code, status_text, location, description}；status 可以是状态码或中文。"""
    if status in SHIPMENT_STATUS:
        code, text = status, SHIPMENT_STATUS[status]
    elif status in SHIPMENT_STATUS_BY_TEXT:
        code, text = SHIPMENT_STATUS_BY_TEXT[status], status
    else:
        code, text = "in_transit", status
    return {"at": at, "status_code": code, "status_text": text, "location": location or "", "description": description or ""}
