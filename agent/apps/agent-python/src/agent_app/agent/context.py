"""ContextBuilder：指令 + 历史 + 本次输入。只组装，不保存权威事实。"""
from __future__ import annotations

# cache: 06G7a 05C3a
DEFAULT_SYSTEM = (
    "你是深维工作台的数字员工，帮跨境设备业务员查事实并用中文简洁作答。\n"
    "规则：规格、库存、交期只能来自工具结果；工具返回 ok=false 时如实说明无法确认，不要把失败说成库存为零；"
    "型号不明先追问，不要猜；不复述原始 JSON。库存是时点数据，回答时带上观测时间。"
)


class ContextBuilder:
    def __init__(self, system_prompt: str = DEFAULT_SYSTEM) -> None:
        self.system_prompt = system_prompt

    def build(self, history: list[dict] | None, user_input: str) -> list[dict]:
        msgs: list[dict] = [{"role": "system", "content": self.system_prompt}]
        msgs.extend(history or [])
        msgs.append({"role": "user", "content": user_input})
        return msgs
