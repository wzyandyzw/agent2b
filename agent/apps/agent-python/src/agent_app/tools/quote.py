"""Product selection and rule-based quote calculation."""
from __future__ import annotations

from agent_app.contracts import ErpGateway, ToolSpec


SEARCH_SPEC = ToolSpec(
    name="search_products",
    description="按工况参数筛选在售产品，返回候选型号和逐项匹配结果。只读。",
    parameters={
        "type": "object",
        "properties": {
            "category": {"type": "string", "description": "可选产品类别代码，如 X、T、S、FL"},
            "flow_lpm": {"type": "number", "minimum": 0},
            "pressure_bar": {"type": "number", "minimum": 0},
            "head_m": {"type": "number", "minimum": 0},
            "cooling_w": {"type": "number", "minimum": 0},
            "setpoint_c": {"type": "number"},
            "measure_bar": {"type": "number", "minimum": 0},
            "measure_m": {"type": "number", "minimum": 0},
            "ambient_c": {"type": "number"},
        },
        "additionalProperties": False,
    },
)

QUOTE_SPEC = ToolSpec(
    name="price_quote",
    description="按客户、产品型号和数量计算报价；金额只能由 ERP 规程计算，只计算不落账。",
    parameters={
        "type": "object",
        "properties": {
            "customer_id": {"type": "string", "description": "客户编号"},
            "lines": {
                "type": "string",
                "description": "报价行，格式 SKU:数量，多项用逗号分隔，例如 X200-Pro:2,S10:4",
            },
        },
        "required": ["customer_id", "lines"],
        "additionalProperties": False,
    },
)


class SearchProducts:
    spec = SEARCH_SPEC

    def __init__(self, erp: ErpGateway) -> None:
        self._erp = erp

    def run(self, args: dict, *, timeout_s: float) -> dict:
        result = self._erp.search_products(timeout_s=timeout_s, **args)
        candidates = [
            {
                "sku": c.get("sku"),
                "name": c.get("name_en"),
                "meets_all": c.get("meets_all"),
                "checks": c.get("checks", []),
                "list_price": c.get("list_price"),
                "doc_ref": c.get("doc_ref"),
            }
            for c in result.get("candidates", [])
        ]
        return {
            "criteria": result.get("criteria"),
            "candidates": candidates,
            "meets_all_count": result.get("meets_all_count"),
            "note": result.get("note"),
        }


class PriceQuote:
    spec = QUOTE_SPEC

    def __init__(self, erp: ErpGateway) -> None:
        self._erp = erp

    def run(self, args: dict, *, timeout_s: float) -> dict:
        return self._erp.price_quote(args["customer_id"], args["lines"], timeout_s=timeout_s)
