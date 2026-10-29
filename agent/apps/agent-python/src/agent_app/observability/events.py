"""事件：追加写的执行事实。记请求、响应、调用、结果和停止；不记 API Key 与鉴权头；不是模型的思维链。"""
from __future__ import annotations

import datetime as dt
import json
import pathlib


def _now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="milliseconds")


class ListSink:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def emit(self, event_type: str, **data) -> None:
        self.events.append({"seq": len(self.events) + 1, "ts": _now(), "type": event_type, **data})


class JsonlSink:
    """一次会话一个文件，每行一个事件。文件只追加。"""

    def __init__(self, path: str | pathlib.Path) -> None:
        self.path = pathlib.Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._seq = sum(1 for _ in self.path.open(encoding="utf-8")) if self.path.exists() else 0

    def emit(self, event_type: str, **data) -> None:
        self._seq += 1
        line = json.dumps({"seq": self._seq, "ts": _now(), "type": event_type, **data}, ensure_ascii=False)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def read_events(path: str | pathlib.Path) -> tuple[list[dict], list[str]]:
    """读事件文件；坏行不抛，记进 problems。"""
    events, problems = [], []
    for i, line in enumerate(pathlib.Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            problems.append(f"第 {i} 行不是完整 JSON（写到一半中断？）")
    return events, problems
