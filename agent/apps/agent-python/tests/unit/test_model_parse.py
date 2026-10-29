"""w1.6b：先看固定响应 JSON，再看解析后的 Python 对象。样本由 scripts/record_model_samples.py 真实录下。"""
import json

from agent_app.contracts import ResponseKind
from agent_app.llm import parse_chat_completion


def _load(fixtures_dir, name):
    return json.loads((fixtures_dir / "model" / f"{name}.json").read_text(encoding="utf-8"))["response"]


def test_parse_final_text(fixtures_dir):
    r = parse_chat_completion(_load(fixtures_dir, "final_text"))
    assert r.kind == ResponseKind.FINAL and r.text and not r.tool_calls
    assert r.usage and r.usage.total_tokens and not r.usage.unknown


def test_parse_single_tool_call(fixtures_dir):
    r = parse_chat_completion(_load(fixtures_dir, "single_tool_call"))
    assert r.kind == ResponseKind.TOOL_CALLS and [c.name for c in r.tool_calls] == ["get_product_spec"]
    assert json.loads(r.tool_calls[0].arguments) == {"model": "X200"}
    assert r.tool_calls[0].call_id.startswith("call_")


def test_parse_multi_tool_call_keeps_distinct_ids(fixtures_dir):
    r = parse_chat_completion(_load(fixtures_dir, "multi_tool_call"))
    assert [c.name for c in r.tool_calls] == ["get_product_spec", "get_availability"]
    assert len({c.call_id for c in r.tool_calls}) == 2
    msg = r.to_assistant_message()
    assert [tc["id"] for tc in msg["tool_calls"]] == [c.call_id for c in r.tool_calls]


def test_parse_empty_choice_is_malformed_not_final():
    r = parse_chat_completion({"choices": [{"message": {"role": "assistant", "content": None}}]})
    assert r.kind == ResponseKind.MALFORMED
    assert parse_chat_completion({"choices": []}).kind == ResponseKind.MALFORMED
