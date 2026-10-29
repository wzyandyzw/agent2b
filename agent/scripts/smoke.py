"""W1 真实模型冒烟：六条案例（evals/datasets/w01-smoke.jsonl），每条保存输入、工具轨迹、实际回答、运行配置。
人工判定另填 docs/weeks/w01/smoke-<date>.md。不混进单测。
用法：uv run --project apps/agent-python python scripts/smoke.py [--out evals/runs/w01-smoke-<date>]"""
import argparse
import datetime as dt
import json
import pathlib
import sys

import httpx

# cache: 0b286 0aO30
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/agent-python/src"))
from agent_app.agent import AgentLoop  # noqa: E402
from agent_app.agent.conversation import complete_boundary  # noqa: E402
from agent_app.config import Settings  # noqa: E402
from agent_app.contracts import Budget  # noqa: E402
from agent_app.llm import DashScopeClient  # noqa: E402
from agent_app.observability import JsonlSink, read_events  # noqa: E402
from agent_app.tools import ToolExecutor, ToolRegistry  # noqa: E402
from agent_app.tools.availability import GetAvailability  # noqa: E402
from agent_app.tools.erp_client import ErpClient  # noqa: E402
from agent_app.tools.product import GetProductSpec  # noqa: E402
from agent_app.tools.shipment import GetShipment  # noqa: E402

ADMIN = {"X-Admin-Token": "local-admin"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "evals/runs" / f"w01-smoke-{dt.date.today():%Y%m%d}"))
    ap.add_argument("--tool-retries", type=int, default=0)
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    s = Settings.from_env()
    cases = [json.loads(l) for l in (ROOT / "evals/datasets/w01-smoke.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    budget = Budget(tool_retries=a.tool_retries)
    config = {"model": s.model, "budget": budget.__dict__, "erp": s.erp_base_url,
              "erp_health": httpx.get(f"{s.erp_base_url}/health", timeout=3).json(), "ran_at": dt.datetime.now().astimezone().isoformat(timespec="seconds")}
    (out / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    histories: dict[str, list[dict]] = {}
    results = []
    for c in cases:
        if "seed" in c and "fault" in c["seed"]:
            httpx.post(f"{s.erp_base_url}/_admin/scenario", json={"case_id": c["id"], "base": True, "faults": [c["seed"]["fault"]]},
                       headers=ADMIN, timeout=5).raise_for_status()
        erp = ErpClient(s.erp_base_url, s.erp_api_key)
        model = DashScopeClient(s.dashscope_api_key, s.model, s.model_base_url)
        reg = ToolRegistry([GetProductSpec(erp), GetAvailability(erp), GetShipment(erp)])
        sink = JsonlSink(out / f"{c['id']}.events.jsonl")
        loop = AgentLoop(model, ToolExecutor(reg, sink=sink), reg.specs(), sink=sink, budget=budget)
        history = complete_boundary(histories[c["resume_from"]]).messages if c.get("resume_from") else []
        r = loop.run(c["input"], history=history, run_id=c["id"])
        histories[c["id"]] = [m for m in r.messages if m["role"] != "system"]
        events, _ = read_events(sink.path)
        traj = [{"name": e["name"], "arguments": e["arguments"]} for e in events if e["type"] == "tool.requested"]
        outcomes = [{"name": e["name"], "ok": e.get("ok"), "category": e.get("category")} for e in events if e["type"] in ("tool.executed", "tool.rejected")]
        rec = {"id": c["id"], "kind": c["kind"], "input": c["input"], "resume_from": c.get("resume_from"),
               "status": r.status, "stop_reason": r.stop_reason, "steps": r.steps,
               "usage": r.usage.__dict__, "trajectory": traj, "outcomes": outcomes, "answer": r.answer,
               "expect": c["expect"], "judgement": None}
        results.append(rec)
        print(f"{c['id']} {c['kind']}: {r.status} {r.steps} 步 {[t['name'] for t in traj]} → {(r.answer or '')[:70]}")
        if "seed" in c:
            httpx.post(f"{s.erp_base_url}/_admin/reset", headers=ADMIN, timeout=5)
    (out / "results.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in results), encoding="utf-8")
    print(f"写入 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
