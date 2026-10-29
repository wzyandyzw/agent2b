# W1 红绿证据（增量 A–F 与工具边界）

所有红都是"预期行为缺失"引起的，不是导入错误或环境问题；绿是最小实现；每对红绿一个提交。提交序列（week/01）：

```
4c9da80 w1.5 契约类型与 Protocol、ScriptedModel、FakeERP、测试计划 T01–T15
e96a690 w1.6a fixture 录制脚本与 12 份 ERP 快照；FakeERP.from_fixtures
368548c w1.6b ERP 客户端、两个只读工具、注册表与执行器、百炼 ModelClient；三份真实模型响应样本与解析测试
18b2065 w1.6 红：T05–T08 工具边界测试（9 红 3 绿：T05/T07/无重试已覆盖，校验与超时分类缺失）
4c75ceb w1.6 绿：guardrails 参数校验进执行器；ERP 客户端区分 timeout / 504 / 非 JSON；契约测试
1d819e8 w1.7a Loop 增量 A：最终文本分支（T01 绿）；ContextBuilder
55e3048 w1.7 红：增量 B/C/D 测试（工具分支未实现，NotImplementedError）
5a7e766 w1.7 绿：工具分支——串行执行、逐个配对、全部回注再请求（T02–T04）
27025c0 w1.7 红：增量 E/F 测试（无步数预算：脚本被打穿；畸形响应：分支未实现）
6bd0d0a w1.7 绿：步数预算与协议失败出口（T09、T10）
a6cb0de w1.7 CLI chat：接真实模型与 ERP，--scripted 离线；主案例真实跑通
05d2027 w1.8a 事件（JSONL 快照、无密钥）、只读回放、会话持久与完整边界裁剪（T12–T14 绿）
ebd2fa9 w1.8 红：T11 预算与重试（执行器不认 tool_retries；Loop 没有墙钟与时钟注入）
2ecd1a1 w1.8 绿：只读工具 timeout 有界重试（每次尝试记事件）、墙钟、可注入时钟（T11）
edd7c2d w1.8 CLI：会话持久、--resume 新 Run 装历史、--show-request、replay 子命令；真实会话继续与回放跑通
b722077 w1.9 红：T15 查物流工具（模块不存在）
043a1b2 w1.9 绿：get_shipment 工具 + 注册；Loop 未改一行
```

## 1.6 工具边界 T05–T08（红 9 / 绿 3，绿的三条说明现有实现已覆盖）

红（提交 `w1.6 红`）：
```
/opt/homebrew/Caskroom/miniforge/base/lib/python3.12/json/decoder.py:356: JSONDecodeError
=========================== short test summary info ============================
FAILED tests/unit/test_tools.py::test_t06_bad_arguments_never_reach_erp[args0-missing_field]
FAILED tests/unit/test_tools.py::test_t06_bad_arguments_never_reach_erp[args1-empty_field]
FAILED tests/unit/test_tools.py::test_t06_bad_arguments_never_reach_erp[args2-empty_field]
FAILED tests/unit/test_tools.py::test_t06_bad_arguments_never_reach_erp[args3-wrong_type]
FAILED tests/unit/test_tools.py::test_t06_bad_arguments_never_reach_erp[args4-unknown_field]
FAILED tests/unit/test_tools.py::test_t06_bad_arguments_never_reach_erp[{"model": -invalid_json]
FAILED tests/unit/test_tools.py::test_t08_read_timeout_maps_to_timeout_category
FAILED tests/unit/test_tools.py::test_t08_gateway_timeout_504_maps_to_timeout_category
FAILED tests/unit/test_tools.py::test_t08_malformed_body_is_not_a_result - js...
9 failed, 3 passed in 0.10s
```
失败原因归类：T06 六条全部是"参数没校验就进了 FakeERP"（计数 1 ≠ 0 或 JSONDecodeError 直接炸出来）；T08 三条是"httpx 超时 / 504 / 非 JSON 都被归成 upstream_error 或抛 JSONDecodeError"。T05（未知工具）、T07（404 → not_found）、无重试计 1 次：一开始就绿，核实了断言不是空断言。

绿（提交 `w1.6 绿`）改动范围：
```
.../src/agent_app/guardrails/__init__.py           |  3 ++
 apps/agent-python/src/agent_app/guardrails/args.py | 36 ++++++++++++++++++++++
 .../agent-python/src/agent_app/tools/erp_client.py | 13 +++++---
 apps/agent-python/src/agent_app/tools/registry.py  | 11 ++++---
 .../tests/integration/test_erp_contract.py         | 28 +++++++++++++++++
 5 files changed, 83 insertions(+), 8 deletions(-)
```

## 1.7 增量 A：最终文本（T01 一开始就绿——Loop 骨架只实现了这一个分支）

## 1.7 增量 B / C / D：工具分支

红：
```
=========================== short test summary info ============================
FAILED tests/unit/test_loop.py::test_t02_single_tool_call_result_enters_next_request
FAILED tests/unit/test_loop.py::test_t03_two_rounds_keep_full_history - NotIm...
FAILED tests/unit/test_loop.py::test_t04_multi_call_pairs_every_id_before_next_request
FAILED tests/unit/test_loop.py::test_tool_failure_is_paired_back_as_error_not_fact
4 failed, 1 passed in 0.05s
```
四条都停在 `NotImplementedError: 响应形态 tool_calls 的分支还没有实现`。

绿改动（只动 loop.py 的工具分支，6 行）：
```
apps/agent-python/src/agent_app/agent/loop.py | 8 +++++++-
 1 file changed, 7 insertions(+), 1 deletion(-)
```

## 1.7 增量 E / F：步数预算与协议失败

红：
```
src/agent_app/agent/loop.py:39: NotImplementedError
=========================== short test summary info ============================
FAILED tests/unit/test_loop.py::test_t10_max_steps_stops_without_extra_model_call
FAILED tests/unit/test_loop.py::test_t09_malformed_response_is_protocol_failure_not_completion
2 failed, 5 passed in 0.04s
```
E 的红是"脚本被打穿"：没有预算的 Loop 把 5 条脚本全部请求完，第 6 次请求超出；F 的红是畸形响应没有分支。

绿改动：
```
apps/agent-python/src/agent_app/agent/loop.py | 18 +++++++++++++++---
 1 file changed, 15 insertions(+), 3 deletions(-)
```

## 1.8 T11 预算与重试

红：
```
=========================== short test summary info ============================
FAILED tests/unit/test_budget.py::test_t11_bounded_retry_on_timeout_counts_every_attempt
FAILED tests/unit/test_budget.py::test_t11_retry_limit_is_respected_then_error_is_reported
FAILED tests/unit/test_budget.py::test_t11_wall_clock_stops_before_next_model_call
3 failed, 2 passed in 0.05s
```
`assert 1 == 2`：执行器不认 tool_retries，超时一次就放弃；`clock` 参数不存在：墙钟没法测。

绿改动：
```
apps/agent-python/src/agent_app/agent/loop.py     | 10 ++++++--
 apps/agent-python/src/agent_app/tools/registry.py | 31 +++++++++++++++--------
 2 files changed, 28 insertions(+), 13 deletions(-)
```

## 1.9 T15 新工具

红：模块 `agent_app.tools.shipment` 不存在（这一条允许是导入错误：工具本来就还没写）。

绿改动——Loop 一行未改：
```
apps/agent-python/src/agent_app/cli.py            |  3 ++-
 apps/agent-python/src/agent_app/tools/shipment.py | 30 +++++++++++++++++++++++
 2 files changed, 32 insertions(+), 1 deletion(-)
```
