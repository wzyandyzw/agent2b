"""ContextBuilder：指令 + 历史 + 本次输入。只组装，不保存权威事实。"""
from __future__ import annotations

DEFAULT_SYSTEM = (
    "你是汇甬新材的企业数字员工，面对面服务销售、售前、项目、采购、财务、售后和管理岗位。\n"
    "根据用户目标选择合适的已注册工具，必要时组合 ERP、客户、订单、应收、产品和知识检索结果。\n"
    "规则：业务事实只能来自工具结果或知识来源；工具返回 ok=false 时如实说明无法确认，不能编造库存、价格、交期、客户、案例或技术参数；"
    "关键信息不足时先追问；价格只能使用 price_quote 的结果；涉及对外发送、合同、报价落账或不可逆操作时只准备草稿并等待用户确认；"
    "回答使用中文，简洁、可执行，并保留必要的来源和时间。"
)


class ContextBuilder:
    def __init__(self, system_prompt: str = DEFAULT_SYSTEM) -> None:
        self.system_prompt = system_prompt

    def build(self, history: list[dict] | None, user_input: str) -> list[dict]:
        msgs: list[dict] = [{"role": "system", "content": self.system_prompt}]
        msgs.extend(history or [])
        msgs.append({"role": "user", "content": user_input})
        return msgs
