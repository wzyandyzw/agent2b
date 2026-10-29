# TDD、测试与验收

## 1. 开发方式

本项目采用测试驱动开发：

```text
补充失败测试 → 最小实现 → 测试转绿 → 重构 → 全量回归
```

确定性行为必须先用程序测试约束；模型判断质量进入评测集，不能只靠单测断言。

## 2. 测试分层

| 层级 | 目标 | 位置 |
|---|---|---|
| 单元测试 | Agent Loop、工具、错误分类、知识检索、报告路径、会话续跑 | `agent/apps/agent-python/tests/unit` |
| 集成测试 | 模拟 ERP 与 Agent 的字段契约 | `agent/apps/agent-python/tests/integration` |
| 环境测试 | ERP 幂等、分页、事件、账本和故障注入 | `environment/shenwei-erp/tests` |
| 端到端 Demo | 7 个跨部门 CLI 场景 | `demo.ps1 -Scenario all` |

## 3. 追踪关系

| 验收条件 | 主要测试或证据 |
|---|---|
| AC-01 多工具执行 | `test_loop.py` |
| AC-02 客户/订单/应收/物流 | `test_enterprise_tools.py`、端到端 Demo |
| AC-03 选型与报价 | `test_enterprise_tools.py`、`demo.ps1 -Scenario quote` |
| AC-04 知识来源 | `test_enterprise_tools.py` |
| AC-05 错误不伪装 | `test_tools.py`、`test_demo_model.py` |
| AC-06 审计与回放 | `test_events.py`、`test_replay.py` |
| AC-07 会话续跑 | `test_resume.py` |
| AC-08 离线 Demo | `test_demo_model.py`、`demo.ps1` |
| AC-09 报告路径安全 | `test_enterprise_tools.py` |

## 4. 发布门禁

以下条件全部满足后才能打版本 tag：

```powershell
uv run --project agent/apps/agent-python pytest agent/apps/agent-python/tests/unit -q
uv run --project environment/shenwei-erp pytest environment/shenwei-erp/tests -q
.\demo.ps1 -Scenario all
```

补充要求：

- Agent 对运行中的模拟 ERP 契约测试通过。
- 无真实密钥、虚拟环境、运行日志和数据库进入 Git。
- Release 文档记录交付范围、验证结果和已知限制。
- 工作区干净后提交，再给提交打 annotated tag。

## 5. 本次验证

- Agent 单元测试：47 条通过。
- 模拟 ERP 测试：16 条通过。
- ERP 契约测试：4 条通过。
- 7 个端到端 Demo 全部完成。
- 回放和后台服务清理验证通过。
