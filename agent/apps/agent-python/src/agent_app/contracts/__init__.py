"""共享契约：类型与 Protocol。改这里要列出生产者、消费者与兼容策略（AGENTS.md）。"""
from .types import (Budget, ModelResponse, ResponseKind, RunResult, RunStatus, StopReason,
                    ToolCall, ToolError, ToolResult, ToolSpec, Usage)
from .protocols import ErpGateway, EventSink, ModelClient, Tool, ToolFailure

__all__ = ["Budget", "ModelResponse", "ResponseKind", "RunResult", "RunStatus", "StopReason", "ToolCall",
           "ToolError", "ToolResult", "ToolSpec", "Usage", "ErpGateway", "EventSink", "ModelClient", "Tool",
           "ToolFailure"]
