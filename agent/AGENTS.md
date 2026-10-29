# AGENTS.md · shenwei-agent-product

给 AI coding 工具读的团队规则。每条规则后面的括号是它的来源：没有来源的行不该出现在这里。
这个文件不是权限设施：AI 可能不读，读了也可能不照做；真正拦住的是保护分支、CI、审查人与凭据权限。
它也不是 README：README 给人读、讲怎么跑；这里给工具读、讲怎么改。两份不互相复制。

## 环境（来源：版本冻结 spike-a-pass、fixture 规则）

- Python 3.12 + uv，不用 pip；依赖改动只经 `apps/agent-python/pyproject.toml` 与 `uv.lock`。
- 单元测试：`cd apps/agent-python && uv run pytest tests/unit -q`。离线，用 FakeERP + `tests/fixtures/`。
- 集成测试：`uv run pytest tests/integration -q`，需要模拟 ERP `http://localhost:9100`，不可达时自动跳过。
- CLI：`uv run agent-cli --help`。真实模型需要 `.env` 里的 `DASHSCOPE_API_KEY`。

## 开发流程（来源：1.2 两层 spec、1.7 TDD）

- 从目标 Issue 与 `docs/specs/` 的周 spec 开始；实现以规格为准，与测试冲突时解释并建议，不自改规格。
- 总 spec `docs/specs/product.md` 不在任务里改；要改先写 ADR。
- 确定性行为先补能复现问题的测试再改实现；概率能力（模型选不选对工具）走 `evals/`，不写成断言。
- 未决业务语义先澄清，不猜。

## 任务边界（来源：六字段指令的"现场保护"）

- 只修改任务允许的目录；跨模块变更先报告影响。
- `apps/agent-python/src/agent_app/contracts/` 与共享类型的变更，要列出生产者、消费者及兼容策略。
- 不删除测试、不弱化断言、不关 CI 来掩盖问题。
- 不引入未说明的新依赖，不做全仓格式化。

## Git 操作（来源：1.4 段二、tag 规则）

- 一任务一分支，分支名 `week/NN` 或 `task/<短名>`；不在 main 上直接开发。
- 精确暂存并复核 staged diff；一次提交解决一件可解释的事。
- 不 push、不打 tag、不 merge，除非任务指令明确授权。
- 不丢弃未提交修改、不改写共享历史、不强推、不移动已发布 tag。
- 冲突按双方意图解决，不统一选一侧。

## 禁止（来源：1.2 非功能、密钥规则）

- 密钥、`.env`、运行日志（`runs/`）、事件文件不进提交；发现已提交的 Key 先报告，不自行 revert 了事。
- 不把 API Key、鉴权头写进事件、日志、测试输出。

## 交付（来源：协作交接记录）

- 报告真实执行的测试及结果；未运行的检查明确标注。
- PR 四行：解决的问题与规格链接 / 关键修改及为什么 / 验证命令、结果与证据位置 / 已知限制。
- 交接包含基线 SHA、结果 SHA、变更文件、接口假设、阻塞和后续步骤。
