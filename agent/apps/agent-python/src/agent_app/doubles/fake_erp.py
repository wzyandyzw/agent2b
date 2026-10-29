"""FakeERP：固定数据 + 调用计数 + 故障开关。实现 ErpGateway，和真实 ErpClient 可互换。"""
from __future__ import annotations

import json
import pathlib
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

    @classmethod
    def from_fixtures(cls, fixtures_dir: str | pathlib.Path) -> "FakeERP":
        """读 scripts/record_fixtures.py 录下的 *.json；只装 200 的，404 样本留给契约测试用。"""
        erp = cls()
        for f in sorted(pathlib.Path(fixtures_dir).glob("*.json")):
            rec = json.loads(f.read_text(encoding="utf-8"))
            if rec["status"] != 200:
                continue
            body, path = rec["body"], rec["request"]["path"]
            if path.startswith("/v1/products/"):
                erp.products[body["sku"]] = body
            elif path.startswith("/v1/inventory/"):
                erp.inventory.setdefault(body["sku"], body)  # 同型号多份只留第一份；qty 由 get_inventory 覆盖
            elif path.startswith("/v1/shipments/"):
                erp.shipments[body["tracking_no"]] = body
            elif path.startswith("/v1/orders/"):
                erp.orders[body["id"]] = body
        return erp

    @staticmethod
    def timeout(method: str = "get_inventory") -> ToolFailure:
        return ToolFailure("timeout", "gateway_timeout", f"ERP {method} 超时")
