# 深维工作台 W1 流程复现

本仓库按 `shenwei-agent-product-W1-all-tags.zip` 的十个阶段快照重建
`w1.0 → w1.2 → w1.4 → w1.5 → w1.6 → w1.7 → w1.8 → w1.9 → w1 → w1-fix1`
的研发过程，并配合 `s6-env-w1.zip` 提供可运行的模拟 ERP。

## 目录

- `agent/`：Agent Loop、CLI、规格、测试、评测与 Release 证据。
- `environment/`：模拟 ERP、mockkit、接口说明和 OpenAPI。

## 启动模拟 ERP

```powershell
uv run --project environment/shenwei-erp --python 3.12 python -m shenwei_erp
```

服务启动后访问 `http://localhost:9100/docs`。

## 运行 Agent

另开一个终端：

```powershell
cd agent
Copy-Item .env.example .env
uv run --project apps/agent-python --python 3.12 `
  agent-cli chat --scripted "查一下 X200 的规格和当前库存交期"
```

真实模型模式需要在 `agent/.env` 中填写 `DASHSCOPE_API_KEY`，然后去掉
`--scripted`。

## 验证

```powershell
uv run --project agent/apps/agent-python --python 3.12 `
  pytest agent/apps/agent-python/tests/unit -q

uv run --project environment/shenwei-erp --python 3.12 `
  pytest environment/shenwei-erp/tests -q
```

本机若使用系统 HTTP 代理，需让回环地址绕过代理，否则本地 ERP/webhook
请求可能被代理返回 502：

```powershell
$env:NO_PROXY = "127.0.0.1,localhost"
$env:no_proxy = "127.0.0.1,localhost"
```

W1 的规格、验收条件、测试计划和 Release 说明位于 `agent/docs/`。

## 本次复现结果

- Agent 单元测试：40/40 通过。
- 模拟 ERP 测试：16/16 通过。
- Agent 对运行中 ERP 的契约测试：4/4 通过。
- 离线 Agent CLI 主案例：通过，调用 `get_product_spec` 和 `get_availability`。
- 固定流程对照：通过。
- 发布检查：通过，十个 W1 tag 齐全。

真实模型的六条冒烟未重跑：本机未配置 `DASHSCOPE_API_KEY`。课程原有冒烟记录保留在
`agent/evals/runs/w01-smoke-20261024/`。
