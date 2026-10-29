"""get_availability：库存与交期。权威事实 = ERP /v1/inventory/{sku}?qty=。库存是时点数据，带观测时间。"""
from __future__ import annotations

from agent_app.contracts import ErpGateway, ToolSpec

SPEC = ToolSpec(
    name="get_availability",
    description="按型号查当前库存与交期：可用量、在途、整单最早发运日（深圳发运，不含国际运输）、依据。只读，时点数据。",
    parameters={"type": "object",
                "properties": {"model": {"type": "string", "description": "型号"},
                               "qty": {"type": "integer", "minimum": 1, "description": "需要的数量，默认 1"}},
                "required": ["model"], "additionalProperties": False},
)


class GetAvailability:
    spec = SPEC

    def __init__(self, erp: ErpGateway) -> None:
        self._erp = erp

    def run(self, args: dict, *, timeout_s: float) -> dict:
        inv = self._erp.get_inventory(args["model"], int(args.get("qty") or 1), timeout_s=timeout_s)
        return {
            "model": inv["sku"], "warehouse": inv.get("warehouse"), "requested_qty": inv.get("requested_qty"),
            "on_hand": inv.get("on_hand"), "reserved": inv.get("reserved"), "available": inv.get("available"),
            "incoming": inv.get("incoming", []),
            "earliest_ship_date": inv.get("earliest_ship_date"), "complete_ship_date": inv.get("complete_ship_date"),
            "basis_code": inv.get("basis_code"), "basis_text": inv.get("basis_text"),
            "schedule_lines": inv.get("schedule_lines", []), "incoterm": inv.get("incoterm"),
            "observed_at": inv.get("as_of"),
        }
