"""T14 · 继续会话：创建新 Run，加载完整历史；未配对历史受控处理。产品级 AC-01 的 --resume 部分。"""
from agent_app.agent import AgentLoop
from agent_app.agent.conversation import ConversationStore, complete_boundary
from agent_app.doubles import ScriptedModel, final, tool_calls
from agent_app.tools import ToolExecutor, ToolRegistry
from agent_app.tools.availability import GetAvailability
from agent_app.tools.product import GetProductSpec


# revision: 0aO30 09K6c
def _loop(erp, script):
    reg = ToolRegistry([GetProductSpec(erp), GetAvailability(erp)])
    model = ScriptedModel(script)
    return model, AgentLoop(model, ToolExecutor(reg), reg.specs())


def test_t14_resume_creates_new_run_with_full_history(erp, tmp_path):
    store = ConversationStore(tmp_path)
    cid = store.new_id()
    m1, loop1 = _loop(erp, [tool_calls(("get_product_spec", {"model": "X200"})), final("X200 是离心泵。")])
    r1 = loop1.run("查一下 X200 的规格", run_id="run1")
    store.save(cid, r1.messages)
    # 中断后继续：新进程、新 Run，只拿历史
    loaded = store.load(cid)
    assert loaded.truncated == 0 and [m["role"] for m in loaded.messages] == ["user", "assistant", "tool", "assistant"]
    m2, loop2 = _loop(erp, [tool_calls(("get_availability", {"model": "X200"})), final("可用 5 台。")])
    r2 = loop2.run("那它现在的库存交期呢", history=loaded.messages, run_id="run2")
    first_req = m2.requests[0]["messages"]
    assert [m["role"] for m in first_req] == ["system", "user", "assistant", "tool", "assistant", "user"]
    assert first_req[1]["content"] == "查一下 X200 的规格" and first_req[-1]["content"] == "那它现在的库存交期呢"
    assert r2.run_id != r1.run_id and r2.status == "completed"
    assert erp.calls == {"get_product": 1, "get_inventory": 1}       # 旧工具请求没有被重新执行


def test_t14_unpaired_history_is_cut_back_to_complete_boundary():
    history = [
        {"role": "user", "content": "查 X200"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "a1", "type": "function", "function": {"name": "get_product_spec", "arguments": "{}"}},
                                                            {"id": "a2", "type": "function", "function": {"name": "get_availability", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "a1", "name": "get_product_spec", "content": "{}"},
    ]   # a2 没有结果：进程在这里被杀
    loaded = complete_boundary(history)
    assert [m["role"] for m in loaded.messages] == ["user"] and loaded.truncated == 2
    assert "未配对" in loaded.note
