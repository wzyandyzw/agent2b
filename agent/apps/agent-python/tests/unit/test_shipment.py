"""T15 · 新工具扩展：注册后可用，Loop 不增加业务特判，旧行为通过。规格见 docs/specs/w01-shipment.md。"""
import inspect

from agent_app.agent import AgentLoop
from agent_app.contracts import RunStatus
from agent_app.doubles import ScriptedModel, final, tool_calls
from agent_app.tools import ToolExecutor, ToolRegistry
from agent_app.tools.availability import GetAvailability
from agent_app.tools.product import GetProductSpec
from agent_app.tools.shipment import GetShipment


def test_t15_registered_shipment_tool_is_usable_through_the_same_loop(erp):
    reg = ToolRegistry([GetProductSpec(erp), GetAvailability(erp), GetShipment(erp)])
    assert "get_shipment" in reg and len(reg.specs()) == 3
    model = ScriptedModel([tool_calls(("get_shipment", {"tracking_no": "SF1234567890"})), final("到达目的地机场，未签收。")])
    r = AgentLoop(model, ToolExecutor(reg), reg.specs()).run("SF1234567890 到哪了")
    assert r.status == RunStatus.COMPLETED and erp.calls["get_shipment"] == 1
    tool_msg = model.requests[1]["messages"][3]
    assert tool_msg["tool_call_id"] == "call_1" and '"status_code": "arrived"' in tool_msg["content"]
    assert '"last_event_at": "2026-09-17T12:04:00+08:00"' in tool_msg["content"]


def test_t15_shipment_input_and_not_found_boundaries(erp):
    reg = ToolRegistry([GetShipment(erp)])
    ex = ToolExecutor(reg)
    from agent_app.contracts import ToolCall
    r = ex.execute(ToolCall("c1", "get_shipment", '{"tracking_no": ""}'), timeout_s=1)
    assert r.error.category == "input_error" and erp.calls["get_shipment"] == 0
    r = ex.execute(ToolCall("c2", "get_shipment", '{"tracking_no": "SF0000000000"}'), timeout_s=1)
    assert r.error.category == "not_found" and r.error.code == "shipment_not_found"


def test_t15_loop_has_no_tool_name_special_case():
    src = inspect.getsource(AgentLoop)
    assert "get_shipment" not in src and "get_product_spec" not in src and "get_availability" not in src
