"""参数校验：模型按描述生成参数，不意味着参数可信。调用业务函数前在这里拦。
W1 只有校验；W2 在这一层加授权与确认。"""
from __future__ import annotations

import json

from agent_app.contracts import ToolFailure, ToolSpec

_TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "object": dict, "array": list}


def validate_args(spec: ToolSpec, raw_arguments: str) -> dict:
    try:
        args = json.loads(raw_arguments) if raw_arguments.strip() else {}
    except json.JSONDecodeError as e:
        raise ToolFailure("input_error", "invalid_json", f"参数不是有效 JSON：{e.msg}") from e
    if not isinstance(args, dict):
        raise ToolFailure("input_error", "wrong_type", "参数必须是对象")
    props: dict = spec.parameters.get("properties", {})
    for name in spec.parameters.get("required", []):
        if name not in args:
            raise ToolFailure("input_error", "missing_field", f"缺少必填参数 {name}")
    if spec.parameters.get("additionalProperties") is False:
        for name in args:
            if name not in props:
                raise ToolFailure("input_error", "unknown_field", f"未定义的参数 {name}")
    for name, value in args.items():
        expected = _TYPES.get(props.get(name, {}).get("type"))
        if expected and (not isinstance(value, expected) or (expected is int and isinstance(value, bool))):
            raise ToolFailure("input_error", "wrong_type", f"参数 {name} 类型应为 {props[name]['type']}")
        if isinstance(value, str) and not value.strip():
            raise ToolFailure("input_error", "empty_field", f"参数 {name} 不能为空")
        minimum = props.get(name, {}).get("minimum")
        if minimum is not None and isinstance(value, (int, float)) and value < minimum:
            raise ToolFailure("input_error", "out_of_range", f"参数 {name} 不能小于 {minimum}")
    return {k: (v.strip() if isinstance(v, str) else v) for k, v in args.items()}
