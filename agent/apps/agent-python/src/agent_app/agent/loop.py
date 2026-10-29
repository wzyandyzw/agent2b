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

import time
import uuid

from agent_app.contracts import (Budget, EventSink, ModelClient, ResponseKind, RunResult, RunStatus, StopReason,
                                 ToolSpec, Usage)
from agent_app.llm.dashscope_client import ModelError
from agent_app.tools import ToolExecutor
from agent_app.tools.registry import NullSink

from .context import ContextBuilder


class AgentLoop:
    def __init__(self, model: ModelClient, executor: ToolExecutor, tools: list[ToolSpec],
                 context: ContextBuilder | None = None, sink: EventSink | None = None,
                 budget: Budget | None = None, clock=time.monotonic) -> None:
        self.model, self.executor, self.tools = model, executor, tools
        self.context = context or ContextBuilder()
        self.sink = sink or NullSink()
        self.budget = budget or Budget()
        self.clock = clock   # 可注入：测试里不用真等 120 秒

    def run(self, user_input: str, history: list[dict] | None = None, *, run_id: str | None = None) -> RunResult:
        run_id = run_id or uuid.uuid4().hex[:12]
        messages = self.context.build(history, user_input)
        steps, total, unknown = 0, Usage(0, 0, 0), False
        self.sink.emit("run.started", run_id=run_id, input=user_input, history_messages=len(history or []),
                       budget=self.budget.__dict__)
        describe = getattr(self.model, "describe", lambda: {})

        def finish(status, reason, answer):
            ev = {"completed": "run.completed", "stopped": "run.stopped", "failed": "run.failed"}[status]
            self.sink.emit(ev, run_id=run_id, stop_reason=reason, steps=steps, usage=total.__dict__,
                           usage_unknown=unknown)
            return RunResult(run_id, status, reason, answer, steps, messages, total, unknown)

        started = self.clock()
        while steps < self.budget.max_steps:                          # 下一次调用前检查预算
            if self.clock() - started > self.budget.wall_clock_s:    # 墙钟只在这里检查：可中断边界是"下一次调用前"
                self.sink.emit("budget.exhausted", run_id=run_id, kind="wall_clock", elapsed_s=self.clock() - started)
                return finish(RunStatus.STOPPED, StopReason.WALL_CLOCK, None)
            steps += 1
            # I1：模型看到的每一条上下文先进事件，再发请求。快照里没有密钥与鉴权头。
            self.sink.emit("model.request", run_id=run_id, step=steps,
                           snapshot={"messages": messages, "tools": [t.to_openai() for t in self.tools],
                                     "timeout_s": self.budget.model_timeout_s, **describe()})
            try:
                resp = self.model.generate(messages, self.tools, timeout_s=self.budget.model_timeout_s)
            except ModelError as e:
                self.sink.emit("model.error", run_id=run_id, step=steps, category=e.category, status=e.status,
                               message=str(e), body=e.body)
                return finish(RunStatus.FAILED, StopReason.MODEL_ERROR, None)
            if resp.usage is None or resp.usage.unknown:
                unknown = True                                            # 用量未知标记，不当零
            else:
                total = Usage((total.prompt_tokens or 0) + (resp.usage.prompt_tokens or 0),
                              (total.completion_tokens or 0) + (resp.usage.completion_tokens or 0),
                              (total.total_tokens or 0) + (resp.usage.total_tokens or 0))
            self.sink.emit("model.response", run_id=run_id, step=steps, kind=resp.kind, text=resp.text,
                           tool_calls=[c.__dict__ for c in resp.tool_calls], finish_reason=resp.finish_reason,
                           usage=(resp.usage.__dict__ if resp.usage else None), raw=resp.raw)
            if resp.kind == ResponseKind.TOOL_CALLS:
                messages.append(resp.to_assistant_message())          # 保存完整的模型响应与调用标识
                for call in resp.tool_calls:                           # 一个响应里的多个调用先串行执行
                    result = self.executor.execute(call, timeout_s=self.budget.tool_timeout_s, run_id=run_id,
                                                   retries=self.budget.tool_retries)
                    messages.append(result.to_message())              # 每个请求都配一个带同 call_id 的结果
                continue                                               # 全部配对后才进入下一轮
            if resp.kind == ResponseKind.FINAL:
                messages.append(resp.to_assistant_message())
                return finish(RunStatus.COMPLETED, StopReason.COMPLETED, resp.text)
            # MALFORMED：无文本也无工具请求。协议失败，不是"完成"，也不是"业务无数据"。
            return finish(RunStatus.FAILED, StopReason.PROTOCOL_ERROR, None)
        # 步数耗尽：不再发起新的模型请求；消息停在完整边界（最后一轮工具结果已配对）
        return finish(RunStatus.STOPPED, StopReason.MAX_STEPS, None)
