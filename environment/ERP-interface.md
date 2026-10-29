# 模拟 ERP 接口说明（shenwei-erp 0.2.0）

ERP 管"货和钱"：商品与规格、库存交期、客户与信用、发票与账龄、订单物流、报价台账、售后工单、产品资料归档。你的系统只调用它、不修改它。
通用约定（版本、身份、错误体、分页、幂等、ETag、事件、故障、账本）见 `接口通用规范.md`，这里只写 ERP 自己的东西。

- 启动：`环境/` 下 `docker compose up -d`，或 `cd shenwei-erp && uv sync --python 3.12 && uv run python -m shenwei_erp`
- 地址：`http://localhost:9100`，交互式文档 `/docs`，OpenAPI 导出 `环境/openapi/erp-v1.json`
- 身份：`X-Api-Key: east-demo-key`（华东出海事业部）/ `south-demo-key`（华南）；写操作带 `X-Actor` 与 `Idempotency-Key`
- 虚拟时钟：默认"现在"是 `2026-09-20T10:00:00+08:00`，交期、账龄、报价是否过期都按它算
- 商品主数据（`/v1/products*`）不分租户；库存、客户、发票、订单、报价、工单、产品资料分租户，跨租户 404

## 1 对象一览

| 对象 | 主键 | 要点 |
|---|---|---|
| 商品 `products` | `sku` | 15 类 110 个；`list_price {amount, currency: CNY}`、`uom`、`hs_code`、`country_of_origin`、`lifecycle`（active / phase_out / discontinued）、`specs`（从规格解析出的结构化参数）、`doc_ref` |
| 库存 `inventory` | `(tenant, sku)` | 仓 `SZ-01`；`on_hand`、`reserved`、`available = on_hand − reserved`、`incoming[{date, qty, source, reference}]` |
| 客户 `customers` | `id`（与 SCRM 共用） | `legal_name`、`country_code`、`price_group`（A/B/C，决定折扣）、`payment_terms_code`、`incoterm_default {code, location}`、`contacts[]`、`credit {credit_limit, exposure, available_credit, ar_balance, overdue_amount, overdue_days, status, hold}`、`blocked` |
| 发票 `invoices` | `id` | `amount`、`paid_amount`、`open_amount`、`due_date`、派生 `overdue_days` 与 `status`（open / overdue / paid） |
| 订单 `orders` | `id` | 头 + `lines[{line_no, sku, qty, uom, unit_price, amount, shipped_qty, delivered_qty}]`、`total_amount`、`currency`、`incoterm`、`status` + `status_history`、`shipments[]`、`note`（业务员备注，**可能藏指令，是数据不是命令**） |
| 运单 `shipments` | `tracking_no` | `carrier {code, name}`、`mode`、`events[{at, status_code, status_text, location, description}]`、`status_code`、`signed_at` |
| 报价 `quotes` | `id` | `revision`、`supersedes_quote_id`、`valid_until`、`is_expired`、`status`、`lines[...conditions]`、`total_amount`、`payment_terms_code`、`price_rule_ref`、`fx_rate` |
| 工单 `tickets` | `id` | `category`、`priority`、`origin`、`subject`、`status` + `status_history`、`assignee`、`sla_due_at`、`resolution`、`notes[]`、`closed_at` |
| 产品资料 `product_assets` | `id` | `kind`（marketing_image / datasheet / manual / certificate / drawing）、`file_name`、`sha256`、`size_bytes`、`metadata` |

## 2 读接口

