"""工具层：每个工具一文件，带 ToolSpec；注册表只认名字；执行器负责查、验、执、回。"""
from .registry import ToolExecutor, ToolRegistry

__all__ = ["ToolExecutor", "ToolRegistry"]
