"""ScriptedModel：按脚本依次返回预设响应，并保存每次收到的请求。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from agent_app.contracts import ModelResponse, ResponseKind, ToolCall, ToolSpec, Usage


def final(text: str, *, usage: Usage | None = None) -> ModelResponse:
    return ModelResponse(kind=ResponseKind.FINAL, text=text, usage=usage, finish_reason="stop")


def tool_calls(*calls: tuple[str, dict | str], text: str | None = None, prefix: str = "call") -> ModelResponse:
    """calls: (name, arguments) … arguments 可以是 dict（自动转 JSON）或原始字符串（可故意非法）。"""
    tcs = []
    for i, (name, args) in enumerate(calls, 1):
        raw = args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)
        tcs.append(ToolCall(call_id=f"{prefix}_{i}", name=name, arguments=raw))
    return ModelResponse(kind=ResponseKind.TOOL_CALLS, text=text, tool_calls=tcs, finish_reason="tool_calls")


def malformed() -> ModelResponse:
    return ModelResponse(kind=ResponseKind.MALFORMED, text=None, tool_calls=[], finish_reason="stop",
                         raw={"choices": [{"message": {"role": "assistant", "content": None}}]})


@dataclass
class ScriptedModel:
    script: list[ModelResponse]
    repeat_last: bool = False                 # True：脚本用尽后一直返回最后一条（"永远请求工具"）
    requests: list[dict] = field(default_factory=list)
    calls: int = 0

    def generate(self, messages: list[dict], tools: list[ToolSpec], *, timeout_s: float) -> ModelResponse:
        self.calls += 1
        self.requests.append({"messages": json.loads(json.dumps(messages)),
                              "tools": [t.name for t in tools], "timeout_s": timeout_s})
        idx = self.calls - 1
        if idx >= len(self.script):
            if self.repeat_last and self.script:
                return self.script[-1]
            raise AssertionError(f"ScriptedModel 脚本只有 {len(self.script)} 条，第 {self.calls} 次请求超出")
        return self.script[idx]