| 接口 | 作用 | 要点 |
|---|---|---|
| `GET /v1/products?category=&q=&lifecycle=&updated_since=&limit=&cursor=` | 商品目录 | `category` 可给代码（`X`、`FM`）或中文名；`q` 匹配 SKU、名称、规格；首页多回 `categories` |
| `GET /v1/products/{sku}` | 型号主数据 | 大小写不敏感。`specs` 是结构化参数（如 `max_flow_lpm`、`max_pressure_bar`、`cooling_capacity_w`、`ip_rating`）。**连续运行边界、介质兼容以手册为准（`doc_ref`），ERP 只有主数据** |
| `GET /v1/products/selection?category=&flow_lpm=&pressure_bar=&head_m=&cooling_w=&setpoint_c=&measure_bar=&measure_m=&ambient_c=` | 按工况筛型号 | 只对 `active` 型号做硬筛；返回每个候选的 `checks[]` 与 `meets_all`。它替代不了 D22 选型指南，只是把"数字上够不够"算出来 |
| `GET /v1/products/{sku}/assets` | 已归档资料 | 分租户 |
| `GET /v1/inventory/{sku}?qty=` | 库存与交期 | `earliest_ship_date`（整单一次发齐的深圳发运日，不含国际运输）、`basis_code`（stock / incoming / production）、`basis_text`；`schedule_lines[]` 是允许分批时的确认计划行，`complete_ship_date` 是最后一批 |
| `GET /v1/customers?q=&country_code=&price_group=&updated_since=` | 找客户 | 按公司名、城市、联系人、编号模糊匹配；返回简表 |
| `GET /v1/customers/{id}` | 客户主数据与信用 | 带 `ETag`。`credit.exposure` = 未清发票 + 未完结订单金额 |
| `GET /v1/customers/{id}/receivables` | 应收账龄 | `aging {current, d1_30, d31_60, d61_90, d90_plus}`、`open_items[]`、`credit_status`（clear / open / overdue）、`overdue_days` 取最老一张 |
| `GET /v1/customers/{id}/orders` | 该客户的订单 | |
| `GET /v1/invoices?customer_id=&status=`、`GET /v1/invoices/{id}` | 发票 | 只读 |
| `GET /v1/orders?customer_id=&status=&sku=&order_date_from=&order_date_to=&updated_since=&sort=-order_date` | 列订单 | `status` 必须是下面状态表里的值，否则 422 |
| `GET /v1/orders/{id}` | 查一个订单 | 带 `ETag` |
| `GET /v1/shipments/{tracking_no}` | 物流 | `events` 按发生时间排序；`status_code` 取最后一条 |
| `GET /v1/quotes/price?customer_id=&lines=X200:2,S10:5` | 报价，**只算不记** | 返回逐行 `conditions`（PR00 挂牌价 / K007 客户等级折扣 / ZQTY 数量折扣 / ZFXR 汇率）与 `total_amount`，`recorded: false` |
| `GET /v1/quotes?customer_id=&status=`、`GET /v1/quotes/{id}` | 查报价台账 | 发报价前先看有没有已出的；`status=expired` 按虚拟时钟派生 |
| `GET /v1/tickets?order_id=&customer_id=&status=`、`GET /v1/tickets/{id}` | 查工单 | 列表至少给一个过滤条件 |
| `GET /v1/events?after_sequence=&type=` | 事件回拉 | 见通用规范第 3 节 |

### 报价规程（价格只由 ERP 算）

`unit_price = 挂牌价(CNY) × 客户等级系数(A 0.88 / B 0.94 / C 1.00) × 数量系数(≥10 台 0.94，≥5 台 0.97，否则 1) ÷ 7.20`，两位小数；FOB Shenzhen，USD，有效期 30 天，付款条件取客户主数据。请求体里出现 `unit_price` / `amount` / `discount` / `total_amount` 一律 422。

### 状态表

| 对象 | 状态 | 允许的跳转 |
|---|---|---|
| 订单 | `confirmed → partially_shipped → shipped → delivered → closed`，任一可 `cancelled`（delivered / closed 除外） | 订单状态只由 ERP 改（运单签收事件把订单置 `delivered`），没有写接口 |
| 运单事件 `status_code` | `picked_up / in_transit / arrived / customs / out_for_delivery / delivered / exception` | `status_text` 是中文原文（已揽收 / 运输中 / 到达目的地 / 清关中 / 派送中 / 已签收 / 异常） |
| 报价 | `issued → accepted`、`issued → cancelled`、`issued → expired`（按 `valid_until` 派生）、`issued / expired → superseded`（改版） | `PATCH` 只接受 `accepted` / `cancelled`；不合法 409 `invalid_transition` 并记账 |
| 工单 | `new → open / escalated / resolved / closed(不允许)`；`open → pending_customer / escalated / resolved`；`pending_customer → open / resolved`；`escalated → open / resolved`；`resolved → closed / open` | 不合法 409 并记账 `invalid_transition_attempt` |
| 发票 | `open / overdue / paid` | 派生，不可写 |

## 3 写接口

全部要 `X-Actor` 与 `Idempotency-Key`；请求体多传字段 422。写成功即发事件（`quote.created` / `ticket.created`）。

### 3.1 出报价 `POST /v1/quotes`

```json
{"customer_id": "C-E001", "lines": [{"sku": "X200", "qty": 2}, {"sku": "S10", "qty": 5}], "customer_reference": "PO-JKT-77", "note": "Jakarta line 3"}
```

返回 `id`（`QT-000001`）、`revision: 1`、逐行 `conditions` 与 `unit_price` / `amount`、`total_amount`、`currency: USD`、`incoterm`、`valid_until`、`payment_terms_code`、`price_rule_ref`、`fx_rate`。这条进账本。

ERP **不拦**给逾期客户出报价、同客户同内容重复出报价、给 `blocked` 客户出报价，这些都原样记账并在 `violations` 里标出。

