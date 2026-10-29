"""w1.5：替身本身要可信——脚本按序返回并记录请求；FakeERP 计数与故障注入可控。"""
import pytest

from agent_app.contracts import ResponseKind, ToolFailure, ToolSpec
from agent_app.doubles import FakeERP, ScriptedModel, final, tool_calls

SPEC = ToolSpec("get_product_spec", "查规格", {"type": "object", "properties": {"model": {"type": "string"}}})


def test_scripted_model_returns_in_order_and_records_requests():
    m = ScriptedModel([tool_calls(("get_product_spec", {"model": "X200"})), final("X200 是离心泵")])
    r1 = m.generate([{"role": "user", "content": "查 X200"}], [SPEC], timeout_s=1)
    r2 = m.generate([{"role": "user", "content": "查 X200"}, r1.to_assistant_message()], [SPEC], timeout_s=1)
    assert r1.kind == ResponseKind.TOOL_CALLS and r1.tool_calls[0].name == "get_product_spec"
    assert r2.kind == ResponseKind.FINAL and r2.text == "X200 是离心泵"
    assert m.calls == 2 and m.requests[1]["messages"][1]["tool_calls"][0]["id"] == "call_1"
    with pytest.raises(AssertionError):
        m.generate([], [SPEC], timeout_s=1)


def test_fake_erp_counts_calls_and_injects_faults():
    erp = FakeERP(products={"X200": {"sku": "X200"}}, inventory={"X200": {"available": 5}})
    assert erp.get_product("x200", timeout_s=1)["sku"] == "X200"
    with pytest.raises(ToolFailure) as e:
        erp.get_product("X999", timeout_s=1)
    assert e.value.error.category == "not_found"
    erp.inject("get_inventory", FakeERP.timeout(), times=1)
    with pytest.raises(ToolFailure) as e:
        erp.get_inventory("X200", 1, timeout_s=1)
    assert e.value.error.category == "timeout"
    assert erp.get_inventory("X200", 1, timeout_s=1)["requested_qty"] == 1
    assert erp.calls == {"get_product": 2, "get_inventory": 2}
