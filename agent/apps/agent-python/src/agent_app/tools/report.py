"""Save generated reports inside a dedicated artifact directory."""
from __future__ import annotations

import pathlib
import re

from agent_app.contracts import ToolFailure, ToolSpec


SPEC = ToolSpec(
    name="save_report",
    description="把整理好的 Markdown 报告保存到本地 artifacts 目录，返回文件路径。",
    parameters={
        "type": "object",
        "properties": {
            "filename": {"type": "string", "description": "文件名，只允许字母、数字、下划线、短横线和 .md 后缀"},
            "content": {"type": "string", "description": "完整 Markdown 内容"},
        },
        "required": ["filename", "content"],
        "additionalProperties": False,
    },
)


class SaveReport:
    spec = SPEC

    def __init__(self, root: str | pathlib.Path) -> None:
        self.root = pathlib.Path(root).resolve()

    def run(self, args: dict, *, timeout_s: float) -> dict:
        del timeout_s
        filename = args["filename"]
        if not re.fullmatch(r"[A-Za-z0-9_-]+\.md", filename):
            raise ToolFailure("input_error", "invalid_filename", "文件名只允许字母、数字、下划线和短横线，并以 .md 结尾")
        self.root.mkdir(parents=True, exist_ok=True)
        path = (self.root / filename).resolve()
        if path.parent != self.root:
            raise ToolFailure("input_error", "invalid_path", "报告路径越界")
        path.write_text(args["content"], encoding="utf-8")
        return {"saved": True, "path": str(path), "bytes": len(args["content"].encode("utf-8"))}
