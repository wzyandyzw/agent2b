"""CLI：输入、输出、调用应用入口。不实现另一份 Loop。
chat   一轮对话：真实模型 + 真实 ERP；--scripted 离线；--resume 继续一个会话（新 Run + 已保存历史）
replay 只读回放一个会话的事件：不调模型、不调工具"""
from __future__ import annotations

import argparse
import json
import sys

from agent_app.agent import AgentLoop
from agent_app.agent.conversation import ConversationStore
from agent_app.agent.replay import replay
from agent_app.config import Settings
from agent_app.contracts import Budget
from agent_app.observability import JsonlSink
from agent_app.tools import ToolExecutor, ToolRegistry
from agent_app.tools.availability import GetAvailability
from agent_app.tools.product import GetProductSpec
from agent_app.tools.shipment import GetShipment


class TeeSink:
    """事件既写 JSONL 又在 stderr 上打一行给人看。"""

    def __init__(self, jsonl: JsonlSink, show_request: bool = False) -> None:
        self.jsonl, self.show_request = jsonl, show_request

    def emit(self, event_type: str, **data) -> None:
        self.jsonl.emit(event_type, **data)
        e = sys.stderr
        if event_type == "model.request":
            print(f"  ▶ 第 {data['step']} 步 → 模型（{len(data['snapshot']['messages'])} 条消息）", file=e)
            if self.show_request:
                print(json.dumps(data["snapshot"]["messages"], ensure_ascii=False, indent=1), file=e)
        elif event_type == "model.response":
            names = [c["name"] for c in data["tool_calls"]]
            print(f"  ◀ 模型 {data['kind']}" + (f" 请求 {names}" if names else ""), file=e)
        elif event_type == "tool.requested":
            print(f"    → 请求工具 {data['name']}({data['arguments']})  id={data['call_id']}", file=e)
        elif event_type == "tool.rejected":
            print(f"    ✗ 拒绝 {data['name']}：{data['category']}/{data['code']}", file=e)
        elif event_type == "tool.retry":
            print(f"    ↻ {data['name']} 超时，重试第 {data['attempt']} 次后", file=e)
        elif event_type == "tool.executed":
            tag = "ok" if data["ok"] else f"失败 {data['category']}/{data['code']}"
            print(f"    ← 执行 {data['name']} {tag}  {data['duration_ms']} ms", file=e)
        elif event_type == "model.error":
            print(f"  ✗ 模型调用失败：{data['category']} {data.get('status') or ''} {data['message']}", file=e)
        elif event_type == "budget.exhausted":
            print(f"  ■ 预算耗尽：{data['kind']}", file=e)


def build_registry(settings: Settings, *, scripted: bool):
    if scripted:
        import pathlib
        from agent_app.doubles import FakeERP, ScriptedModel, final, tool_calls
        fixtures = pathlib.Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "erp"
        erp = FakeERP.from_fixtures(fixtures)
        model = ScriptedModel([
            tool_calls(("get_product_spec", {"model": "X200"}), ("get_availability", {"model": "X200", "qty": 1})),
            final("（离线脚本）X200 离心输送泵，260 W，最大流量 5 L/min；可用 5 台，最早 2026-09-23 深圳发运。"),
        ])
    else:
        from agent_app.llm import DashScopeClient
        from agent_app.tools.erp_client import ErpClient
        erp = ErpClient(settings.erp_base_url, settings.erp_api_key)
        model = DashScopeClient(settings.dashscope_api_key, settings.model, settings.model_base_url)
    return model, ToolRegistry([GetProductSpec(erp), GetAvailability(erp), GetShipment(erp)])


def cmd_chat(a) -> int:
    settings = Settings.from_env()
    store = ConversationStore(settings.runs_dir)
    history = []
    if a.resume:
        cid = a.resume
        loaded = store.load(cid)
        history = loaded.messages
        if loaded.note:
            print(f"[resume] {loaded.note}", file=sys.stderr)
        print(f"[resume] 会话 {cid}：装入 {len(history)} 条历史，新开一个 Run", file=sys.stderr)
    else:
        cid = store.new_id()
    sink = TeeSink(JsonlSink(store.events_path(cid)), show_request=a.show_request)
    model, registry = build_registry(settings, scripted=a.scripted)
    budget = Budget(max_steps=a.max_steps, tool_retries=a.tool_retries, tool_timeout_s=a.tool_timeout)
    loop = AgentLoop(model, ToolExecutor(registry, sink=sink), registry.specs(), sink=sink, budget=budget)
    result = loop.run(a.text, history=history)
    store.save(cid, result.messages)
    usage = "用量未知" if result.usage_unknown else f"{result.usage.total_tokens} tokens"
    print(f"[conversation {cid} · run {result.run_id}] {result.status} / {result.stop_reason} · {result.steps} 步 · {usage}",
          file=sys.stderr)
    print(f"[events] {store.events_path(cid)}   继续：agent-cli chat --resume {cid} \"…\"", file=sys.stderr)
    print(result.answer if result.answer is not None else f"（无答复：{result.stop_reason}）")
    return 0 if result.status == "completed" else 1


def cmd_replay(a) -> int:
    settings = Settings.from_env()
    path = ConversationStore(settings.runs_dir).events_path(a.conversation_id)
    rep = replay(path)
    print(f"会话 {a.conversation_id}：{len(rep.runs)} 个 Run，{len(rep.steps)} 步，外部调用 {rep.external_calls_made} 次")
    for s in rep.steps:
        calls = ", ".join(f"{c['name']}[{c['call_id'][-6:]}]={c['outcome']}" for c in s.tool_calls)
        text = f" 答复：{s.text[:50]}…" if s.text and s.response_kind == "final" else ""
        print(f"  {s.run_id} 第 {s.step} 步：发 {s.request_messages} 条消息 → {s.response_kind} {calls}{text}")
    for st in rep.stops:
        print(f"  {st['run_id']} 结束：{st['type']} / {st['stop_reason']} · {st['steps']} 步")
    for g in rep.gaps:
        print(f"  ! 缺损：{g}")
    for p in rep.problems:
        print(f"  ! 文件：{p}")
    return 0 if not (rep.gaps or rep.problems) else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="agent-cli", description="深维工作台 · W1")
    sub = ap.add_subparsers(dest="cmd")
    chat = sub.add_parser("chat", help="与 agent 对话一轮")
    chat.add_argument("text")
    chat.add_argument("--resume", metavar="CONVERSATION_ID", help="继续一个会话：新 Run + 已保存历史")
    chat.add_argument("--show-request", action="store_true", help="打印每一步真正发给模型的 messages")
    chat.add_argument("--max-steps", type=int, default=6)
    chat.add_argument("--tool-retries", type=int, default=0, help="只读工具超时的有界重试次数")
    chat.add_argument("--tool-timeout", type=float, default=5.0)
    chat.add_argument("--scripted", action="store_true", help="用 ScriptedModel + FakeERP 离线跑")
    rp = sub.add_parser("replay", help="只读回放一个会话的事件")
    rp.add_argument("conversation_id")
    a = ap.parse_args(argv)
    if a.cmd == "chat":
        return cmd_chat(a)
    if a.cmd == "replay":
        return cmd_replay(a)
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
