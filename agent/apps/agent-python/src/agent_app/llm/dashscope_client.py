"""百炼 OpenAI 兼容接口的 ModelClient。只做两件事：把 messages + tools 发出去；把原始 JSON 归一化成 ModelResponse。
不决定业务动作是否获准；不执行任何函数。"""
from __future__ import annotations

import httpx

from agent_app.contracts import ModelResponse, ResponseKind, ToolCall, ToolSpec, Usage


class ModelError(Exception):
    def __init__(self, category: str, message: str, status: int | None = None, body: str | None = None) -> None:
        super().__init__(message)
        self.category, self.status, self.body = category, status, body


def parse_chat_completion(raw: dict) -> ModelResponse:
    """原始 chat.completion JSON → ModelResponse。无文本且无工具请求 = MALFORMED，不是完成。"""
    choices = raw.get("choices") or []
    if not choices:
        return ModelResponse(kind=ResponseKind.MALFORMED, raw=raw)
    choice = choices[0]
    msg = choice.get("message") or {}
    text = msg.get("content")
    calls = []
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        calls.append(ToolCall(call_id=tc.get("id", ""), name=fn.get("name", ""), arguments=fn.get("arguments") or ""))
    u = raw.get("usage") or {}
    usage = Usage(u.get("prompt_tokens"), u.get("completion_tokens"), u.get("total_tokens"))
    finish = choice.get("finish_reason")
    if calls:
        return ModelResponse(ResponseKind.TOOL_CALLS, text=text or None, tool_calls=calls, usage=usage,
                             finish_reason=finish, raw=raw)
    if text and text.strip():
        return ModelResponse(ResponseKind.FINAL, text=text, usage=usage, finish_reason=finish, raw=raw)
    return ModelResponse(ResponseKind.MALFORMED, usage=usage, finish_reason=finish, raw=raw)


class DashScopeClient:
    def __init__(self, api_key: str, model: str, base_url: str, *, temperature: float = 0.2,
                 max_tokens: int = 1024, transport: httpx.BaseTransport | None = None) -> None:
        if not api_key:
            raise ModelError("config", "缺少 DASHSCOPE_API_KEY（放在 .env）")
        self.model, self.temperature, self.max_tokens = model, temperature, max_tokens
        self._client = httpx.Client(base_url=base_url, headers={"Authorization": f"Bearer {api_key}"},
                                    transport=transport)

    def describe(self) -> dict:
        """进事件快照的模型标识与生成参数。没有密钥。"""
        return {"model": self.model, "temperature": self.temperature, "max_tokens": self.max_tokens,
                "base_url": str(self._client.base_url)}

    def request_body(self, messages: list[dict], tools: list[ToolSpec]) -> dict:
        """真正发出去的请求体。事件快照记的就是它——里面没有密钥。"""
        body = {"model": self.model, "messages": messages, "temperature": self.temperature,
                "max_tokens": self.max_tokens}
        if tools:
            body["tools"] = [t.to_openai() for t in tools]
            body["tool_choice"] = "auto"
            body["parallel_tool_calls"] = True
        return body

    def generate(self, messages: list[dict], tools: list[ToolSpec], *, timeout_s: float) -> ModelResponse:
        body = self.request_body(messages, tools)
        try:
            r = self._client.post("/chat/completions", json=body, timeout=timeout_s)
        except httpx.TimeoutException as e:
            raise ModelError("timeout", f"模型请求超时（{timeout_s}s）") from e
        except httpx.HTTPError as e:
            raise ModelError("network", f"模型请求失败：{type(e).__name__}") from e
        if r.status_code >= 400:
            raise ModelError("http", f"模型接口返回 {r.status_code}", status=r.status_code, body=r.text[:2000])
        try:
            raw = r.json()
        except ValueError as e:
            raise ModelError("malformed", "模型接口返回的不是 JSON", status=r.status_code, body=r.text[:500]) from e
        return parse_chat_completion(raw)
