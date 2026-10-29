"""Conversation：一段持久历史，可含多个 Run。继续会话 = 新 Run + 已保存的完整历史；不是恢复被杀的执行（那是 W6）。"""
from __future__ import annotations

import json
import pathlib
import uuid
from dataclasses import dataclass


@dataclass
class LoadedHistory:
    messages: list[dict]          # 不含 system；已裁到完整边界
    truncated: int = 0            # 丢掉了几条未配对的消息
    note: str | None = None


def complete_boundary(messages: list[dict]) -> LoadedHistory:
    """历史若停在未配对的工具调用处，裁回到最后一个完整边界，并报告。"""
    msgs = list(messages)
    dropped = 0
    while msgs:
        last = msgs[-1]
        if last["role"] == "tool":
            # 工具结果必须紧跟一条含同 id 的 assistant；找不到就丢
            ids = {tc["id"] for m in msgs[:-1] if m["role"] == "assistant" for tc in m.get("tool_calls", [])}
            if last.get("tool_call_id") in ids:
                # 还要确认该 assistant 的所有调用都已配对
                a_idx = max(i for i, m in enumerate(msgs[:-1]) if m["role"] == "assistant" and
                            any(tc["id"] == last.get("tool_call_id") for tc in m.get("tool_calls", [])))
                want = [tc["id"] for tc in msgs[a_idx]["tool_calls"]]
                got = [m.get("tool_call_id") for m in msgs[a_idx + 1:] if m["role"] == "tool"]
                if want == got:
                    break
                del msgs[a_idx:]
                dropped += 1 + len(got)
                continue
            msgs.pop(); dropped += 1; continue
        if last["role"] == "assistant" and last.get("tool_calls"):
            msgs.pop(); dropped += 1; continue   # 请求了工具但一个结果都没有
        break
    note = f"历史停在未配对的工具调用处，已裁掉 {dropped} 条，回到最后一个完整边界" if dropped else None
    return LoadedHistory(msgs, dropped, note)


class ConversationStore:
    def __init__(self, runs_dir: str | pathlib.Path) -> None:
        self.root = pathlib.Path(runs_dir)

    def new_id(self) -> str:
        return uuid.uuid4().hex[:8]

    def dir(self, conversation_id: str) -> pathlib.Path:
        return self.root / conversation_id

    def events_path(self, conversation_id: str) -> pathlib.Path:
        return self.dir(conversation_id) / "events.jsonl"

    def save(self, conversation_id: str, messages: list[dict]) -> None:
        d = self.dir(conversation_id)
        d.mkdir(parents=True, exist_ok=True)
        payload = [m for m in messages if m["role"] != "system"]
        (d / "history.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    def load(self, conversation_id: str) -> LoadedHistory:
        f = self.dir(conversation_id) / "history.json"
        if not f.exists():
            raise FileNotFoundError(f"会话 {conversation_id} 没有历史文件 {f}")
        return complete_boundary(json.loads(f.read_text(encoding="utf-8")))
