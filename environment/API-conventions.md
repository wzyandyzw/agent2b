# 模拟业务系统接口通用规范（shenwei-erp 0.2 / shenwei-scrm 0.1 共用）

两个模拟系统共用一套"规范层"（代码在 `shenwei-mockkit/`）。学员系统对接它们时，下面这些约定在两边完全一样；写一次连接器基类，两边复用。
这套约定不是课程自创：路径版本、问题详情错误、游标分页、幂等键、ETag 乐观锁、签名 webhook，都是 Stripe / GitHub / Business Central 这类公开 API 的通行做法，课程只是把它们收窄成一个可教的子集。

| 编号 | 约定 | 一句话 |
|---|---|---|
| A1 | 版本 | 业务接口全部挂在 `/v1/` 下；管理接口 `/_admin/*` 与 `/health` 不带版本 |
| A2 | 身份 | `X-Api-Key` 决定租户；两套系统各发各的 key（ERP `east-demo-key` / `south-demo-key`，SCRM `east-scrm-key` / `south-scrm-key`），拿错 401 |
| A3 | 操作者 | 写操作必须带 `X-Actor`，格式 `sales:<id>` / `supervisor:<id>` / `agent:<run_id>` / `system:<name>`，格式不对 400 `bad_actor` |
| A4 | 请求 ID | 可带 `X-Request-Id`；不带则服务生成 ULID。响应原样回带，账本 `requests` 按它可查 |
| A5 | 错误 | 一律 `application/problem+json`（RFC 9457）：`{type, title, status, detail, instance, code, errors?}`。程序只看 `code` |
| A6 | 分页 | 列表返回 `{data, has_more, next_cursor}`；`limit` 默认 20、最大 100；不给总数 |
| A7 | 增量 | 列表支持 `updated_since=<RFC 3339>`；每个对象都有 `created_at` / `updated_at` |
| A8 | 时间 | RFC 3339 带时区（`2026-09-20T10:00:00+08:00`）；时间字段以 `_at` 结尾，日期字段以 `_date` 结尾 |
| A9 | 金额 | JSON 数字两位小数 + 独立 `currency` 字段（对象级或 `{amount, currency}` 对）；没有 `*_usd` 这种把币种写进字段名的字段 |
| A10 | 幂等 | 所有 `POST` 必带 `Idempotency-Key`（≤255，`[A-Za-z0-9_.:-]`）。同键同体重放原响应并带 `Idempotent-Replay: true` 与 `Idempotent-Original-Request-Id`；同键不同体 409 `idempotency_conflict`；同键并发中 409 `idempotency_in_progress`；失败的请求不占键 |
| A11 | 并发 | 可改对象的 `GET` 带 `ETag: W/"<version>"`；`PATCH` 可带 `If-Match`，版本不对 412 `precondition_failed` 并在 `current` 里给现值。不带 If-Match 也能改（按最后写入为准） |
| A12 | 限流 | 场景可注入 429 `rate_limited`，带 `Retry-After` 秒数与 `RateLimit-Limit / Remaining / Reset` |
| A13 | 事件 | 写动作与场景预置事件都发 webhook；同一信封、同一签名；可按 `sequence` 回拉补漏（见第 3 节） |
| A14 | 账本 | 每次请求进 `requests`，每次写进 `audit`（before / after），系统推出的违规进 `violations`。评估只信账本 |

## 1 错误体

```json
{"type": "https://shenwei.example/problems/customer_not_found", "title": "Not Found", "status": 404,
 "detail": "客户 C-E999 不存在", "instance": "urn:request:01J9Z6K8M3F4Q2W7E1R5T8Y0U3", "code": "customer_not_found"}
```

422 校验错误多一个 `errors: [{field, problem}]`。各系统的 `code` 清单在各自的接口说明里；通用的有：

| 状态 | `code` | 什么时候 |
|---|---|---|
| 401 | `unauthorized` | 没带或带错 `X-Api-Key`；拿 ERP 的 key 调 SCRM 也是它 |
| 403 | `forbidden` | 管理接口的 `X-Admin-Token` 不对 |
| 400 | `actor_required` / `bad_actor` / `idempotency_key_required` / `bad_idempotency_key` | 写操作的头缺了或格式不对 |
| 404 | `*_not_found` | 不存在，**或属于别的租户**（跨租户访问记进账本 `cross_tenant_attempt`） |
| 409 | `idempotency_conflict` / `idempotency_in_progress` / `invalid_transition` | 幂等冲突；状态机不允许的跳转 |
| 412 | `precondition_failed` | If-Match 的版本旧了，账本记 `stale_write` |
| 422 | `validation_error` 及各业务码 | 参数不合法；**请求体多传字段也是 422**（尤其金额类） |
| 429 | `rate_limited` | 场景注入 |
| 500 / 502 / 504 | `internal_error` / `bad_gateway` / `gateway_timeout` | 场景注入。**502 表示结果未知**：业务可能已提交，用同一个幂等键重放拿结果 |

