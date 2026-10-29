---
spec: w01-shipment
week: W1
covers: [US-03 的物流部分]
---

# 周内新增 · get_shipment（查物流）

- 目标：按运单号返回物流最新状态与事件时间线。
- 输入：`tracking_no`（非空字符串）。
- 权威事实：ERP `GET /v1/shipments/{tracking_no}`。
- 输出：tracking_no、order_id、carrier、status_code、status_text、last_event_at、events[]。
- 缺信息：运单号为空 → 不调 ERP，返回输入错误。
- 上游失败：404 → 业务无数据（`shipment_not_found`）；超时 → timeout。
- 设计检验：理想变化集中在工具实现、注册、Schema、测试、文档；Loop 不应出现 `if name == "get_shipment"`。
- 验收 T15：注册后可用；Loop 无业务特判；旧测试全过。
