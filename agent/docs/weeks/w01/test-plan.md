# W1 测试计划（1.5 定，1.6–1.9 逐条变绿）

行为覆盖点，不规定测试函数数量；每条能追到周 spec 的 W1-AC。

| ID | 验证行为 | 关键断言 | W1-AC | 节 | 测试位置 |
|---|---|---|---|---|---|
| T01 | 模型最终文本 | 不执行工具，正常结束 | — | 1.7 A | tests/unit/test_loop.py |
| T02 | 一次调用后回答 | 工具恰被执行，结果进入下次模型请求 | 03 | 1.7 B | test_loop.py |
| T03 | 两轮调用 | 后轮保留前轮请求与结果，不丢用户目标 | 03 | 1.7 C | test_loop.py |
| T04 | 一次多调用 | 每个 call_id 都有对应结果，全部处理后再请求模型 | 03 | 1.7 D | test_loop.py |
| T05 | 未知工具 | 不执行任意函数，返回约定错误 | 01 | 1.6 | test_tools.py |
| T06 | 缺字段、空参数、非法 JSON | 在进入业务函数前拦截 | 02 | 1.6 | test_tools.py |
| T07 | 工具无数据 | 与网络失败区分，不把空结果补成事实 | 05 | 1.6 | test_tools.py |
| T08 | 工具超时 | 有 timeout 类别，不伪装成功；有限重试遵守配置 | 05 | 1.6 / 1.8 | test_tools.py |
| T09 | 模型结构异常 | 不把空白响应判为完成；行为明确 | — | 1.7 F | test_loop.py |
| T10 | 持续工具请求 | 达步数上限停止；不会多发一次模型调用 | 04 | 1.7 E | test_loop.py |
| T11 | 预算与重试 | 重试计入次数 / 时间；未知用量保留标记 | 04 | 1.8 | test_budget.py |
| T12 | 请求与事件 | 能找到实际模型请求和调用配对；无鉴权秘密 | — | 1.8 | test_events.py |
| T13 | 回放 | 不调用模型或 ERP，记录缺损可报告 | 07 | 1.8 | test_replay.py |
| T14 | 继续会话 | 新 Run，加载完整历史，未配对历史受控处理 | — | 1.8 | test_resume.py |
| T15 | 新工具扩展 | 注册后可用，Loop 不增加业务特判，旧行为通过 | — | 1.9 | test_shipment.py |

替身：`agent_app.doubles.ScriptedModel`（脚本 + 请求记录）、`agent_app.doubles.FakeERP`（固定数据 + 计数 + 故障注入）。
真实模型冒烟六条在 `evals/datasets/w01-smoke.jsonl`，人工判定量表在 `evals/graders/w01-manual-rubric.md`，不混进单测。
