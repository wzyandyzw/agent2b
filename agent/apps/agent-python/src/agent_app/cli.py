"""CLI：输入、输出、调用应用入口。不实现另一份 Loop。
w1.7：chat 子命令接真实模型与真实 ERP；--scripted 用替身离线演示。"""
from __future__ import annotations

import argparse
import sys

from agent_app.agent import AgentLoop
from agent_app.config import Settings
from agent_app.contracts import Budget
from agent_app.tools import ToolExecutor, ToolRegistry
from agent_app.tools.availability import GetAvailability
from agent_app.tools.product import GetProductSpec


class PrintSink:
    """把工具事件打到 stderr：现在能看见"提出动作"和"真正执行"是两件事。"""

    def emit(self, event_type: str, **data) -> None:
        if event_type == "tool.requested":
            print(f"  → 模型请求工具 {data['name']}({data['arguments']})  id={data['call_id']}", file=sys.stderr)
        elif event_type == "tool.rejected":
            print(f"  ✗ 拒绝 {data['name']}：{data['category']}/{data['code']}", file=sys.stderr)
        elif event_type == "tool.executed":
            tag = "ok" if data["ok"] else f"失败 {data['category']}/{data['code']}"
            print(f"  ← 执行 {data['name']} {tag}  {data['duration_ms']} ms", file=sys.stderr)


def build_loop(settings: Settings, *, scripted: bool, max_steps: int, sink=None) -> AgentLoop:
    sink = sink or PrintSink()
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
    registry = ToolRegistry([GetProductSpec(erp), GetAvailability(erp)])
    executor = ToolExecutor(registry, sink=sink)
    return AgentLoop(model, executor, registry.specs(), sink=sink, budget=Budget(max_steps=max_steps))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="agent-cli", description="深维工作台 · W1")
    sub = ap.add_subparsers(dest="cmd")
    chat = sub.add_parser("chat", help="与 agent 对话一轮")
    chat.add_argument("text")
    chat.add_argument("--max-steps", type=int, default=6)
    chat.add_argument("--scripted", action="store_true", help="用 ScriptedModel + FakeERP 离线跑")
    a = ap.parse_args(argv)
    if a.cmd != "chat":
        ap.print_help()
        return 0
    settings = Settings.from_env()
    loop = build_loop(settings, scripted=a.scripted, max_steps=a.max_steps)
    result = loop.run(a.text)
    print(f"[run {result.run_id}] {result.status} / {result.stop_reason} · {result.steps} 步", file=sys.stderr)
    print(result.answer if result.answer is not None else f"（无答复：{result.stop_reason}）")
    return 0 if result.status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
