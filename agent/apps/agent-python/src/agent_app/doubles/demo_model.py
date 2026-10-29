"""Deterministic planner/formatter for the offline CLI demo.

It exercises the same AgentLoop and ToolExecutor as a real model. It is not a
replacement for model-driven free-form planning; it makes the demo runnable
without credentials and keeps every factual statement tied to tool output.
"""
from __future__ import annotations

import json
import re

from agent_app.contracts import ModelResponse, ResponseKind, ToolCall, ToolSpec, Usage


class OfflineDemoModel:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, messages: list[dict], tools: list[ToolSpec], *, timeout_s: float = 0.0) -> ModelResponse:
        del timeout_s
        self.calls += 1
        prompt = next((m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), "")
        results, errors = self._tool_results(messages)
        intent = self._intent(prompt)

        if intent == "customer":
            order_id = self._first(r"(ORD-\d+)", prompt, "ORD-10086")
            if "get_order" not in results and "get_order" not in errors:
                return self._calls(("get_order", {"order_id": order_id}))
            order = results.get("get_order")
            if not order:
                return self._final(f"订单 {order_id} 无法读取：{errors.get('get_order', '未知错误')}。")
            customer_id = order.get("customer_id")
            remaining = [
                ("get_customer", {"customer_id": customer_id}),
                ("get_receivables", {"customer_id": customer_id}),
            ]
            shipments = order.get("shipments") or []
            if shipments:
                remaining.append(("get_shipment", {"tracking_no": shipments[0]}))
            if any(name not in results and name not in errors for name, _ in remaining):
                return self._calls(*remaining)
            return self._final(self._customer_summary(order, results, errors))

        if intent == "delivery":
            order_id = self._first(r"(ORD-\d+)", prompt, "ORD-10086")
            if "get_order" not in results and "get_order" not in errors:
                return self._calls(("get_order", {"order_id": order_id}))
            order = results.get("get_order")
            if not order:
                return self._final(f"订单 {order_id} 无法读取：{errors.get('get_order', '未知错误')}。")
            shipment_id = self._first(r"(SF\d+)", prompt, (order.get("shipments") or [""])[0])
            if shipment_id and "get_shipment" not in results and "get_shipment" not in errors:
                return self._calls(("get_shipment", {"tracking_no": shipment_id}))
            return self._final(self._delivery_summary(order, results, errors))

        if intent == "finance":
            customer_id = self._first(r"(C-E\d+)", prompt, "C-E003")
            if "get_customer" not in results and "get_customer" not in errors:
                return self._calls(
                    ("get_customer", {"customer_id": customer_id}),
                    ("get_receivables", {"customer_id": customer_id}),
                )
            return self._final(self._finance_summary(customer_id, results, errors))

        if intent == "quote":
            customer_id = self._first(r"(C-E\d+)", prompt, "C-E001")
            sku = self._first(r"\b((?:X|T|S|FL)\d+(?:-Pro)?)\b", prompt, "X200-Pro")
            qty = int(self._first(r"(?:数量\s*|qty\s*)?(\d+)\s*(?:台|套|EA)", prompt, "2"))
            if "search_products" not in results and "search_products" not in errors:
                return self._calls(
                    ("search_products", {"category": "X", "flow_lpm": 6, "pressure_bar": 2}),
                    ("get_customer", {"customer_id": customer_id}),
                    ("price_quote", {"customer_id": customer_id, "lines": f"{sku}:{qty}"}),
                )
            return self._final(self._quote_summary(results, errors))

        if intent == "management":
            if "list_orders" not in results and "list_orders" not in errors:
                return self._calls(("list_orders", {"status": "shipped", "limit": 20}))
            summary = self._management_summary(results, errors)
            if "保存" in prompt or "报告" in prompt:
                if "save_report" not in results and "save_report" not in errors:
                    return self._calls(("save_report", {"filename": "weekly-summary.md", "content": summary}))
                saved = results.get("save_report")
                if saved:
                    summary += f"\n\n报告已保存：{saved.get('path')}"
                else:
                    summary += f"\n\n报告保存失败：{errors.get('save_report', '未知错误')}"
            return self._final(summary)

        if intent == "product":
            sku = self._first(r"\b((?:X|T|S|FL)\d+(?:-Pro)?)\b", prompt, "X200")
            qty = int(self._first(r"(\d+)\s*(?:台|套|EA)", prompt, "1"))
            if "get_product_spec" not in results and "get_product_spec" not in errors:
                return self._calls(
                    ("get_product_spec", {"model": sku}),
                    ("get_availability", {"model": sku, "qty": qty}),
                )
            return self._final(self._product_summary(results, errors))

        query = prompt or "公司产品"
        if "search_knowledge" not in results and "search_knowledge" not in errors:
            return self._calls(("search_knowledge", {"query": query, "limit": 3}))
        return self._final(self._knowledge_summary(results, errors, query))

    def _tool_results(self, messages: list[dict]) -> tuple[dict[str, dict], dict[str, str]]:
        results: dict[str, dict] = {}
        errors: dict[str, str] = {}
        for message in messages:
            if message.get("role") != "tool":
                continue
            name = message.get("name") or "unknown"
            try:
                body = json.loads(message.get("content") or "{}")
            except json.JSONDecodeError:
                errors[name] = "工具结果格式异常"
                continue
            if body.get("ok"):
                results[name] = body.get("data") or {}
            else:
                errors[name] = (body.get("error") or {}).get("message", "工具执行失败")
        return results, errors

    def _intent(self, prompt: str) -> str:
        if (
            any(word in prompt for word in ("客户全景", "客户风险", "客户情况"))
            or ("客户" in prompt and "回款" in prompt)
            or ("客户" in prompt and "物流" in prompt and "订单" in prompt)
        ):
            return "customer"
        if any(word in prompt for word in ("周报", "经营", "异常汇总")):
            return "management"
        if any(word in prompt for word in ("延误", "物流", "签收", "发货")):
            return "delivery"
        if any(word in prompt for word in ("应收", "回款", "逾期", "账龄")):
            return "finance"
        if any(word in prompt for word in ("报价", "价格", "选型")):
            return "quote"
        if any(word in prompt for word in ("库存", "交期", "规格")):
            return "product"
        return "knowledge"

    def _calls(self, *pairs: tuple[str, dict]) -> ModelResponse:
        calls = [
            ToolCall(call_id=f"demo_{self.calls}_{index}", name=name, arguments=json.dumps(args, ensure_ascii=False))
            for index, (name, args) in enumerate(pairs, 1)
        ]
        return ModelResponse(ResponseKind.TOOL_CALLS, tool_calls=calls, usage=Usage(0, 0, 0), raw={"demo": True})

    def _final(self, text: str) -> ModelResponse:
        return ModelResponse(ResponseKind.FINAL, text=text, usage=Usage(0, 0, 0), raw={"demo": True})

    def _first(self, pattern: str, text: str, default: str) -> str:
        match = re.search(pattern, text, re.IGNORECASE)
        return match.group(1) if match else default

    def _customer_summary(self, order: dict, results: dict, errors: dict) -> str:
        customer = results.get("get_customer", {})
        receivables = results.get("get_receivables", {})
        shipment = results.get("get_shipment", {})
        events = shipment.get("events") or []
        last_event = events[-1] if events else {}
        credit = customer.get("credit", {})
        lines = [
            "## 客户全景与风险",
            f"- 客户：{customer.get('name') or order.get('customer_name')}（{customer.get('country', '')} {customer.get('city', '')}）",
            f"- 重点订单：{order.get('order_id')}，状态 {order.get('status')}，承诺送达 {order.get('promised_delivery_date')}，金额 {order.get('total_amount')} {order.get('currency')}",
        ]
        if shipment:
            sign_text = "已签收" if shipment.get("signed") else "未签收"
            lines.append(
                f"- 物流：{shipment.get('status_text')}（{sign_text}），最后更新 {shipment.get('last_event_at')}，位置 {last_event.get('location', '未知')}"
            )
            if not shipment.get("signed") and order.get("promised_delivery_date") and str(shipment.get("last_event_at", ""))[:10] > order["promised_delivery_date"]:
                lines.append("- 风险：已超过承诺送达日且尚未签收，需要优先跟进承运商和客户签收。")
        if receivables:
            lines.append(
                f"- 财务：应收 {receivables.get('ar_balance')} {receivables.get('currency')}，逾期 {receivables.get('overdue_days')} 天，信用状态 {receivables.get('credit_status')}。"
            )
        lines.append(
            f"- 信用：额度 {credit.get('credit_limit')}，已占用 {credit.get('exposure')}，可用 {credit.get('available_credit')}。"
        )
        for name, error in errors.items():
            lines.append(f"- 未能读取 {name}：{error}")
        lines.append("- 建议动作：今天向物流确认末端派送与签收，同时将结果回写客户跟进。")
        return "\n".join(lines)

    def _delivery_summary(self, order: dict, results: dict, errors: dict) -> str:
        shipment = results.get("get_shipment", {})
        events = shipment.get("events") or []
        last = events[-1] if events else {}
        text = [
            f"订单 {order.get('order_id')} 当前状态为 **{order.get('status')}**，承诺送达 **{order.get('promised_delivery_date')}**。",
            f"物流状态：**{shipment.get('status_text', '无法确认')}**，{'已签收' if shipment.get('signed') else '尚未签收'}。",
            f"最后轨迹：{last.get('at', '无')}，{last.get('location', '无位置')}，{last.get('description', '') or last.get('status_text', '')}。",
        ]
        if not shipment.get("signed") and order.get("promised_delivery_date") and str(last.get("at", ""))[:10] > order["promised_delivery_date"]:
            text.append("该订单已超过承诺送达日且未签收，建议立即联系物流并准备客户说明。")
        for name, error in errors.items():
            text.append(f"{name} 读取失败：{error}。")
        return "\n\n".join(text)

    def _finance_summary(self, customer_id: str, results: dict, errors: dict) -> str:
        customer = results.get("get_customer", {})
        r = results.get("get_receivables", {})
        if not r:
            return f"客户 {customer_id} 的应收信息无法确认：{errors.get('get_receivables', '未知错误')}。"
        return "\n".join([
            f"## {customer.get('name', customer_id)} 回款风险",
            f"- 应收余额：{r.get('ar_balance')} {r.get('currency')}",
            f"- 逾期金额：{r.get('overdue_amount')}，逾期 {r.get('overdue_days')} 天",
            f"- 信用状态：{r.get('credit_status')}；占用额度 {r.get('exposure')} / {r.get('credit_limit')}",
            f"- 未清项目：{len(r.get('open_items') or [])} 笔",
            "- 建议：先与销售确认争议或验收状态，再安排催收；新的赊销报价需人工判断。",
        ])

    def _quote_summary(self, results: dict, errors: dict) -> str:
        products = results.get("search_products", {})
        quote = results.get("price_quote", {})
        customer = results.get("get_customer", {})
        candidates = [c for c in products.get("candidates", []) if c.get("meets_all")]
        lines = ["## 售前选型与报价草稿"]
        if candidates:
            names = "、".join(f"{c.get('sku')}（{c.get('name')}）" for c in candidates)
            lines.append(f"- 按当前工况，满足条件的候选型号：{names}。")
        if quote:
            lines.append(f"- 客户：{customer.get('name', quote.get('customer_id'))}")
            for line in quote.get("lines", []):
                lines.append(
                    f"- {line.get('sku')} × {line.get('qty')}：{line.get('unit_price')} USD/台，小计 {line.get('amount')} USD"
                )
            lines.append(f"- 合计：**{quote.get('total_amount')} {quote.get('currency')}**；付款条件：{quote.get('payment_terms')}")
            lines.append(f"- 价格依据：{quote.get('price_rule_ref')}；报价有效期规则以 ERP 返回为准。")
        for name, error in errors.items():
            lines.append(f"- {name} 失败：{error}")
        lines.append("- 状态：这是只计算未落账的草稿，发送客户前必须由业务负责人确认。")
        return "\n".join(lines)

    def _management_summary(self, results: dict, errors: dict) -> str:
        data = results.get("list_orders", {})
        orders = data.get("orders", [])
        lines = [f"## 经营异常摘要", f"- 已发货未完成订单：{data.get('count', 0)} 笔"]
        for order in orders[:5]:
            lines.append(
                f"- {order.get('order_id')}｜{order.get('customer_name')}｜承诺 {order.get('promised_delivery_date')}｜{order.get('status')}｜{order.get('total_amount')} {order.get('currency')}"
            )
        if data.get("has_more"):
            lines.append("- 结果仍有更多记录，建议按客户或日期继续细分。")
        for name, error in errors.items():
            lines.append(f"- {name} 失败：{error}")
        return "\n".join(lines)

    def _product_summary(self, results: dict, errors: dict) -> str:
        product = results.get("get_product_spec", {})
        availability = results.get("get_availability", {})
        lines = [
            f"## {product.get('model', '产品')}",
            f"- 名称：{product.get('name') or product.get('name_en', '未知')}",
            f"- 规格：{product.get('key_spec', '未提供')}",
            f"- 手册/版本：{product.get('doc_ref', '未提供')} / {product.get('source_version', '未提供')}",
        ]
        if availability:
            lines.append(
                f"- 可用库存：{availability.get('available')}；最早发运 {availability.get('earliest_ship_date')}；依据：{availability.get('basis_text')}"
            )
            lines.append(f"- 库存观测时间：{availability.get('observed_at')}")
        for name, error in errors.items():
            lines.append(f"- {name} 失败：{error}")
        return "\n".join(lines)

    def _knowledge_summary(self, results: dict, errors: dict, query: str) -> str:
        data = results.get("search_knowledge", {})
        hits = data.get("results", [])
        lines = [f"## 知识检索：{query}"]
        if not hits:
            lines.append("知识库中没有找到足够相关的资料。")
        for hit in hits:
            lines.append(f"- [{hit.get('source')}] {hit.get('excerpt')}")
        for name, error in errors.items():
            lines.append(f"- {name} 失败：{error}")
        return "\n".join(lines)
