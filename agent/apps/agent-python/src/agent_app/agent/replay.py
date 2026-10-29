"""只读回放：读事件文件，还原发生过什么，指出缺失或损坏。不调用模型，不调用工具——函数签名里就没有它们。"""
from __future__ import annotations

import pathlib
from dataclasses import dataclass, field

from agent_app.observability import read_events


@dataclass
class ReplayStep:
    run_id: str
    step: int
    request_messages: int
    response_kind: str | None = None
    tool_calls: list[dict] = field(default_factory=list)   # {call_id, name, outcome}
    text: str | None = None


@dataclass
class ReplayReport:
    runs: list[str]
    steps: list[ReplayStep]
    stops: list[dict]
    gaps: list[str]
    problems: list[str]

    @property
    def external_calls_made(self) -> int:
        return 0   # 回放永远不发起外部调用；这里是给读者看的常量


def replay(events_path: str | pathlib.Path) -> ReplayReport:
    events, problems = read_events(events_path)
    runs, steps, stops, gaps = [], [], [], []
    open_steps: dict[tuple[str, int], ReplayStep] = {}
    pending_calls: dict[str, ReplayStep] = {}
    for e in events:
        t, rid = e["type"], e.get("run_id", "?")
        if t == "run.started":
            runs.append(rid)
        elif t == "model.request":
            st = ReplayStep(rid, e["step"], len(e["snapshot"]["messages"]))
            open_steps[(rid, e["step"])] = st
            steps.append(st)
        elif t == "model.response":
            st = open_steps.get((rid, e["step"]))
            if st is None:
                gaps.append(f"{rid} 第 {e['step']} 步有响应但没有请求记录")
                continue
            st.response_kind, st.text = e["kind"], e.get("text")
            for c in e.get("tool_calls", []):
                st.tool_calls.append({"call_id": c["call_id"], "name": c["name"], "outcome": "requested"})
                pending_calls[c["call_id"]] = st
        elif t in ("tool.executed", "tool.rejected"):
            st = pending_calls.pop(e["call_id"], None)
            if st is None:
                gaps.append(f"工具结果 {e['call_id']} 找不到对应的模型请求")
                continue
            for c in st.tool_calls:
                if c["call_id"] == e["call_id"]:
                    c["outcome"] = "ok" if e.get("ok") else f"{e.get('category')}/{e.get('code')}"
        elif t in ("run.completed", "run.stopped", "run.failed"):
            stops.append({"run_id": rid, "type": t, "stop_reason": e.get("stop_reason"), "steps": e.get("steps")})
    for (rid, n), st in open_steps.items():
        if st.response_kind is None:
            gaps.append(f"{rid} 第 {n} 步发出了模型请求但没有响应记录（中断在这里）")
    for cid, st in pending_calls.items():
        gaps.append(f"{st.run_id} 第 {st.step} 步的工具调用 {cid} 没有执行记录")
    for rid in runs:
        if not any(s["run_id"] == rid for s in stops):
            gaps.append(f"{rid} 没有停止记录")
    return ReplayReport(runs, steps, stops, gaps, problems)
