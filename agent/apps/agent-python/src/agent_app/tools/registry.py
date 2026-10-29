"""ToolRegistry：按名字找工具。ToolExecutor：查 → 验 → 执 → 带 call_id 回。"""
from __future__ import annotations

import time

from agent_app.contracts import EventSink, Tool, ToolCall, ToolError, ToolFailure, ToolResult, ToolSpec
from agent_app.guardrails import validate_args


class NullSink:
    def emit(self, event_type: str, **data) -> None:
        pass


class ToolRegistry:
    def __init__(self, tools: list[Tool] | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        for t in tools or []:
            self.register(t)

    def register(self, tool: Tool) -> None:
        self._tools[tool.spec.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def specs(self) -> list[ToolSpec]:
        return [t.spec for t in self._tools.values()]

    def __contains__(self, name: str) -> bool:
        return name in self._tools


class ToolExecutor:
    def __init__(self, registry: ToolRegistry, sink: EventSink | None = None) -> None:
        self._registry = registry
        self._sink = sink or NullSink()

    def execute(self, call: ToolCall, *, timeout_s: float, run_id: str | None = None, retries: int = 0) -> ToolResult:
        """retries：只对 timeout 类别做有界重试（W1 工具只读；W2 的写工具不能照搬）。每次尝试都记事件。"""
        # I2：先落日志再执行，被拒绝的也要记
        self._sink.emit("tool.requested", run_id=run_id, call_id=call.call_id, name=call.name, arguments=call.arguments)
        tool = self._registry.get(call.name)
        if tool is None:
            err = ToolError("unknown_tool", "unknown_tool", f"工具 {call.name} 未注册")
            self._sink.emit("tool.rejected", run_id=run_id, call_id=call.call_id, name=call.name, category=err.category, code=err.code)
            return ToolResult(call.call_id, call.name, ok=False, error=err)
        try:
            args = validate_args(tool.spec, call.arguments)   # W1-AC-02：不合法参数不触发 ERP 请求
        except ToolFailure as f:
            self._sink.emit("tool.rejected", run_id=run_id, call_id=call.call_id, name=call.name, category=f.error.category, code=f.error.code)
            return ToolResult(call.call_id, call.name, ok=False, error=f.error)
        attempt = 0
        while True:
            attempt += 1
            t0 = time.monotonic()
            try:
                data = tool.run(args, timeout_s=timeout_s)
            except ToolFailure as f:
                ms = int((time.monotonic() - t0) * 1000)
                if f.error.category == "timeout" and attempt <= retries:
                    self._sink.emit("tool.retry", run_id=run_id, call_id=call.call_id, name=call.name,
                                    attempt=attempt, code=f.error.code, duration_ms=ms)
                    continue
                self._sink.emit("tool.executed", run_id=run_id, call_id=call.call_id, name=call.name, ok=False,
                                category=f.error.category, code=f.error.code, attempts=attempt, duration_ms=ms)
                return ToolResult(call.call_id, call.name, ok=False, error=f.error)
            self._sink.emit("tool.executed", run_id=run_id, call_id=call.call_id, name=call.name, ok=True,
                            attempts=attempt, duration_ms=int((time.monotonic() - t0) * 1000))
            return ToolResult(call.call_id, call.name, ok=True, data=data)
