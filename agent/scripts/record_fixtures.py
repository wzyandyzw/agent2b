"""从跑着的模拟 ERP 录 fixture：fixture 不手写，永远是 ERP 数据的快照。
用法：uv run --project apps/agent-python python scripts/record_fixtures.py [--base http://localhost:9100]
输出：apps/agent-python/tests/fixtures/erp/<name>.json，每个文件 = 请求 + 状态 + 响应体。"""
import argparse
import datetime as dt
import json
import pathlib
import sys

import httpx

CASES = [  # (文件名, 路径, 查询)
    ("products_X200", "/v1/products/X200", {}),
    ("products_X200-Pro", "/v1/products/X200-Pro", {}),
    ("products_T200", "/v1/products/T200", {}),
    ("products_X999_404", "/v1/products/X999", {}),
    ("inventory_X200_qty1", "/v1/inventory/X200", {"qty": 1}),
    ("inventory_X200_qty2", "/v1/inventory/X200", {"qty": 2}),
    ("inventory_T200_qty1", "/v1/inventory/T200", {"qty": 1}),
    ("inventory_X999_404", "/v1/inventory/X999", {"qty": 1}),
    ("shipments_SF1234567890", "/v1/shipments/SF1234567890", {}),
    ("shipments_SF0000000000_404", "/v1/shipments/SF0000000000", {}),
    ("orders_ORD-10086", "/v1/orders/ORD-10086", {}),
    ("orders_ORD-99999_404", "/v1/orders/ORD-99999", {}),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:9100")
    ap.add_argument("--api-key", default="east-demo-key")
    ap.add_argument("--out", default=str(pathlib.Path(__file__).resolve().parents[1] / "apps/agent-python/tests/fixtures/erp"))
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with httpx.Client(base_url=a.base, headers={"X-Api-Key": a.api_key}, timeout=5) as c:
        health = c.get("/health").json()
        for name, path, query in CASES:
            r = c.get(path, params=query)
            rec = {"recorded_at": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds"),
                   "erp_version": health.get("version"), "erp_now": health.get("now"), "scenario": health.get("scenario"),
                   "request": {"method": "GET", "path": path, "query": query},
                   "status": r.status_code, "content_type": r.headers.get("content-type", ""),
                   "body": r.json()}
            (out / f"{name}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"{r.status_code}  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
