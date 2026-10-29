"""T12 · 请求与事件：能找到实际模型请求和调用配对；无鉴权秘密。"""
from agent_app.agent import AgentLoop
from agent_app.doubles import ScriptedModel, final, tool_calls
from agent_app.observability import JsonlSink, read_events
from agent_app.tools import ToolExecutor, ToolRegistry
from agent_app.tools.availability import GetAvailability
from agent_app.tools.product import GetProductSpec


def test_t12_events_hold_actual_requests_and_pairings(erp, tmp_path):
    sink = JsonlSink(tmp_path / "events.jsonl")
    model = ScriptedModel([tool_calls(("get_product_spec", {"model": "X200"}), ("get_availability", {"model": "X200"})),
                           final("好的")])
    reg = ToolRegistry([GetProductSpec(erp), GetAvailability(erp)])
    loop = AgentLoop(model, ToolExecutor(reg, sink=sink), reg.specs(), sink=sink)
    r = loop.run("查一下 X200 的规格和当前库存交期", run_id="runA")
    events, problems = read_events(sink.path)
    assert not problems
    types = [e["type"] for e in events]
    assert types == ["run.started", "model.request", "model.response",
                     "tool.requested", "tool.executed", "tool.requested", "tool.executed",
                     "model.request", "model.response", "run.completed"]
    # 第二步的快照就是真正发给模型的 messages：含 assistant 的两个 tool_calls 与两条配对的 tool 消息
    step2 = next(e for e in events if e["type"] == "model.request" and e["step"] == 2)
    msgs = step2["snapshot"]["messages"]
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "tool", "tool"]
    assert [m["tool_call_id"] for m in msgs[3:]] == [tc["id"] for tc in msgs[2]["tool_calls"]] == ["call_1", "call_2"]
    assert step2["snapshot"]["tools"][0]["function"]["name"] == "get_product_spec"
    # 工具请求事件在执行事件之前（I2：先落日志再执行），且 run_id 一致
    assert all(e["run_id"] == "runA" for e in events)
    # 结束事件带停止原因与步数
    assert events[-1]["stop_reason"] == "completed" and events[-1]["steps"] == r.steps == 2


def test_t12_snapshot_has_no_secret_or_auth_header(erp, tmp_path, monkeypatch):
    import httpx
    from agent_app.llm import DashScopeClient
    secret = "sk-test-SECRET-1234567890abcdef"
    captured = {}

    def handler(request):
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "你好"},
                                                       "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})
    client = DashScopeClient(secret, "qwen-plus", "https://model.test/v1", transport=httpx.MockTransport(handler))
    sink = JsonlSink(tmp_path / "events.jsonl")
    reg = ToolRegistry([GetProductSpec(erp)])
    AgentLoop(client, ToolExecutor(reg, sink=sink), reg.specs(), sink=sink).run("你好", run_id="runB")
    text = sink.path.read_text(encoding="utf-8")
    assert captured["auth"] == f"Bearer {secret}"          # 请求确实带了鉴权
    assert secret not in text and "Bearer" not in text     # 事件里没有
    assert '"model": "qwen-plus"' in text                   # 但有模型标识与参数
