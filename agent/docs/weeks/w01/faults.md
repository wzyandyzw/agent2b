# 六张故障卡（1.8 / 直播 65–80 分）

讲法固定：先预测 → 看现象 → 收证据 → 定位层 → 修复 / 控制 → 回归。每张卡的证据都是真实跑出来的。

## 1 库存接口超时

- 现象：规格有结果，交期"无法确认"。
- 证据：冒烟 S05（ERP 场景注入 `GET /v1/inventory/*` timeout 一次）：`tool.executed get_availability ok=false category=timeout`；答复"当前库存与交期：无法确认，上游系统超时"。
- 定位层：ERP adapter 的错误分类（T08）。
- 揭示：网络失败不等于库存为零。修复 / 控制：ADR-002 有界重试，`--tool-retries 1`。
- 回归：T08 三条 + T11 三条。

## 2 工具参数为空

- 现象：看似发出调用却无业务结果。
- 证据（脚本模型发 `{"model": ""}`）：
```
4 tool.requested {'name': 'get_availability', 'arguments': '{"model": ""}'}
5 tool.rejected {'name': 'get_availability', 'category': 'input_error', 'code': 'empty_field'}
ERP 调用计数： {}
回注给模型的内容： {"ok": false, "error": {"category": "input_error", "code": "empty_field", "message": "参数 model 不能为空"}}
结果： completed （模型据此说）请提供型号。
```
- 定位层：guardrails（T06）。揭示：描述里写了"必填"不代替执行校验。

## 3 tool_call_id 配错

- 现象：预期是下一轮协议报错；实测百炼 qwen-plus **不报错**，而是静默错配——模型声称"已查到"，内容全是"未提供"。
- 证据（直接调接口，把结果配到不存在的 id；以及少发一条 tool 消息）：
```
HTTP 200（百炼 qwen-plus 没有报协议错误）
{"choices":[{"message":{"content":"已查到 X200 的规格信息。需要我为您详细说明哪些方面？…"}}]}
---- 缺一条 tool 消息（assistant 请求了工具但没有结果就发下一轮）
HTTP 200
{"choices":[{"message":{"content":"已查到 X200 的规格信息如下：\n- 名称：X200\n- 类别：未知（未提供具体类别）\n- 结构化参数：未提供详细参数 …"}}]}
```
- 定位层：Loop 的配对（T04）与继续会话的完整边界（T14）。揭示：多调用配对是协议责任，而且上游不一定替你把关——错配可能不报错，只是答复变成空话。

## 4 重复调用

- 现象：程序一直输出查询动作。
- 证据：T10（脚本永远请求 get_availability，max_steps=3）：模型调用 3 次、ERP 3 次、`stopped / max_steps`，消息停在完整边界。
- 定位层：Loop 预算。揭示：相同调用不一律非法（只读、在预算内），但必须有停止边界。

## 5 异常被吞掉

- 现象：用户收到"查询成功"，实际是超时。
- 证据：打上 `faults/swallow.patch`（adapter 把超时吞成 `{"available": 0, "note": "查询成功"}`）后跑 T08：
```
E       AssertionError: assert (True is False)
E        +  where True = ToolResult(call_id='call_1', name='get_availability', ok=True, data={'model': 'X200', 'warehouse': None, 'requested_qt...None, 'basis_code': None, 'basis_text': None, 'schedule_lines': [], 'incoterm': None, 'observed_at': None}, error=None).ok
1 failed, 11 deselected in 0.09s
```
- 定位层：catch 分支与结果包装。揭示：错误语义不能被展示层覆盖；撤掉补丁回归全绿。

## 6 模型结构异常

- 现象：空回复或解析失败。
- 证据：`parse_chat_completion` 对 `content: null` 且无 tool_calls 的响应返回 MALFORMED（test_model_parse 第 4 条）；Loop 对 MALFORMED 返回 `failed / protocol_error`，不执行工具（T09）。
- 定位层：原始响应与适配层。揭示：协议失败与业务无数据不同。
