"""T11 · 预算与重试：重试计入次数 / 时间；未知用量保留标记；墙钟到期不再发模型请求。W1-AC-04 的另一半。"""
from agent_app.agent import AgentLoop
from agent_app.contracts import Budget, RunStatus, StopReason, Usage
from agent_app.doubles import FakeERP, ScriptedModel, final, tool_calls
from agent_app.tools import ToolExecutor, ToolRegistry
from agent_app.tools.availability import GetAvailability
from agent_app.tools.product import GetProductSpec


def _loop(erp, script, budget, clock=None):
    reg = ToolRegistry([GetProductSpec(erp), GetAvailability(erp)])
    model = ScriptedModel(script)
    kw = {"clock": clock} if clock else {}
    return model, AgentLoop(model, ToolExecutor(reg), reg.specs(), budget=budget, **kw)


# 只读工具超时的有界重试：配置 1 次就只多打 1 次，超时一次后成功
def test_t11_bounded_retry_on_timeout_counts_every_attempt(erp):
    erp.inject("get_inventory", FakeERP.timeout(), times=1)
    model, loop = _loop(erp, [tool_calls(("get_availability", {"model": "X200"})), final("可用 5 台")],
                        Budget(tool_retries=1))
    r = loop.run("查交期")
    assert r.status == RunStatus.COMPLETED
    assert erp.calls["get_inventory"] == 2                       # 1 次超时 + 1 次重试
    assert '"ok": true' in model.requests[1]["messages"][3]["content"]


def test_t11_retry_limit_is_respected_then_error_is_reported(erp):
    erp.inject("get_inventory", FakeERP.timeout())               # 一直超时
    model, loop = _loop(erp, [tool_calls(("get_availability", {"model": "X200"})), final("无法确认")],
                        Budget(tool_retries=1))
    loop.run("查交期")
    assert erp.calls["get_inventory"] == 2                       # 不会无限重试
    assert '"category": "timeout"' in model.requests[1]["messages"][3]["content"]


def test_t11_not_found_is_not_retried(erp):
    model, loop = _loop(erp, [tool_calls(("get_product_spec", {"model": "X999"})), final("没有这个型号")],
                        Budget(tool_retries=2))
    loop.run("查 X999")
    assert erp.calls["get_product"] == 1                         # 业务无数据不是临时故障，不重试


# 供应商没回用量：标记 unknown，不当零；有用量时累加
def test_t11_unknown_usage_is_flagged_not_zeroed(erp):
    model, loop = _loop(erp, [tool_calls(("get_product_spec", {"model": "X200"}), ), final("好")], Budget())
    r = loop.run("查")
    assert r.usage_unknown is True
    model2, loop2 = _loop(erp, [final("好", usage=Usage(10, 5, 15))], Budget())
    r2 = loop2.run("查")
    assert r2.usage_unknown is False and r2.usage.total_tokens == 15


# 墙钟：到期后不再发起新的模型请求；可中断边界是"下一次调用前"
def test_t11_wall_clock_stops_before_next_model_call(erp):
    ticks = iter([0.0, 0.0, 200.0, 200.0, 200.0])   # started=0；第一轮前 0；第二轮前 200 > 120
    model, loop = _loop(erp, [tool_calls(("get_product_spec", {"model": "X200"}))] * 3 + [final("x")],
                        Budget(wall_clock_s=120), clock=lambda: next(ticks))
    r = loop.run("查")
    assert r.status == RunStatus.STOPPED and r.stop_reason == StopReason.WALL_CLOCK
    assert model.calls == 1 and r.steps == 1
