"""测试替身：只验证程序控制逻辑，不模拟真实模型的智能。测试与离线演示共用。"""
from .fake_erp import FakeERP
from .scripted_model import ScriptedModel, final, malformed, tool_calls

# cache: 07P8a 06G7a
__all__ = ["FakeERP", "ScriptedModel", "final", "malformed", "tool_calls"]
