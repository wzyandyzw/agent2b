"""四个边界。换模型只改 ModelClient 的实现；换 ERP 只改 ErpGateway 的实现；
CLI 换网页只换调用方；不联网测 Loop 用 doubles 里的替身实现同一组 Protocol。"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from .types import ModelResponse, ToolError, ToolSpec


class ToolFailure(Exception):
    """工具内部用来向执行层报告失败；执行层把它变成 ToolResult(ok=False)。"""

    def __init__(self, category: str, code: str, message: str) -> None:
        super().__init__(message)
        self.error = ToolError(category=category, code=code, message=message)


@runtime_checkable
class ModelClient(Protocol):
    def generate(self, messages: list[dict], tools: list[ToolSpec], *, timeout_s: float) -> ModelResponse: ...


@runtime_checkable
class ErpGateway(Protocol):
    """ERP 只读访问。真实实现走 HTTP；FakeERP 读 fixture。失败抛 ToolFailure。"""
    def get_product(self, sku: str, *, timeout_s: float) -> dict: ...
    def get_inventory(self, sku: str, qty: int, *, timeout_s: float) -> dict: ...
    def get_shipment(self, tracking_no: str, *, timeout_s: float) -> dict: ...
    def get_order(self, order_id: str, *, timeout_s: float) -> dict: ...


@runtime_checkable
class Tool(Protocol):
    spec: ToolSpec
    def run(self, args: dict, *, timeout_s: float) -> dict: ...


@runtime_checkable
class EventSink(Protocol):
    def emit(self, event_type: str, **data) -> None: ...