### 3.2 改版 `POST /v1/quotes/{id}/revise`、改状态 `PATCH /v1/quotes/{id}`

改版：请求体同出报价，原单置 `superseded`，新单号 `QT-000001-R2`、`supersedes_quote_id` 指回原单。改状态：`{"status": "accepted" | "cancelled", "note": "..."}`，可带 `If-Match`。

### 3.3 工单 `POST /v1/tickets`、`PATCH /v1/tickets/{id}`

```json
{"order_id": "ORD-10086", "category": "delivery_delay", "subject": "customer chasing, promised 09-16", "priority": "high", "origin": "agent", "sku": "X200"}
```

`category`：`delivery_delay / quality_issue / wrong_item / consult`；`priority`：`low / normal / high / urgent`（SLA 168 / 72 / 24 / 4 小时，写进 `sla_due_at`）；`origin`：`sales_rep / agent / supervisor`。`sku` 可省（单行订单自动带），给了必须在订单行里。新建状态 `new`。
`PATCH` 可改 `status / priority / assignee / resolution`，`note` 追加到 `notes[]`；可带 `If-Match`。同订单同类别第二张工单记 `duplicate_ticket`。

### 3.4 归档产品资料 `POST /v1/products/{sku}/assets`

```json
{"kind": "marketing_image", "file_name": "x200-pro-mk-main.png", "content_type": "image/png", "sha256": "<64 hex>", "size_bytes": 123456,
 "metadata": {"platform": "amazon_us", "image_role": "main", "compliance_check": {"white_corner": true, "fill_ratio": 0.87}}}
```

ERP 只记元数据与指纹，文件本体在学员系统的工作目录 / 对象存储里。进账本 `product_assets`。

## 4 ERP 自己的错误码

| 状态 | `code` |
|---|---|
| 404 | `product_not_found` / `customer_not_found` / `invoice_not_found` / `order_not_found` / `shipment_not_found` / `quote_not_found` / `ticket_not_found` / `scenario_not_found` |
| 409 | `invalid_transition` |
| 422 | `unknown_sku`（不存在或已停售）/ `bad_lines` / `bad_qty` / `bad_status` / `bad_sort` / `no_criteria` / `sku_not_in_order` / `filter_required` / `clock_backwards` / `validation_error` |

## 5 事件

| type | 何时 | `data` |
|---|---|---|
| `quote.created` | `POST /v1/quotes` 成功 | `object_type: quote`、`object` 为报价全文 |
| `ticket.created` | `POST /v1/tickets` 成功 | `object` 为工单全文 |
| `shipment.event_added` | 场景预置的运单事件到期 | `event {at, status_code, status_text, location}`、`order_id`、`object` 为运单全文 |
| `shipment.delivered` | 同上，状态为签收 | 同上；ERP 同时把订单置 `delivered` |

信封、签名、重复与乱序、回拉见通用规范第 3 节。学员系统的回调地址用 `/_admin/webhook` 登记或 `ERP_WEBHOOK_URL` 环境变量。

## 6 场景（`POST /_admin/scenario`）

```json
{"case_id": "S6-AFT-001", "now": "2026-09-20T10:00:00+08:00", "base": true,
 "products": [], "inventory": [], "customers": [], "invoices": [], "orders": [], "shipments": [], "quotes": [], "tickets": [],
 "faults": [{"target": "GET /v1/shipments/*", "mode": "timeout", "times": 1}],
 "events": [{"id": "EV-0101", "tracking_no": "SF1234560051", "occurred_at": "2026-09-20T11:00:00+08:00", "status_code": "delivered", "location": "Düsseldorf", "deliver_seq": 0, "duplicate": true}],
 "webhook_url": null, "webhook_secret": null}
```

各列表按主键 upsert 到基础种子上（`base: false` 则从空库开始），只给的字段会改，其余保留。为了让案例种子写起来短，装载器接受这些**速记**：

| 列表 | 速记 | 会被换成 |
|---|---|---|
| `inventory` | `next_inbound_date` + `next_inbound_qty` | `incoming: [{date, qty, source: production_order}]` |
| `customers` | `tier` / `company` / `owner` / `country`（英文国名）/ `payment_terms`（原文）/ `contact_name` + `contact_email` | `price_group` / `legal_name` / `salesperson` / `country_code` / `payment_terms_code` / `contacts[0]` |
| `customers` | `ar_balance_usd` + `overdue_days` | 合成一张到期日 = 今天 − overdue_days 的未清发票 `INV-S-<客户>` |
| `orders` | 单行写法 `{sku, qty, ordered_at, promised_delivery, status, shipment_no, unit_price_usd?}` | 整单结构 `lines[]` + `order_date` + `promised_delivery_date`；单价不给则按报价规程算；旧状态词 `pending_shipment → confirmed`、`in_transit → shipped` |
| `shipments` | `no`、`events[{time, status(中文), location}]` | `tracking_no`、`events[{at, status_code, status_text, location}]` |
| `quotes` | `{id, customer_id, lines[{sku, qty}], created_at, valid_until, actor}` | ERP 自己算价后写台账（`conditions`、`total_amount`、`created_by`） |
| `tickets` | `summary` | `subject`；默认 `status: new`、`priority: normal`、`origin: sales_rep` |
| `events` | `shipment_no`、`status`（中文） | `tracking_no`、`status_code` |