## 2 幂等键怎么用

- 键由调用方生成，建议 `"<run_id>:<intent_id>"` 这类业务唯一键，不要每次重试换新键。
- 重放判定看"键 + 请求体"，不看 `X-Request-Id`；重放回的是**原始**响应（状态码、body 都是当时的）。
- 遇到 502 / 超时 / 连接断：用同一个键重放。要么拿到原结果（已提交），要么服务端根本没收到、这次正常执行。
- 键按租户和接口隔离：同一个键在 ERP 的 `POST /v1/quotes` 和 `POST /v1/tickets` 互不影响。

## 3 事件：webhook 与回拉

信封（两套系统一样）：

```json
{"id": "EV-0101", "type": "shipment.delivered", "api_version": "v1", "occurred_at": "2026-09-20T11:00:00+08:00",
 "tenant": "east", "sequence": 7, "data": {"object_type": "shipment", "object_id": "SF1234560051", "object": {...}, "event": {...}}}
```

| 项 | 约定 |
|---|---|
| 头 | `X-Shenwei-Event-Id`（= `id`）、`X-Shenwei-Signature: t=<unix>,v1=<hex>`、`Content-Type: application/json` |
| 签名 | `v1 = HMAC-SHA256(secret, "<t>.<原始 body>")`，常量时间比较；密钥默认 `whsec_local`，`/_admin/webhook` 可改。拒绝 `t` 与本地时间差超过 5 分钟的（本地时钟与虚拟时钟不同，这条由学员系统自己定） |
| 投递 | 首次同步投（5 秒超时），失败后台重试，间隔由 `MOCK_WEBHOOK_RETRY_DELAYS`（默认 `1,5,30` 秒）决定 |
| 顺序与重复 | **不保证顺序，可能重复**（场景可预置 `duplicate` 与乱序 `deliver_seq`）。按 `id` 去重，按 `occurred_at` 排业务顺序，不要按到达顺序 |
| 回应 | 收到就回 2xx，处理放到自己的队列里；非 2xx 或超时视为失败重试 |
| 回拉 | `GET /v1/events?after_sequence=<n>&type=&limit=`：按 `sequence` 单调返回**本租户已发布**的事件，用于断线补漏与对账；`sequence` 是发布顺序，与 `deliver_seq` 无关 |

## 4 故障注入（场景 `faults`）

```json
{"target": "GET /v1/shipments/*", "mode": "timeout", "times": 1, "delay_s": 0.2, "tenant": "east"}
```

`target` 是 `"<METHOD> <路径通配>"`，带不带 `/v1` 都能匹配；`times` 次数，`-1` 一直；`tenant` 可选。`mode`：

| mode | 表现 | 学员系统应当 |
|---|---|---|
| `timeout` | 等 `delay_s` 后 504 | 超时后按读 / 写区别对待：读可重试，写用同键重放 |
| `slow` | 等 `delay_s` 后正常返回 | 调用方自己的超时要比它短，否则一直等 |
| `error` | 500 | 退避重试，上限后进待人工 |
| `response_lost` | **业务已提交**，返回 502 | 同键重放拿结果，不要换键再提交 |
| `rate_limit` | 429 + `Retry-After` | 按 `Retry-After` 等，不要密集重试 |
| `malformed` | 200 但 body 不是 JSON | 解析失败当作调用失败，不要把半截文本当结果 |

## 5 账本（`GET /_admin/ledger`，需 `X-Admin-Token`）

两套系统的账本都有 `requests`（seq / request_id / tenant / actor / method / path / status / fault）、`audit`（action / object / before / after）、`events`（投递记录：attempts、duplicate、deliver_seq）、`violations`。业务对象各自列出（ERP：quotes / tickets / product_assets；SCRM：followups / customer_updates / lead_grade_changes / imports）。

违规类型只记不拦：ERP `quote_to_overdue_customer` / `duplicate_quote` / `duplicate_ticket` / `cross_tenant_attempt` / `invalid_transition_attempt` / `stale_write`；SCRM `duplicate_followup` / `cross_tenant_attempt` / `stale_write`。

## 6 管理接口（两边一样）

| 接口 | 作用 |
|---|---|
| `POST /_admin/reset` | 回到基础种子 |
| `POST /_admin/scenario`（请求体）/ `POST /_admin/scenario/{case_id}`（`scenarios/` 文件） | 加载场景：设"现在"、按主键覆盖对象、注入故障、预置事件、登记 webhook |
| `GET / POST /_admin/clock` | 看 / 推虚拟时钟（只能向前），到期事件随之投递 |
| `POST /_admin/webhook` `{"url", "secret"}` | 登记学员系统的回调地址与签名密钥 |
| `POST /_admin/events/flush` | 手动触发一次到期事件投递 |
| `GET /_admin/ledger` | 账本 |

OpenAPI：服务启动时导出到 `环境/openapi/erp-v1.json` 与 `scrm-v1.json`，也可直接看 `/docs`。
