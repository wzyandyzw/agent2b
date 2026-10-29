"""Customer and receivable tools backed by the ERP mock."""
from __future__ import annotations

from agent_app.contracts import ErpGateway, ToolFailure, ToolSpec


FIND_SPEC = ToolSpec(
    name="find_customer",
    description="按公司名、城市、联系人、编号或关键词查找客户。只读。",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "客户名称、城市、联系人或编号"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 20},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
)

GET_SPEC = ToolSpec(
    name="get_customer",
    description="按客户编号读取客户资料、联系人、信用额度和付款条件。只读。",
    parameters={
        "type": "object",
        "properties": {"customer_id": {"type": "string", "description": "客户编号，如 C-E001"}},
        "required": ["customer_id"],
        "additionalProperties": False,
    },
)

RECEIVABLES_SPEC = ToolSpec(
    name="get_receivables",
    description="读取客户应收余额、信用状态、逾期天数和未清发票。只读。",
    parameters={
        "type": "object",
        "properties": {"customer_id": {"type": "string", "description": "客户编号，如 C-E003"}},
        "required": ["customer_id"],
        "additionalProperties": False,
    },
)


class FindCustomer:
    spec = FIND_SPEC

    def __init__(self, erp: ErpGateway) -> None:
        self._erp = erp

    def run(self, args: dict, *, timeout_s: float) -> dict:
        page = self._erp.search_customers(
            args["query"], limit=int(args.get("limit") or 5), timeout_s=timeout_s
        )
        customers = [
            {
                "customer_id": c.get("id"),
                "name": c.get("legal_name") or c.get("short_name"),
                "country": c.get("country_code"),
                "city": c.get("city"),
                "industry": c.get("industry"),
                "salesperson": c.get("salesperson"),
            }
            for c in page.get("data", [])
        ]
        if not customers:
            raise ToolFailure("not_found", "customer_not_found", f"没有找到匹配“{args['query']}”的客户")
        return {"customers": customers, "count": len(customers), "has_more": page.get("has_more", False)}


class GetCustomer:
    spec = GET_SPEC

    def __init__(self, erp: ErpGateway) -> None:
        self._erp = erp

    def run(self, args: dict, *, timeout_s: float) -> dict:
        c = self._erp.get_customer(args["customer_id"], timeout_s=timeout_s)
        return {
            "customer_id": c.get("id"),
            "name": c.get("legal_name"),
            "short_name": c.get("short_name"),
            "country": c.get("country_code"),
            "city": c.get("city"),
            "industry": c.get("industry"),
            "salesperson": c.get("salesperson"),
            "contacts": c.get("contacts", []),
            "payment_terms": c.get("payment_terms"),
            "payment_terms_code": c.get("payment_terms_code"),
            "credit": c.get("credit", {}),
            "blocked": c.get("blocked"),
            "note": c.get("note"),
            "updated_at": c.get("updated_at"),
        }


class GetReceivables:
    spec = RECEIVABLES_SPEC

    def __init__(self, erp: ErpGateway) -> None:
        self._erp = erp

    def run(self, args: dict, *, timeout_s: float) -> dict:
        return self._erp.get_receivables(args["customer_id"], timeout_s=timeout_s)