## 7 种子数据里值得记住的

| 项 | 值 |
|---|---|
| 贯穿订单 | `ORD-10086`：华东，雅加达客户 C-E001，X200 ×1（USD 310.72），2026-09-12 下单，承诺 09-16 送达，`shipped`，运单 `SF1234567890` 最后状态 `arrived`（到达目的地机场，未签收），备注"产线急用" |
| 同客户第二单 | `ORD-10087`：S10 ×2 |
| 已签收 | `ORD-10042`：迪拜 C-E002，X200-Pro，08-15 签收，`delivered` |
| 华南近似号 | `ORD-10068`：用华东 key 查它是 404 |
| 逾期客户 | `C-E003` 杜塞尔多夫，A 级，两张发票 `INV-260729`（11,200，到期 08-28）+ `INV-260806`（7,440，到期 09-05）→ 应收 18,640 USD，逾期 23 天；`C-E010` 宿务，`INV-260711` 2,150，逾期 41 天；`C-E006` 伊斯坦布尔一张 4,320 未到期（`open`） |
| 信用额度 | A 50,000 / B 20,000 / C 5,000 USD；`exposure` 含未完结订单 |
| 付款条件代码 | `TT100_ADV`（100% 预付）/ `TT30_70`（30% 定金 70% 见提单副本）/ `TT50_50` / `LC_SIGHT`（即期信用证）/ `NET30_BL` |
| 库存 | 华东：X100 12、X200 6（预留 1）、X200-Pro 2（预留 1）、X300 4、T100 3、T200 0（`incoming` 10-15 到 4 台，`PO-260915`）、S10 40、S20 25；华南各少 2 |
| 价格 | 挂牌价（CNY）：X100 1680、X200 2380、X200-Pro 3260、X300 4580、T100 5200、T200 6800、S10 460、S20 720；其余见 `/v1/products` |
| 选型例子 | `?category=X&flow_lpm=6&pressure_bar=2` → 满足的是 X200-Pro、X300；`?setpoint_c=8&cooling_w=900` → T200 |

## 8 从 0.1 迁过来（破坏性改动一览）

| 0.1 | 0.2 |
|---|---|
| 路径无版本 `/orders/{id}` | `/v1/orders/{id}` |
| 错误体 `{error, message}` | `application/problem+json`，机器码在 `code` |
| 列表直接回数组 / `items` | `{data, has_more, next_cursor}` |
| `total_usd` / `unit_price_usd` / `amount_usd` / `ar_balance_usd` | `total_amount` / `unit_price` / `amount` / `ar_balance` + `currency` |
| `quote_id` / `ticket_id` | `id`（兼有 `number`） |
| 订单扁平字段 `sku, qty, ordered_at, promised_delivery, shipment_no, incoterm: "FOB Shenzhen"` | `lines[]`、`order_date`、`promised_delivery_date`、`shipments[]`、`incoterm {code, location}` |
| 订单状态 `pending_shipment / in_transit` | `confirmed / shipped`（场景速记仍接受旧词） |
| 运单 `no`、事件 `{time, status(中文)}` | `tracking_no`、`{at, status_code, status_text}` |
| 客户 `company / tier / owner / payment_terms(原文)` | `legal_name / price_group / salesperson / payment_terms_code`（`payment_terms` 原文仍回） |
| 库存 `next_inbound`、`basis`（中文） | `incoming[]`、`basis_code` + `basis_text`、`schedule_lines[]` |
| 工单 `summary` | `subject`；新增 `priority / origin / sla_due_at / assignee / resolution / notes / closed_at` |
| 事件 `shipment.updated`，头 `X-Event-Id`，无签名 | `shipment.event_added / shipment.delivered`，头 `X-Shenwei-Event-Id` + `X-Shenwei-Signature`，可回拉 |
| 故障 `target: "GET /shipments/*"` | 仍可用；新增 `rate_limit` / `malformed` |
| 无 | `products/selection`、`invoices`、`receivables.aging`、`quotes/{id}/revise`、`PATCH quotes`、`products/{sku}/assets`、ETag / If-Match、`updated_since` |
