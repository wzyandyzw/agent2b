"""get_shipment：按运单号查物流。权威事实 = ERP /v1/shipments/{tracking_no}。1.9 跟做的第三个工具。"""
from __future__ import annotations

from agent_app.contracts import ErpGateway, ToolSpec

SPEC = ToolSpec(
    name="get_shipment",
    description="按运单号查物流：承运商、最新状态、最后更新时间与位置、事件时间线。只读；物流停更时如实给最后更新时间。",
    parameters={"type": "object",
                "properties": {"tracking_no": {"type": "string", "description": "运单号，如 SF1234567890"}},
                "required": ["tracking_no"], "additionalProperties": False},
)


class GetShipment:
    spec = SPEC

    def __init__(self, erp: ErpGateway) -> None:
        self._erp = erp

    def run(self, args: dict, *, timeout_s: float) -> dict:
        s = self._erp.get_shipment(args["tracking_no"], timeout_s=timeout_s)
        return {
            "tracking_no": s["tracking_no"], "order_id": s.get("order_id"), "carrier": s.get("carrier"),
            "mode": s.get("mode"), "ship_date": s.get("ship_date"),
            "status_code": s.get("status_code"), "status_text": s.get("status_text"),
            "signed": s.get("signed"), "signed_at": s.get("signed_at"), "last_event_at": s.get("last_event_at"),
            "events": [{"at": e.get("at"), "status_code": e.get("status_code"), "status_text": e.get("status_text"),
                        "location": e.get("location")} for e in s.get("events", [])],
        }
