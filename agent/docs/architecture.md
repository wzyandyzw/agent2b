# 架构

最终（W12）的一张图在课件 `S6/课件/W01-从需求到AgentLoop/arch.html`。W1 只做高亮部分：

```
CLI ──▶ AgentLoop ──▶ ModelClient（百炼 OpenAI 兼容）
            │  ├──▶ ContextBuilder（指令 + 历史 + 工具结果）
            │  ├──▶ ToolRegistry / Executor ──▶ guardrails（参数校验）──▶ tools/*（ERP 只读）──▶ ERP 9100
            │  └──▶ EventSink（JSONL 事件：请求快照、工具请求/结果、停止原因）
            └──▶ RunResult（状态、停止原因、答复）
```

| 组件 | 负责 | 不负责 |
|---|---|---|
| ModelClient | 请求与响应适配、协议错误 | 决定业务动作是否获准 |
| ToolRegistry / Executor | 查工具、验证参数、执行、返回带 call_id 的结果 | 生成最终答复 |
| AgentLoop | 推进一次执行、配对结果、判断继续 / 停止 | 知道某型号的价格与规格 |
| ContextBuilder | 指令、历史和工具结果的组装 | 保存权威库存 |
| EventSink | 记录执行事实与请求快照 | 生成模型内部推理 |
| CLI | 输入、输出、调用应用入口 | 实现另一份 Loop |

对象语义（W1 最小）：Conversation 一段对话历史，可含多个 Run；Run 对一次新输入的执行（running / completed / failed / stopped）；Step 一次模型请求及其响应；Event 追加的执行记录。
