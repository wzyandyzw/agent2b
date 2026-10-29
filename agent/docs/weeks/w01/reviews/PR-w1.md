# PR · week/01 → main（本地审查记录）

解决的问题与规格链接：W1 从需求到 Agent Loop；`docs/specs/w01-agent-loop.md`（W1-AC-01–07）、`w01-shipment.md`。

关键修改及为什么：
- contracts：四个 Protocol 与最小类型——换模型 / 换 ERP / 换入口 / 离线测各只动一个边界。
- tools + guardrails：参数在进业务函数前校验（W1-AC-02）；ERP 错误分层 not_found / timeout / upstream_error / malformed（W1-AC-05）。
- agent/loop：增量 A–F，串行执行逐个配对（W1-AC-03）、步数与墙钟预算（W1-AC-04）、协议失败出口。
- observability + replay + conversation：请求快照无密钥（I1）、先记后执行（I2）、只读回放（W1-AC-07）、继续会话裁到完整边界（AC-01）。
- tools/shipment：第三个工具，Loop 零改动（T15）。

验证命令、结果与证据位置：`uv run pytest tests -q` → 44 passed（含契约测试）；冒烟 `docs/weeks/w01/smoke-20261024.md` 六条过；红绿 `increments.md`；故障卡 `faults.md`。

已知限制或未覆盖情况：没有流式；工具串行；W1-AC-06 只有人工判定；墙钟只在下一次调用前检查；qwen-plus 对 id 错配不报错（faults.md 第 3 张）。

自审结论：合并。
