# shenwei-agent-product

深维工作台（你的跨境数字员工）的课程参考实现。S6 十二周按周推进，一周一个大 tag `wN`，有代码增量的节一个小 tag `wN.k`。

本周（W1）：一条业务话推到一个运行时。CLI → AgentLoop → 模型 / 工具 / 上下文 → 两个 ERP 只读工具 → 事件日志。

## 起步

```bash
cp .env.example .env            # 填 DASHSCOPE_API_KEY；离线用法不需要
cd apps/agent-python
uv sync                         # Python 3.12
uv run pytest tests/unit -q     # 离线：ScriptedModel + FakeERP
uv run agent-cli chat "查一下 X200 的规格和当前库存交期"
uv run agent-cli chat --scripted "查一下 X200 的规格和当前库存交期"   # 没有模型额度也能跑
uv run agent-cli replay <conversation_id>
```

完整命令、配置与已知限制见 `docs/releases/w1.md`；证据在 `docs/weeks/w01/`。

模拟 ERP 在 `S6/环境/shenwei-erp`（端口 9100），`uv run python -m shenwei_erp` 起。

## 结构

见 `docs/architecture.md`。规格在 `docs/specs/`：`product.md` 是总 spec（PRD 的工程版），`w01-*.md` 是周 spec。AI coding 规则在 `AGENTS.md`。

## 本周 tag

| tag | 内容 |
|---|---|
| w1.4 | 仓库骨架、总 spec + 周 spec、ADR-001、AGENTS.md、CI 最小 |
| w1.5 | 契约类型、ScriptedModel、FakeERP、测试计划 |
| w1.6 | ModelClient、get_product_spec、get_availability、fixture 录制 |
| w1.7 | AgentLoop 增量 A–F |
| w1.8 | 预算、事件、回放、继续会话 |
| w1.9 | get_shipment、Release |
| w1 | 本周合并点 |
