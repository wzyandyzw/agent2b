"""规格解析与按工况筛型号。

商品主数据的 key_spec 是一段中文文本（"260 W；最大流量 5 L/min；最大压力 2 bar；IP54"）。这里把能解析的数值抽成 specs 字段，
解析不出的留 null。选型接口只按主数据做硬筛（"候选来自系统、推荐来自模型"），运行边界以手册为准。
"""
from __future__ import annotations

import re

# generated: 0cTb2 0bJ88
NUM = r"(-?\d+(?:\.\d+)?)"
RANGE = rf"{NUM}\s*[–\-~]\s*{NUM}"

HS_CODES = {   # 课程虚构但按真实税号大类给：泵 8413、冷水机 8418、压力/流量/液位仪表 9026、温度仪表 9025、阀 8481、变频柜 8537、换热器 8419、过滤器 8421
    "X": "8413.70", "GP": "8413.60", "MP": "8413.70", "RP": "8413.60", "QP": "8413.50", "DP": "8413.50",
    "T": "8418.69", "S": "9026.20", "FM": "9026.10", "LS": "9026.10", "TS": "9025.19",
    "VA": "8481.80", "VC": "8537.10", "HX": "8419.50", "FL": "8421.29",
}


def parse_specs(key_spec: str, connection: str | None, power: str | None, weight_kg: float | None) -> dict:
    s = {"power_w": None, "cooling_capacity_w": None, "max_flow_lpm": None, "max_pressure_bar": None, "max_head_m": None,
         "range_bar_min": None, "range_bar_max": None, "range_m_min": None, "range_m_max": None,
         "setpoint_min_c": None, "setpoint_max_c": None, "stability_c": None, "tank_l": None,
         "operating_temp_min_c": None, "operating_temp_max_c": None, "accuracy_fs_pct": None, "output": None,
         "ip_rating": None, "high_temp_hours": None, "nominal_size_dn": None, "air_supply_bar_min": None, "air_supply_bar_max": None,
         "insertion_mm": None, "sensor_type": None, "wiring": None,
         "connection": connection or None, "supply_voltage": power or None, "weight_kg": weight_kg}
    for seg in [x.strip() for x in re.split(r"[；;]", key_spec or "") if x.strip()]:
        if m := re.fullmatch(rf"{NUM}\s*W", seg):
            s["power_w"] = float(m[1])
        elif m := re.search(rf"制冷量\s*{NUM}\s*W", seg):
            s["cooling_capacity_w"] = float(m[1])
        elif m := re.search(rf"最大流量\s*{NUM}\s*L/min", seg):
            s["max_flow_lpm"] = float(m[1])
        elif m := re.search(rf"最大流量\s*{NUM}\s*m[³3]/h", seg):
            s["max_flow_lpm"] = round(float(m[1]) * 1000 / 60, 1)
        elif m := re.search(rf"最大压力\s*{NUM}\s*bar", seg):
            s["max_pressure_bar"] = float(m[1])
        elif m := re.search(rf"最大扬程\s*{NUM}\s*m", seg):
            s["max_head_m"] = float(m[1])
        elif m := re.search(rf"设定\s*{RANGE}\s*°C", seg):
            s["setpoint_min_c"], s["setpoint_max_c"] = float(m[1]), float(m[2])
        elif m := re.search(rf"稳定度\s*±?{NUM}\s*°C", seg):
            s["stability_c"] = float(m[1])
        elif m := re.search(rf"水箱\s*{NUM}\s*L", seg):
            s["tank_l"] = float(m[1])
        elif m := re.search(rf"气源\s*{RANGE}\s*bar", seg):
            s["air_supply_bar_min"], s["air_supply_bar_max"] = float(m[1]), float(m[2])
        elif m := re.fullmatch(rf"{RANGE}\s*bar", seg):
            s["range_bar_min"], s["range_bar_max"] = float(m[1]), float(m[2])
        elif m := re.fullmatch(rf"{RANGE}\s*m", seg):
            s["range_m_min"], s["range_m_max"] = float(m[1]), float(m[2])
        elif m := re.fullmatch(rf"{RANGE}\s*°C", seg):
            s["operating_temp_min_c"], s["operating_temp_max_c"] = float(m[1]), float(m[2])
        elif m := re.search(rf"{NUM}\s*%\s*FS", seg):
            s["accuracy_fs_pct"] = float(m[1])
        elif re.search(r"4\s*[–\-]\s*20\s*mA", seg):
            s["output"] = "4-20 mA"
        elif m := re.fullmatch(r"IP(\d{2})", seg):
            s["ip_rating"] = f"IP{m[1]}"
        elif m := re.search(rf"高温时长\s*{NUM}\s*h", seg):
            s["high_temp_hours"] = float(m[1])
        elif m := re.search(r"口径\s*DN(\d+)", seg):
            s["nominal_size_dn"] = int(m[1])
        elif m := re.search(rf"插深\s*{NUM}\s*mm", seg):
            s["insertion_mm"] = float(m[1])
        elif seg.startswith("Pt100"):
            s["sensor_type"] = "Pt100"
        elif "三线制" in seg:
            s["wiring"] = "3-wire"
    return s


# 选型参数 → (规格字段, 判定方式)。ge：规格 ≥ 要求；range：规格区间覆盖要求值
SELECTION_PARAMS = {
    "flow_lpm": ("max_flow_lpm", "ge", "最大流量 L/min"),
    "pressure_bar": ("max_pressure_bar", "ge", "最大压力 bar"),
    "head_m": ("max_head_m", "ge", "最大扬程 m"),
    "cooling_w": ("cooling_capacity_w", "ge", "制冷量 W"),
    "setpoint_c": (("setpoint_min_c", "setpoint_max_c"), "range", "设定温度范围 °C"),
    "measure_bar": (("range_bar_min", "range_bar_max"), "range", "压力量程 bar"),
    "measure_m": (("range_m_min", "range_m_max"), "range", "液位量程 m"),
    "ambient_c": (("operating_temp_min_c", "operating_temp_max_c"), "range", "工作温度范围 °C"),
}


def select(products: list[dict], wants: dict[str, float]) -> list[dict]:
    out = []
    for p in products:
        sp = p["specs"]
        checks, applicable = [], True
        for param, val in wants.items():
            field, how, label = SELECTION_PARAMS[param]
            if how == "ge":
                actual = sp.get(field)
                if actual is None:
                    applicable = False
                    break
                checks.append({"param": param, "label": label, "required": val, "actual": actual, "ok": actual >= val})
            else:
                lo, hi = sp.get(field[0]), sp.get(field[1])
                if lo is None or hi is None:
                    applicable = False
                    break
                checks.append({"param": param, "label": label, "required": val, "actual": [lo, hi], "ok": lo <= val <= hi})
        if not applicable:
            continue
        out.append({"sku": p["sku"], "name_en": p["name_en"], "category_code": p["category_code"],
                    "list_price": {"amount": p["list_price_cny"], "currency": "CNY"}, "lifecycle": p["lifecycle"],
                    "meets_all": all(c["ok"] for c in checks), "checks": checks, "doc_ref": p["doc_ref"]})
    out.sort(key=lambda c: (not c["meets_all"], c["list_price"]["amount"]))
    return out
