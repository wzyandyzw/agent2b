"""发三次真实请求，把原始 chat.completion JSON 存成 tests/fixtures/model/*.json（离线解析课与解析测试用）。
用法：uv run --project apps/agent-python python scripts/record_model_samples.py"""
import datetime as dt
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "apps/agent-python/src"))
from agent_app.config import Settings  # noqa: E402
from agent_app.llm import DashScopeClient  # noqa: E402
from agent_app.tools.availability import SPEC as AVAIL  # noqa: E402
from agent_app.tools.product import SPEC as PRODUCT  # noqa: E402

SYSTEM = "你是深维工作台的数字员工，帮跨境设备业务员查事实。能用工具就用工具，不要编造规格或库存。"
CASES = [
    ("final_text", "你好，你能帮我做什么？"),
    ("single_tool_call", "查一下 X200 的规格"),
    ("multi_tool_call", "查一下 X200 的规格和当前库存交期"),
]


def main() -> int:
    s = Settings.from_env()
    client = DashScopeClient(s.dashscope_api_key, s.model, s.model_base_url)
    out = pathlib.Path(__file__).resolve().parents[1] / "apps/agent-python/tests/fixtures/model"
    out.mkdir(parents=True, exist_ok=True)
    for name, user in CASES:
        msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
        resp = client.generate(msgs, [PRODUCT, AVAIL], timeout_s=60)
        rec = {"recorded_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
               "request": client.request_body(msgs, [PRODUCT, AVAIL]), "response": resp.raw,
               "parsed": {"kind": resp.kind, "text": resp.text,
                          "tool_calls": [c.__dict__ for c in resp.tool_calls], "finish_reason": resp.finish_reason}}
        (out / f"{name}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(name, "→", resp.kind, [c.name for c in resp.tool_calls], (resp.text or "")[:60])
    return 0


if __name__ == "__main__":
    sys.exit(main())
