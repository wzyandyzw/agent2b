"""get_product_spec：型号主数据与规格。权威事实 = ERP /v1/products/{sku}。"""
from __future__ import annotations

from agent_app.contracts import ErpGateway, ToolSpec

SPEC = ToolSpec(
    name="get_product_spec",
    description="按型号查产品规格与主数据（名称、类别、结构化参数、挂牌价、生命周期、交期天数、手册编号）。只读。",
    parameters={"type": "object",
                "properties": {"model": {"type": "string", "description": "型号，如 X200、X200-Pro、T200"}},
                "required": ["model"], "additionalProperties": False},
)


class GetProductSpec:
    spec = SPEC

    def __init__(self, erp: ErpGateway) -> None:
        self._erp = erp

    def run(self, args: dict, *, timeout_s: float) -> dict:
        p = self._erp.get_product(args["model"], timeout_s=timeout_s)
        return {
            "model": p["sku"], "name": p.get("name_cn"), "name_en": p.get("name_en"),
            "category": (p.get("category") or {}).get("name_cn"),
            "key_spec": p.get("key_spec"),
            "specs": {k: v for k, v in (p.get("specs") or {}).items() if v is not None},
            "list_price": p.get("list_price"), "lifecycle": p.get("lifecycle"),
            "lead_time_days": p.get("lead_time_days"), "doc_ref": p.get("doc_ref"),
            "spec_source": p.get("spec_source"), "source_version": p.get("updated_at"),
        }
