"""契约测试：跑着的 ERP 与录下的 fixture 字段一致。ERP 不可达时跳过（CI 里不跑）。"""
import json
import pathlib

import httpx
import pytest

FIX = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "erp"
BASE = "http://localhost:9100"


def _alive():
    try:
        return httpx.get(f"{BASE}/health", timeout=1).status_code == 200
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(not _alive(), reason="ERP 9100 不可达")


@pytest.mark.parametrize("name", ["products_X200", "inventory_X200_qty2", "shipments_SF1234567890", "orders_ORD-10086"])
def test_live_erp_has_same_fields_as_fixture(name):
    rec = json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))
    r = httpx.get(BASE + rec["request"]["path"], params=rec["request"]["query"],
                  headers={"X-Api-Key": "east-demo-key"}, timeout=3)
    assert r.status_code == rec["status"]
    assert set(r.json().keys()) == set(rec["body"].keys()), "ERP 字段变了：先重录 fixture，再改工具"
