"""Order lookup tools backed by the ERP mock."""
from __future__ import annotations

from agent_app.contracts import ErpGateway, ToolSpec


GET_SPEC = ToolSpec(
    name="get_order",
    description="按订单号读取客户、订单行、金额、状态、承诺交期、运单号和备注。只读。",
    parameters={
        "type": "object",
        "properties": {"order_id": {"type": "string", "description": "订单号，如 ORD-10086"}},
        "required": ["order_id"],
        "additionalProperties": False,
    },
)

LIST_SPEC = ToolSpec(
    name="list_orders",
    description="按客户、状态或产品型号查询近期订单摘要。只读。",
    parameters={
        "type": "object",
        "properties": {
            "customer_id": {"type": "string", "description": "可选客户编号"},
            "status": {
                "type": "string",
                "description": "可选订单状态：confirmed、partially_shipped、shipped、delivered、closed、cancelled",
            },
            "sku": {"type": "string", "description": "可选产品型号"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        },
        "additionalProperties": False,
    },
)


class GetOrder:
    spec = GET_SPEC

    def __init__(self, erp: ErpGateway) -> None:
        self._erp = erp

    def run(self, args: dict, *, timeout_s: float) -> dict:
        order = self._erp.get_order(args["order_id"], timeout_s=timeout_s)
        return {
            "order_id": order.get("id"),
            "customer_id": order.get("customer_id"),
            "customer_name": (order.get("customer") or {}).get("legal_name"),
            "order_date": order.get("order_date"),
            "promised_delivery_date": order.get("promised_delivery_date"),
            "status": order.get("status"),
            "currency": order.get("currency"),
            "total_amount": order.get("total_amount"),
            "payment_terms_code": order.get("payment_terms_code"),
            "incoterm": order.get("incoterm"),
            "lines": order.get("lines", []),
            "shipments": order.get("shipments", []),
            "note": order.get("note"),
            "updated_at": order.get("updated_at"),
        }


class ListOrders:
    spec = LIST_SPEC

    def __init__(self, erp: ErpGateway) -> None:
        self._erp = erp

    def run(self, args: dict, *, timeout_s: float) -> dict:
        page = self._erp.list_orders(
            customer_id=args.get("customer_id"),
            status=args.get("status"),
            sku=args.get("sku"),
            limit=int(args.get("limit") or 20),
            timeout_s=timeout_s,
        )
        orders = [
            {
                "order_id": o.get("id"),
                "customer_id": o.get("customer_id"),
                "customer_name": (o.get("customer") or {}).get("legal_name"),
                "order_date": o.get("order_date"),
                "promised_delivery_date": o.get("promised_delivery_date"),
                "status": o.get("status"),
                "currency": o.get("currency"),
                "total_amount": o.get("total_amount"),
                "shipments": o.get("shipments", []),
            }
            for o in page.get("data", [])
        ]
        return {
            "orders": orders,
            "count": len(orders),
            "has_more": page.get("has_more", False),
            "observed_at": page.get("as_of"),
        }
