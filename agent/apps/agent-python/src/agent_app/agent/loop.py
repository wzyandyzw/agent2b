"""AgentLoop · 增量 A–F。教学控制流：

    建立本次运行上下文
    在步数预算允许时：
        获取并校验模型响应
        若包含工具请求：保存响应与调用标识 → 逐个校验并执行 → 为每个请求配一个结果 → 下一轮
        否则若是有效最终答复：记录完成并返回
        否则：记录协议失败并停止
    记录预算停止，返回明确的非成功结果
"""
from __future__ import annotations

import uuid

from agent_app.contracts import (Budget, EventSink, ModelClient, ResponseKind, RunResult, RunStatus, StopReason,
                                 ToolSpec)
from agent_app.tools import ToolExecutor
from agent_app.tools.registry import NullSink

from .context import ContextBuilder


class AgentLoop:
    def __init__(self, model: ModelClient, executor: ToolExecutor, tools: list[ToolSpec],
                 context: ContextBuilder | None = None, sink: EventSink | None = None,
                 budget: Budget | None = None) -> None:
        self.model, self.executor, self.tools = model, executor, tools
        self.context = context or ContextBuilder()
        self.sink = sink or NullSink()
        self.budget = budget or Budget()

    def run(self, user_input: str, history: list[dict] | None = None, *, run_id: str | None = None) -> RunResult:
        run_id = run_id or uuid.uuid4().hex[:12]
        messages = self.context.build(history, user_input)
        steps = 0
        while steps < self.budget.max_steps:                          # 下一次调用前检查预算
            steps += 1
            resp = self.model.generate(messages, self.tools, timeout_s=self.budget.model_timeout_s)
            if resp.kind == ResponseKind.TOOL_CALLS:
                messages.append(resp.to_assistant_message())          # 保存完整的模型响应与调用标识
                for call in resp.tool_calls:                           # 一个响应里的多个调用先串行执行
                    result = self.executor.execute(call, timeout_s=self.budget.tool_timeout_s)
                    messages.append(result.to_message())              # 每个请求都配一个带同 call_id 的结果
                continue                                               # 全部配对后才进入下一轮
            if resp.kind == ResponseKind.FINAL:
                messages.append(resp.to_assistant_message())
                return RunResult(run_id, RunStatus.COMPLETED, StopReason.COMPLETED, resp.text, steps, messages)
            # MALFORMED：无文本也无工具请求。协议失败，不是"完成"，也不是"业务无数据"。
            return RunResult(run_id, RunStatus.FAILED, StopReason.PROTOCOL_ERROR, None, steps, messages)
        # 步数耗尽：不再发起新的模型请求；消息停在完整边界（最后一轮工具结果已配对）
        return RunResult(run_id, RunStatus.STOPPED, StopReason.MAX_STEPS, None, steps, messages)
