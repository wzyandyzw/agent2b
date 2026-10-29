# 汇甬全公司数字员工 CLI Demo

第一阶段交付单 Agent CLI：用自然语言调用 ERP、客户、订单、应收、产品、物流和知识库工具，完成跨部门任务。

## 一键运行

需要安装 `uv`。脚本会自动启动模拟 ERP，并在 Demo 结束后关闭它。

```powershell
.\demo.ps1 -Scenario customer
```

可选场景：

```powershell
.\demo.ps1 -Scenario delivery
.\demo.ps1 -Scenario finance
.\demo.ps1 -Scenario quote
.\demo.ps1 -Scenario management
.\demo.ps1 -Scenario knowledge
.\demo.ps1 -Scenario product
.\demo.ps1 -Scenario all
```

也可以传入自己的演示任务：

```powershell
.\demo.ps1 -Prompt "汇总客户 C-E001 的订单、物流和回款风险"
```

## 真实模型模式

复制 `agent/.env.example` 为 `agent/.env`，填写 `DASHSCOPE_API_KEY`，然后启动模拟 ERP：

```powershell
uv run --project environment/shenwei-erp python -m shenwei_erp
```

另开终端：

```powershell
uv run --project agent/apps/agent-python agent-cli chat "帮我检查本周有哪些订单可能延误"
```

## 已交付能力

- CLI 单轮对话与多轮工具调用。
- ERP 产品、库存、订单、物流、客户、应收和报价工具。
- 公司资料、产品说明和规则的知识检索。
- 本地 Markdown 报告生成。
- 会话续跑、JSONL 事件记录和只读回放。
- 超时、错误、预算和参数校验。
- 无模型密钥的离线 Demo。

详细交付结果见 [DELIVERY.md](./DELIVERY.md)。

## 目录

- `agent/`：Agent 代码、测试、知识库和原课程文档。
- `environment/`：完整模拟 ERP 环境、接口规范和故障注入。
- `product/`：汇甬业务调研和产品方案。
- `s6-env-w1.zip`、`shenwei-agent-product-W1-all-tags.zip`：原始交付包，保持不变。

## 验证

```powershell
uv run --project agent/apps/agent-python pytest agent/apps/agent-python/tests/unit -q
uv run --project environment/shenwei-erp pytest environment/shenwei-erp/tests -q
```

