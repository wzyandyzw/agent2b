"""T05–T08：工具执行层的边界。先红：w1.6b 的执行器还没有参数校验，ERP 客户端还不区分超时。"""
import json

import httpx
import pytest

from agent_app.contracts import ToolCall
from agent_app.tools import ToolExecutor, ToolRegistry
from agent_app.tools.availability import GetAvailability
from agent_app.tools.erp_client import ErpClient
from agent_app.tools.product import GetProductSpec


# revision: 0fKc2
def _executor(erp):
    return ToolExecutor(ToolRegistry([GetProductSpec(erp), GetAvailability(erp)]))


def _call(name, args, cid="call_1"):
    return ToolCall(call_id=cid, name=name, arguments=args if isinstance(args, str) else json.dumps(args))


# T05 · W1-AC-01 只有已注册工具可执行
def test_t05_unknown_tool_is_rejected_without_running_anything(erp):
    r = _executor(erp).execute(_call("delete_everything", {"model": "X200"}), timeout_s=1)
    assert r.ok is False and r.error.category == "unknown_tool" and r.call_id == "call_1"
    assert sum(erp.calls.values()) == 0


# T06 · W1-AC-02 缺字段、空参数、非法 JSON 在进入业务函数前拦截
@pytest.mark.parametrize("args, code", [
    ({}, "missing_field"),
    ({"model": ""}, "empty_field"),
    ({"model": "   "}, "empty_field"),
    ({"model": 200}, "wrong_type"),
    ({"model": "X200", "unit_price": 1}, "unknown_field"),
    ('{"model": ', "invalid_json"),
])
def test_t06_bad_arguments_never_reach_erp(erp, args, code):
    r = _executor(erp).execute(_call("get_product_spec", args), timeout_s=1)
    assert r.ok is False and r.error.category == "input_error" and r.error.code == code
    assert erp.calls["get_product"] == 0


# T07 · 工具无数据 ≠ 网络失败：404 是业务无数据，不把空结果补成事实
def test_t07_not_found_is_business_no_data(erp):
    r = _executor(erp).execute(_call("get_product_spec", {"model": "X999"}), timeout_s=1)
    assert r.ok is False and r.error.category == "not_found" and r.error.code == "product_not_found"
    assert erp.calls["get_product"] == 1
    assert '"data"' not in r.content()   # 回注给模型的内容里没有伪造的 data


# T08 · W1-AC-05 工具超时记录为 timeout，不伪装成功、不包装成库存为零
def _erp_with(handler):
    return ErpClient("http://erp.test", "east-demo-key", transport=httpx.MockTransport(handler))


def test_t08_read_timeout_maps_to_timeout_category():
    def handler(request):
        raise httpx.ReadTimeout("read timed out", request=request)
    r = _executor(_erp_with(handler)).execute(_call("get_availability", {"model": "X200"}), timeout_s=0.5)
    assert r.ok is False and r.error.category == "timeout"
    body = json.loads(r.content())
    assert body["ok"] is False and "data" not in body and body["error"]["category"] == "timeout"


def test_t08_gateway_timeout_504_maps_to_timeout_category():
    def handler(request):
        return httpx.Response(504, json={"code": "gateway_timeout", "detail": "场景注入超时", "status": 504},
                              headers={"content-type": "application/problem+json"})
    r = _executor(_erp_with(handler)).execute(_call("get_availability", {"model": "X200"}), timeout_s=0.5)
    assert r.ok is False and r.error.category == "timeout" and r.error.code == "gateway_timeout"


def test_t08_malformed_body_is_not_a_result():
    def handler(request):
        return httpx.Response(200, content=b"<html>half", headers={"content-type": "application/json"})
    r = _executor(_erp_with(handler)).execute(_call("get_product_spec", {"model": "X200"}), timeout_s=0.5)
    assert r.ok is False and r.error.category == "malformed"


def test_t08_no_retry_by_default_counts_one_call(erp):
    from agent_app.doubles import FakeERP
    erp.inject("get_inventory", FakeERP.timeout())
    r = _executor(erp).execute(_call("get_availability", {"model": "X200", "qty": 2}), timeout_s=1)
    assert r.ok is False and r.error.category == "timeout"
    assert erp.calls["get_inventory"] == 1
