# S6 业务环境 · W1（模拟 ERP）

课程提供，只调不改。W1 只用到模拟 ERP `shenwei-erp`（端口 9100）；SCRM 与知识服务从用到它们的那一周起另发。
课件里说的「`环境/`」就是这个文件夹，解压后可以改名叫 `环境`。

| 目录 / 文件 | 是什么 |
|---|---|
| `shenwei-erp/` | 模拟 ERP 0.2.0：商品与规格（110 SKU）、库存交期、客户、订单物流、报价、工单；虚拟时钟、故障注入 |
| `shenwei-mockkit/` | ERP 依赖的规范层（错误体、分页、幂等、故障注入），不用单独启动 |
| `ERP-interface.md` | ERP 接口说明 |
| `API-conventions.md` | 鉴权、错误体、分页、幂等等通用约定 |
| `openapi/erp-v1.json` | OpenAPI 导出（服务启动时自动刷新） |
| `docker-compose.yml` | 用 Docker 启动 |

## 启动（二选一）

不用 Docker（需要 [uv](https://docs.astral.sh/uv/)）：

```bash
cd shenwei-erp
uv sync --python 3.12
uv run python -m shenwei_erp        # http://localhost:9100/docs
```

用 Docker：

```bash
docker compose up -d                # 在本文件夹里运行
```

第一次启动会自动建库并灌入种子数据：不用 Docker 时库在 `shenwei-erp/erp.db`（课件里用 `sqlite3` 查的就是它）；用 Docker 时在卷 `erp-data` 里。想回到初始数据：前者停掉服务、删掉 `erp.db` 再启动；后者 `docker compose down -v` 再 `up -d`。

## 检查是否跑通

```bash
curl -s -H 'X-Api-Key: east-demo-key' localhost:9100/v1/products/X200
curl -s -H 'X-Api-Key: east-demo-key' 'localhost:9100/v1/inventory/X200?qty=1'
cd shenwei-erp && uv run pytest -q   # 自测
```

身份约定：`X-Api-Key: east-demo-key`（华东）/ `south-demo-key`（华南），跨租户 404。管理接口 `/_admin/*` 用 `X-Admin-Token: local-admin`，业务代码不许调。
