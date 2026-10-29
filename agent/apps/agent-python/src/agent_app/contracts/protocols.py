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
    """ERP 业务系统访问。第一阶段只启用了只读操作方法。"""
    def get_product(self, sku: str, *, timeout_s: float) -> dict: ...
    def get_inventory(self, sku: str, qty: int, *, timeout_s: float) -> dict: ...
    def get_shipment(self, tracking_no: str, *, timeout_s: float) -> dict: ...
    def get_order(self, order_id: str, *, timeout_s: float) -> dict: ...
    def list_orders(
        self,
        *,
        customer_id: str | None = None,
        status: str | None = None,
        sku: str | None = None,
        limit: int = 50,
        timeout_s: float,
    ) -> dict: ...
    def search_customers(self, query: str | None = None, *, limit: int = 10, timeout_s: float) -> dict: ...
    def get_customer(self, customer_id: str, *, timeout_s: float) -> dict: ...
    def get_receivables(self, customer_id: str, *, timeout_s: float) -> dict: ...
    def search_products(
        self,
        *,
        category: str | None = None,
        flow_lpm: float | None = None,
        pressure_bar: float | None = None,
        head_m: float | None = None,
        cooling_w: float | None = None,
        setpoint_c: float | None = None,
        measure_bar: float | None = None,
        measure_m: float | None = None,
        ambient_c: float | None = None,
        timeout_s: float,
    ) -> dict: ...
    def price_quote(self, customer_id: str, lines: str, *, timeout_s: float) -> dict: ...


@runtime_checkable
class Tool(Protocol):
    spec: ToolSpec
    def run(self, args: dict, *, timeout_s: float) -> dict: ...


@runtime_checkable
class EventSink(Protocol):
    def emit(self, event_type: str, **data) -> None: ...
