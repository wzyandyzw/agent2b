import json

import httpx

from agent_app.contracts import ToolCall
from agent_app.tools import ToolExecutor, ToolRegistry
from agent_app.tools.customer import GetCustomer, GetReceivables
from agent_app.tools.erp_client import ErpClient
from agent_app.tools.knowledge import SearchKnowledge
from agent_app.tools.order import ListOrders
from agent_app.tools.quote import PriceQuote
from agent_app.tools.report import SaveReport


def _call(name: str, args: dict) -> ToolCall:
    return ToolCall(call_id="call_1", name=name, arguments=json.dumps(args))


def test_customer_and_receivables_tools_are_available():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/receivables"):
            return httpx.Response(200, json={"customer_id": "C-E003", "overdue_days": 23, "ar_balance": 18640.0})
        return httpx.Response(200, json={
            "id": "C-E003",
            "legal_name": "Rheinwerk Anlagenbau GmbH",
            "country_code": "DE",
            "city": "Düsseldorf",
            "contacts": [],
            "credit": {"credit_limit": 50000.0},
        })

    erp = ErpClient("http://erp.test", "key", transport=httpx.MockTransport(handler))
    registry = ToolRegistry([GetCustomer(erp), GetReceivables(erp)])
    executor = ToolExecutor(registry)

    customer = executor.execute(_call("get_customer", {"customer_id": "C-E003"}), timeout_s=1)
    receivable = executor.execute(_call("get_receivables", {"customer_id": "C-E003"}), timeout_s=1)

    assert customer.ok is True
    assert customer.data["name"] == "Rheinwerk Anlagenbau GmbH"
    assert receivable.ok is True
    assert receivable.data["overdue_days"] == 23


def test_quote_tool_returns_erp_calculated_amount_only():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/quotes/price"
        assert request.url.params["lines"] == "X200-Pro:2"
        return httpx.Response(200, json={
            "customer_id": "C-E001",
            "lines": [{"sku": "X200-Pro", "qty": 2, "unit_price": 425.61, "amount": 851.22}],
            "total_amount": 851.22,
            "currency": "USD",
            "recorded": False,
        })

    erp = ErpClient("http://erp.test", "key", transport=httpx.MockTransport(handler))
    result = ToolExecutor(ToolRegistry([PriceQuote(erp)])).execute(
        _call("price_quote", {"customer_id": "C-E001", "lines": "X200-Pro:2"}),
        timeout_s=1,
    )
    assert result.ok is True
    assert result.data["total_amount"] == 851.22
    assert result.data["recorded"] is False


def test_list_orders_passes_filters():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["status"] == "shipped"
        assert request.url.params["limit"] == "5"
        return httpx.Response(200, json={"data": [{"id": "ORD-10086", "status": "shipped"}]})

    erp = ErpClient("http://erp.test", "key", transport=httpx.MockTransport(handler))
    result = ToolExecutor(ToolRegistry([ListOrders(erp)])).execute(
        _call("list_orders", {"status": "shipped", "limit": 5}),
        timeout_s=1,
    )
    assert result.ok is True and result.data["orders"][0]["order_id"] == "ORD-10086"


def test_knowledge_search_returns_source(tmp_path):
    (tmp_path / "policy.md").write_text(
        "# 政策\n\n报价必须由业务系统计算，对外发送前由负责人确认。", encoding="utf-8"
    )
    result = ToolExecutor(ToolRegistry([SearchKnowledge(tmp_path)])).execute(
        _call("search_knowledge", {"query": "报价 确认"}),
        timeout_s=1,
    )
    assert result.ok is True
    assert result.data["results"][0]["source"] == "policy.md"


def test_report_tool_rejects_path_traversal(tmp_path):
    result = ToolExecutor(ToolRegistry([SaveReport(tmp_path)])).execute(
        _call("save_report", {"filename": "../secret.md", "content": "x"}),
        timeout_s=1,
    )
    assert result.ok is False
    assert result.error.category == "input_error"
    assert not (tmp_path.parent / "secret.md").exists()
