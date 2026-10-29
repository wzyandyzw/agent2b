import json

from agent_app.doubles.demo_model import OfflineDemoModel


def _tool(name: str, data: dict) -> dict:
    return {
        "role": "tool",
        "tool_call_id": f"call_{name}",
        "name": name,
        "content": json.dumps({"ok": True, "data": data}, ensure_ascii=False),
    }


def test_offline_customer_plan_and_grounded_summary():
    model = OfflineDemoModel()
    prompt = "汇总客户 C-E001 的重点订单、物流和回款风险"
    first = model.generate([{"role": "user", "content": prompt}], [])
    assert [call.name for call in first.tool_calls] == ["get_order"]
    assert first.tool_calls[0].arguments == '{"order_id": "ORD-10086"}'

    messages = [
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": ""},
        _tool("get_order", {
            "order_id": "ORD-10086",
            "customer_id": "C-E001",
            "customer_name": "PT Nusantara Process Engineering",
            "promised_delivery_date": "2026-09-16",
            "status": "shipped",
            "total_amount": 310.72,
            "currency": "USD",
            "shipments": ["SF1234567890"],
        }),
    ]
    second = model.generate(messages, [])
    assert {call.name for call in second.tool_calls} == {"get_customer", "get_receivables", "get_shipment"}

    messages.extend([
        {"role": "assistant", "content": ""},
        _tool("get_customer", {
            "name": "PT Nusantara Process Engineering",
            "country": "ID",
            "city": "Jakarta",
            "credit": {"credit_limit": 20000, "exposure": 671.08, "available_credit": 19328.92},
        }),
        _tool("get_receivables", {"ar_balance": 0, "currency": "USD", "overdue_days": 0, "credit_status": "clear"}),
        _tool("get_shipment", {
            "status_text": "到达目的地",
            "signed": False,
            "last_event_at": "2026-09-17T12:04:00+08:00",
            "events": [{"location": "Jakarta"}],
        }),
    ])
    final = model.generate(messages, [])
    assert final.kind == "final"
    assert "PT Nusantara Process Engineering" in final.text
    assert "尚未签收" in final.text
    assert "应收 0 USD" in final.text


def test_offline_unknown_prompt_uses_knowledge_base():
    model = OfflineDemoModel()
    response = model.generate([{"role": "user", "content": "介绍一下公司"}], [])
    assert [call.name for call in response.tool_calls] == ["search_knowledge"]
