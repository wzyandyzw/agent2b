# 汇甬数字员工 CLI Demo 系统设计说明

> SDD：Software Design Description。  
> 本文把 PRD 转成可实现的系统设计、接口契约和验收条件；项目同时遵循 Specification-Driven Development。

## 1. 架构

```text
CLI
  ↓
ContextBuilder → AgentLoop → ModelClient
                     ↓
               ToolRegistry / ToolExecutor
                     ↓
   ERP 工具 | 知识检索 | 报告输出
                     ↓
           JSONL 事件、会话历史、回放
```

### 组件职责

| 组件 | 职责 |
|---|---|
| CLI | 接收命令、选择运行模式、展示结果 |
| ContextBuilder | 组装系统指令、历史和当前任务 |
| AgentLoop | 控制模型请求、工具调用、预算和停止条件 |
| ModelClient | 对接真实模型或离线规划器 |
| ToolRegistry | 注册和发现可用工具 |
| ToolExecutor | 校验参数、执行工具、记录结果 |
| ErpClient | 访问模拟 ERP，隔离 HTTP 和错误语义 |
| ConversationStore | 保存历史，支持新 Run 续跑 |
| EventSink | 记录请求、调用和停止原因，支持只读回放 |

## 2. 工具契约

| 工具组 | 工具 | 数据源 |
|---|---|---|
| 产品 | `get_product_spec`、`get_availability`、`search_products` | ERP |
| 订单 | `get_order`、`list_orders` | ERP |
| 客户 | `find_customer`、`get_customer`、`get_receivables` | ERP |
| 物流 | `get_shipment` | ERP |
| 报价 | `price_quote` | ERP 报价规则 |
| 知识 | `search_knowledge` | `agent/knowledge` |
| 产出 | `save_report` | `agent/artifacts` |

## 3. 核心约束

- **事实边界**：业务事实只能来自工具结果或知识库。
- **价格边界**：模型不能传入或修改价格，只能调用 `price_quote`。
- **失败语义**：404 表示无数据；超时、上游错误和坏响应不能被解释为业务事实。
- **写入边界**：第一阶段不写真实业务系统，报价只计算不落账。
- **安全边界**：密钥只来自环境变量；报告文件名和保存路径受校验。
- **可追溯性**：模型请求、工具调用、结果和最终状态必须写入事件日志。
- **预算边界**：每次 Run 限制模型步数、工具次数、超时和总时长。

## 4. 运行模式

| 模式 | 模型 | ERP | 用途 |
|---|---|---|---|
| 真实模型 | 百炼 OpenAI 兼容接口 | 模拟 ERP | 自由自然语言任务 |
| 离线 Demo | 确定性规划器 | 模拟 ERP | 无密钥验收和故障测试 |
| Scripted | 固定脚本 | Fixture | 原有 W1 回归 |

## 5. 验收契约

| 编号 | 验收条件 | 设计位置 |
|---|---|---|
| AC-01 | 一个任务可以调用多个工具并得到最终答复 | AgentLoop、ToolExecutor |
| AC-02 | 客户、订单、应收、物流可组合查询 | ERP tools |
| AC-03 | 产品选型和报价遵循工况与报价规则 | `search_products`、`price_quote` |
| AC-04 | 知识答案带来源 | `search_knowledge` |
| AC-05 | 工具失败不被包装成业务事实 | ErpClient、DemoModel |
| AC-06 | 每次调用可审计、可回放 | EventSink、Replay |
| AC-07 | 会话可继续，不丢完整消息边界 | ConversationStore |
| AC-08 | 无模型密钥可完成核心 Demo | OfflineDemoModel |
| AC-09 | 报告只能写入指定目录 | SaveReport |

## 6. 已知限制

- 当前仅支持单 Agent 和串行工具执行。
- 没有生产级审批、多租户和真实系统写操作。
- 本地知识检索是轻量关键词匹配，不是最终 RAG 方案。
- 模型响应质量和成本需要真实模型评测，离线规划器不能代表模型能力。
