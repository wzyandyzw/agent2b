"""FakeERP：固定数据 + 调用计数 + 故障开关。实现 ErpGateway，和真实 ErpClient 可互换。"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from agent_app.contracts import ToolFailure


@dataclass
class FakeERP:
    products: dict[str, dict] = field(default_factory=dict)
    inventory: dict[str, dict] = field(default_factory=dict)
    shipments: dict[str, dict] = field(default_factory=dict)
    orders: dict[str, dict] = field(default_factory=dict)
    faults: dict[str, ToolFailure] = field(default_factory=dict)   # 按方法名注入：{"get_inventory": ToolFailure(...)}
    fault_times: dict[str, int] = field(default_factory=dict)      # 注入几次；缺省一直
    calls: Counter = field(default_factory=Counter)

    def inject(self, method: str, failure: ToolFailure, times: int | None = None) -> None:
        self.faults[method] = failure
        if times is not None:
            self.fault_times[method] = times

    def _maybe_fail(self, method: str) -> None:
        if method not in self.faults:
            return
        left = self.fault_times.get(method)
        if left is not None:
            if left <= 0:
                return
            self.fault_times[method] = left - 1
        raise self.faults[method]

    def _lookup(self, method: str, table: dict, key: str, code: str, what: str) -> dict:
        self.calls[method] += 1
        self._maybe_fail(method)
        if key.upper() not in {k.upper() for k in table}:
            raise ToolFailure("not_found", code, f"{what} {key} 不存在")
        return next(v for k, v in table.items() if k.upper() == key.upper())

    def get_product(self, sku: str, *, timeout_s: float) -> dict:
        return self._lookup("get_product", self.products, sku, "product_not_found", "型号")

    def get_inventory(self, sku: str, qty: int, *, timeout_s: float) -> dict:
        data = dict(self._lookup("get_inventory", self.inventory, sku, "product_not_found", "型号"))
        data["requested_qty"] = qty
        return data

    def get_shipment(self, tracking_no: str, *, timeout_s: float) -> dict:
        return self._lookup("get_shipment", self.shipments, tracking_no, "shipment_not_found", "运单")

    def get_order(self, order_id: str, *, timeout_s: float) -> dict:
        return self._lookup("get_order", self.orders, order_id, "order_not_found", "订单")

    @staticmethod
    def timeout(method: str = "get_inventory") -> ToolFailure:
        return ToolFailure("timeout", "gateway_timeout", f"ERP {method} 超时")
