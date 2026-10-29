# apps/agent-python

子目录规则，覆盖根 AGENTS.md 中同名条款。

- 包名 `agent_app`，目录：`contracts/`（共享类型与 Protocol）、`agent/`（Loop、预算、上下文、Run）、`llm/`（模型适配）、`tools/`（每个工具一文件，带 schema）、`guardrails/`（参数校验）、`observability/`（事件）、`doubles/`（ScriptedModel、FakeERP，测试与离线演示共用）。
- 新增工具：只改 `tools/<name>.py`、注册、schema、测试、文档；不得在 `agent/loop.py` 加按工具名的分支。
- 单测不联网：模型用 `doubles.ScriptedModel`，ERP 用 `doubles.FakeERP` 读 `tests/fixtures/erp/*.json`。
- fixture 不手写：`uv run python ../../scripts/record_fixtures.py` 从 ERP 9100 录。
