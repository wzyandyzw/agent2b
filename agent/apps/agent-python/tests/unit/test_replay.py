"""T13 · 回放：不调用模型或 ERP；记录缺损可报告。W1-AC-07。"""
from agent_app.agent import AgentLoop
from agent_app.agent.replay import replay
from agent_app.doubles import ScriptedModel, final, tool_calls
from agent_app.observability import JsonlSink
from agent_app.tools import ToolExecutor, ToolRegistry
from agent_app.tools.availability import GetAvailability
from agent_app.tools.product import GetProductSpec


def _run(erp, tmp_path):
    sink = JsonlSink(tmp_path / "events.jsonl")
    model = ScriptedModel([tool_calls(("get_product_spec", {"model": "X200"})), final("完成")])
    reg = ToolRegistry([GetProductSpec(erp), GetAvailability(erp)])
    r = AgentLoop(model, ToolExecutor(reg, sink=sink), reg.specs(), sink=sink).run("查 X200", run_id="runR")
    return model, sink.path, r


def test_t13_replay_makes_zero_external_calls(erp, tmp_path):
    model, path, r = _run(erp, tmp_path)
    before = (model.calls, dict(erp.calls))
    rep = replay(path)                                   # 签名里没有模型、没有 ERP
    assert (model.calls, dict(erp.calls)) == before == (2, {"get_product": 1})
    assert rep.runs == ["runR"] and [s.step for s in rep.steps] == [1, 2]
    assert rep.steps[0].tool_calls == [{"call_id": "call_1", "name": "get_product_spec", "outcome": "ok"}]
    assert rep.steps[1].response_kind == "final" and rep.steps[1].text == "完成"
    assert rep.stops[0]["stop_reason"] == "completed" and not rep.gaps and rep.external_calls_made == 0


def test_t13_replay_reports_truncated_file(erp, tmp_path):
    _, path, _ = _run(erp, tmp_path)
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(lines[:-3]) + "\n" + lines[-3][:40] + "\n", encoding="utf-8")   # 掉了结尾，还有半行
    rep = replay(path)
    assert rep.problems and "不是完整 JSON" in rep.problems[0]
    assert any("没有响应记录" in g or "没有停止记录" in g for g in rep.gaps)
