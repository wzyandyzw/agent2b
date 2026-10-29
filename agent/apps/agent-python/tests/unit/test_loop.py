"""T01–T04、T09、T10：Loop 的控制流。全部用 ScriptedModel + FakeERP，不联网。"""
from agent_app.agent import AgentLoop
from agent_app.contracts import Budget, RunStatus, StopReason
from agent_app.doubles import ScriptedModel, final, tool_calls
from agent_app.tools import ToolExecutor, ToolRegistry
from agent_app.tools.availability import GetAvailability
from agent_app.tools.product import GetProductSpec

ASK = "查一下 X200 的规格和当前库存交期"


def _loop(erp, script, **budget):
    model = ScriptedModel(script, repeat_last=budget.pop("repeat_last", False))
    reg = ToolRegistry([GetProductSpec(erp), GetAvailability(erp)])
    return model, AgentLoop(model, ToolExecutor(reg), reg.specs(), budget=Budget(**budget))


def _roles(msgs):
    return [m["role"] for m in msgs]


# 增量 A · T01 模型直接给最终文本：不执行工具，正常结束
def test_t01_final_text_runs_no_tool(erp):
    model, loop = _loop(erp, [final("我是深维工作台的数字员工。")])
    r = loop.run("你好")
    assert r.status == RunStatus.COMPLETED and r.stop_reason == StopReason.COMPLETED
    assert r.answer == "我是深维工作台的数字员工。" and r.steps == 1 and model.calls == 1
    assert sum(erp.calls.values()) == 0
    assert _roles(r.messages) == ["system", "user", "assistant"]


# 增量 B · T02 一次工具调用后回答：工具恰被执行一次，结果进入第二轮请求
def test_t02_single_tool_call_result_enters_next_request(erp):
    model, loop = _loop(erp, [tool_calls(("get_product_spec", {"model": "X200"})), final("X200 是 260 W 离心输送泵。")])
    r = loop.run(ASK)
    assert r.status == RunStatus.COMPLETED and r.steps == 2 and model.calls == 2
    assert erp.calls["get_product"] == 1 and erp.calls["get_inventory"] == 0
    second = model.requests[1]["messages"]
    assert _roles(second) == ["system", "user", "assistant", "tool"]
    assert second[2]["tool_calls"][0]["id"] == "call_1" and second[3]["tool_call_id"] == "call_1"
    assert '"ok": true' in second[3]["content"] and "2380" in second[3]["content"]


# 增量 C · T03 两轮调用：后轮保留前轮请求与结果，不丢用户目标
def test_t03_two_rounds_keep_full_history(erp):
    model, loop = _loop(erp, [
        tool_calls(("get_product_spec", {"model": "X200"}), prefix="r1"),
        tool_calls(("get_availability", {"model": "X200", "qty": 1}), prefix="r2"),
        final("规格与交期如下……"),
    ])
    r = loop.run(ASK)
    assert r.status == RunStatus.COMPLETED and r.steps == 3
    third = model.requests[2]["messages"]
    assert _roles(third) == ["system", "user", "assistant", "tool", "assistant", "tool"]
    assert third[1]["content"] == ASK
    assert (third[3]["tool_call_id"], third[5]["tool_call_id"]) == ("r1_1", "r2_1")
    assert erp.calls == {"get_product": 1, "get_inventory": 1}


# 增量 D · T04 一次响应两个调用：每个 call_id 都有对应结果，全部处理完再请求模型（W1-AC-03）
def test_t04_multi_call_pairs_every_id_before_next_request(erp):
    model, loop = _loop(erp, [
        tool_calls(("get_product_spec", {"model": "X200"}), ("get_availability", {"model": "X200"}), prefix="m"),
        final("好的。"),
    ])
    r = loop.run(ASK)
    assert r.status == RunStatus.COMPLETED and model.calls == 2
    second = model.requests[1]["messages"]
    assert _roles(second) == ["system", "user", "assistant", "tool", "tool"]
    assert [m["tool_call_id"] for m in second[3:]] == ["m_1", "m_2"]
    assert [m["name"] for m in second[3:]] == ["get_product_spec", "get_availability"]
    assert erp.calls == {"get_product": 1, "get_inventory": 1}


# T02 的失败路径：工具失败也要配对回注，错误不是事实（W1-AC-05 在 Loop 这一层）
def test_tool_failure_is_paired_back_as_error_not_fact(erp):
    from agent_app.doubles import FakeERP
    erp.inject("get_inventory", FakeERP.timeout())
    model, loop = _loop(erp, [tool_calls(("get_availability", {"model": "X200"})), final("交期暂时无法确认。")])
    r = loop.run(ASK)
    second = model.requests[1]["messages"]
    assert second[3]["tool_call_id"] == "call_1" and '"category": "timeout"' in second[3]["content"]
    assert r.status == RunStatus.COMPLETED


# 增量 E · T10 持续工具请求：达 max_steps 停止，不会多发一次模型调用（W1-AC-04）
def test_t10_max_steps_stops_without_extra_model_call(erp):
    model, loop = _loop(erp, [tool_calls(("get_availability", {"model": "X200"}))] * 5, max_steps=3)
    r = loop.run(ASK)
    assert r.status == RunStatus.STOPPED and r.stop_reason == StopReason.MAX_STEPS
    assert model.calls == 3 and r.steps == 3 and erp.calls["get_inventory"] == 3
    assert r.answer is None
    assert r.messages[-1]["role"] == "tool"   # 停在完整边界：最后一个请求已配对，没有半截消息


# 增量 F · T09 模型结构异常：不把空白响应判为完成；行为明确
def test_t09_malformed_response_is_protocol_failure_not_completion(erp):
    from agent_app.doubles import malformed
    model, loop = _loop(erp, [malformed(), final("不应该到这里")])
    r = loop.run(ASK)
    assert r.status == RunStatus.FAILED and r.stop_reason == StopReason.PROTOCOL_ERROR
    assert r.answer is None and model.calls == 1 and sum(erp.calls.values()) == 0
