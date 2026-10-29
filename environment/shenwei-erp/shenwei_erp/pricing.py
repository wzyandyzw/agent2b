"""报价规程（课程虚构，对应 D18 的"按型号、客户等级、数量查价"）。

价格只由 ERP 算。调用方只能给 sku 与数量，给不了金额。算法不变，输出按"价格条件"逐层列出（SAP 条件技术的样子）：
  PR00  挂牌价（CNY）
  K007  客户等级折扣（A 12% / B 6% / C 0）
  ZQTY  数量折扣（≥5 台 3%，≥10 台 6%）
  ZFXR  汇率换算 CNY→USD（7.20）
"""
from __future__ import annotations

# generated: 0fR02 0eAeb
FX_CNY_PER_USD = 7.20
TIER_DISCOUNT = {"A": 0.88, "B": 0.94, "C": 1.00}
QTY_DISCOUNT = [(10, 0.94), (5, 0.97), (1, 1.00)]
QUOTE_VALID_DAYS = 30
INCOTERM = {"code": "FOB", "location": "Shenzhen"}
INCOTERM_TEXT = "FOB Shenzhen"
RULE_REF = "报价规程 v2026.1 第 3 条"
CREDIT_LIMIT = {"A": 50000.0, "B": 20000.0, "C": 5000.0}   # 课程虚构：按客户等级给信用额度（USD）

PAYMENT_TERMS = {   # 代码 ↔ D43 五种付款条件原文
    "TT100_ADV": "100% T/T in advance",
    "TT30_70": "T/T 30% deposit, 70% before shipment",
    "TT50_50": "T/T 50% deposit, 50% before shipment",
    "LC_SIGHT": "L/C at sight",
    "NET30_BL": "Net 30 after B/L",
}
PAYMENT_TERMS_CODE = {v: k for k, v in PAYMENT_TERMS.items()}
PAYMENT_TERMS_DUE_DAYS = {"TT100_ADV": 0, "TT30_70": 0, "TT50_50": 0, "LC_SIGHT": 0, "NET30_BL": 30}


def qty_factor(qty: int) -> float:
    for threshold, f in QTY_DISCOUNT:
        if qty >= threshold:
            return f
    return 1.0


def unit_price_usd(list_price_cny: int, tier: str, qty: int) -> float:
    return round(list_price_cny * TIER_DISCOUNT.get(tier, 1.0) * qty_factor(qty) / FX_CNY_PER_USD, 2)


def price_lines(products: dict[str, dict], tier: str, lines: list[dict]) -> tuple[list[dict], float]:
    out, total = [], 0.0
    for i, ln in enumerate(lines, 1):
        p = products[ln["sku"]]
        qty = int(ln["qty"])
        tf, qf = TIER_DISCOUNT.get(tier, 1.0), qty_factor(qty)
        unit = unit_price_usd(p["list_price_cny"], tier, qty)
        sub = round(unit * qty, 2)
        total += sub
        out.append({"line_no": i, "sku": p["sku"], "name_en": p["name_en"], "qty": qty, "uom": p.get("uom", "EA"),
                    "list_price": {"amount": p["list_price_cny"], "currency": "CNY"},
                    "conditions": [
                        {"type": "PR00", "description": "挂牌价", "value": p["list_price_cny"], "currency": "CNY"},
                        {"type": "K007", "description": f"客户等级折扣（{tier} 级）", "rate": round(1 - tf, 2)},
                        {"type": "ZQTY", "description": "数量折扣", "rate": round(1 - qf, 2)},
                        {"type": "ZFXR", "description": "汇率换算 CNY→USD", "rate": FX_CNY_PER_USD},
                    ],
                    "unit_price": unit, "amount": sub})
    return out, round(total, 2)
