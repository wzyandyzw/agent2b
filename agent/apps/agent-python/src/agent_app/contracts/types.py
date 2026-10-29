"""W1 的最小类型。消息本身用 OpenAI chat 格式的 dict（role / content / tool_calls / tool_call_id），
这样在事件快照里看到的就是真正发给模型的东西。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum


class ResponseKind(StrEnum):
    FINAL = "final"            # 有效最终文本
    TOOL_CALLS = "tool_calls"  # 至少一个工具请求（可能伴随文本，先处理工具请求）
    MALFORMED = "malformed"    # 无文本也无工具请求、或无法解析：协议失败，不是"完成"


class StopReason(StrEnum):
    COMPLETED = "completed"            # 得到有效最终答复
    MAX_STEPS = "max_steps"            # 步数耗尽，不再发起新的模型请求
    WALL_CLOCK = "wall_clock"          # 墙钟耗尽
    PROTOCOL_ERROR = "protocol_error"  # 模型响应结构异常
    MODEL_ERROR = "model_error"        # 模型调用 / 网络失败


class RunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"  # 只表示循环得到有效结束响应，不证明业务内容正确
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(frozen=True)
class ToolSpec:
    """给模型看的工具说明。parameters 是 JSON Schema（object）。"""
    name: str
    description: str
    parameters: dict

    def to_openai(self) -> dict:
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                                                 "parameters": self.parameters}}


@dataclass(frozen=True)
class ToolCall:
    """模型提出的一个工具请求。arguments 保留模型给的原始字符串：解析与校验是宿主的事。"""
    call_id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class ToolError:
    """工具失败的分类。category 是程序分支依据，code 是上游机器码，message 给模型 / 人看。"""
    category: str  # unknown_tool | input_error | not_found | timeout | upstream_error | malformed
    code: str
    message: str


@dataclass
class ToolResult:
    """带着同一个 call_id 回去的结果。ok=False 时 data 为空、error 必填；错误不是事实。"""
    call_id: str
    name: str
    ok: bool
    data: dict | None = None
    error: ToolError | None = None

    def content(self) -> str:
        body = {"ok": self.ok, "data": self.data} if self.ok else \
               {"ok": False, "error": {"category": self.error.category, "code": self.error.code,
                                       "message": self.error.message}}
        return json.dumps(body, ensure_ascii=False)

    def to_message(self) -> dict:
        return {"role": "tool", "tool_call_id": self.call_id, "name": self.name, "content": self.content()}


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None

    @property
    def unknown(self) -> bool:
        return self.total_tokens is None


@dataclass
class ModelResponse:
    """归一化后的模型响应。raw 保留原始 JSON 用于事件快照。"""
    kind: ResponseKind
    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage | None = None
    finish_reason: str | None = None
    raw: dict | None = None

    def to_assistant_message(self) -> dict:
        msg: dict = {"role": "assistant", "content": self.text or ""}
        if self.tool_calls:
            msg["tool_calls"] = [{"id": c.call_id, "type": "function",
                                  "function": {"name": c.name, "arguments": c.arguments}} for c in self.tool_calls]
        return msg


@dataclass(frozen=True)
class Budget:
    max_steps: int = 6            # 模型请求次数上限
    model_timeout_s: float = 60.0
    tool_timeout_s: float = 5.0
    wall_clock_s: float = 120.0
    tool_retries: int = 0         # 只读工具超时的有界重试；重试计入预算（1.8 起）


@dataclass
class RunResult:
    run_id: str
    status: RunStatus
    stop_reason: StopReason | None
    answer: str | None
    steps: int
    messages: list[dict]
    usage: Usage = field(default_factory=Usage)
    usage_unknown: bool = False
