# 汇甬企业数字员工 CLI

本项目以 `shenwei-agent-product-w1-fix1` 为基线，在保留原有 Agent Loop、测试、事件和课程文档的基础上，扩展为可跨部门演示的企业数字员工。

## 启动

项目根目录提供一键脚本：

```powershell
.\demo.ps1 -Scenario all
```

也可以手动启动模拟 ERP：

```powershell
uv run --project environment/shenwei-erp python -m shenwei_erp
```

然后运行：

```powershell
uv run --project agent/apps/agent-python agent-cli chat --offline-demo "查看客户 C-E003 的应收和逾期风险"
```

真实模型模式需要将 `.env.example` 复制为 `.env` 并设置 `DASHSCOPE_API_KEY`：

```powershell
uv run --project agent/apps/agent-python agent-cli chat "帮我检查订单 ORD-10086 是否可能延误"
```

## CLI

```text
agent-cli chat       单 Agent 对话
agent-cli replay     只读回放会话事件
agent-cli tools      列出当前注册工具
```

`chat` 支持：

- 真实模型模式：默认。
- `--offline-demo`：规则规划器 + 模拟 ERP，无需模型密钥。
- `--scripted`：保留的原 W1 固定回归。
- `--resume <id>`：继续会话。
- `--show-request`：显示实际发给模型的消息。

## 已接入工具

- 产品规格、库存交期、产品工况筛选。
- 客户查询、客户资料、应收账龄。
- 订单详情、订单列表、物流。
- 报价规则计算。
- 企业知识检索。
- Markdown 报告保存。

## 测试

```powershell
uv run --project agent/apps/agent-python pytest agent/apps/agent-python/tests/unit -q
uv run --project environment/shenwei-erp pytest environment/shenwei-erp/tests -q
```

原有规格和版本证据保留在 `docs/`；当前交付针对第一阶段 CLI Demo 做了增量扩展。

