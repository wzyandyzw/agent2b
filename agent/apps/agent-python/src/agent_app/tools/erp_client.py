"""真实 ERP 访问（httpx）。实现 ErpGateway；失败一律变成 ToolFailure 的分类，不让 httpx 异常漏到 Loop。
错误分层：调用 / 解析错误（malformed）、业务无数据（not_found）、上游临时故障（timeout / upstream_error）。"""
from __future__ import annotations

import httpx

from agent_app.contracts import ToolFailure


class ErpClient:
    def __init__(self, base_url: str, api_key: str, transport: httpx.BaseTransport | None = None) -> None:
        self._client = httpx.Client(base_url=base_url, headers={"X-Api-Key": api_key}, transport=transport)

    def _get(self, path: str, params: dict | None = None, *, timeout_s: float) -> dict:
        try:
            r = self._client.get(path, params=params, timeout=timeout_s)
        except httpx.TimeoutException as e:
            raise ToolFailure("timeout", "client_timeout", f"ERP 请求超时（{timeout_s}s）：{type(e).__name__}") from e
        except httpx.HTTPError as e:
            raise ToolFailure("upstream_error", "http_error", f"ERP 请求失败：{type(e).__name__}") from e
        body = _problem(r)
        if r.status_code == 404:
            raise ToolFailure("not_found", body.get("code", "not_found"), body.get("detail", "不存在"))
        if r.status_code == 504 or body.get("code") == "gateway_timeout":
            raise ToolFailure("timeout", body.get("code", "gateway_timeout"), body.get("detail", "ERP 网关超时"))
        if r.status_code >= 400:
            raise ToolFailure("upstream_error", body.get("code", str(r.status_code)),
                              body.get("detail", f"ERP 返回 {r.status_code}"))
        if not body and r.content:
            raise ToolFailure("malformed", "not_json", "ERP 返回的不是 JSON，不能当结果")
        return body

    def get_product(self, sku: str, *, timeout_s: float) -> dict:
        return self._get(f"/v1/products/{sku}", timeout_s=timeout_s)

    def get_inventory(self, sku: str, qty: int, *, timeout_s: float) -> dict:
        return self._get(f"/v1/inventory/{sku}", {"qty": qty}, timeout_s=timeout_s)

    def get_shipment(self, tracking_no: str, *, timeout_s: float) -> dict:
        return self._get(f"/v1/shipments/{tracking_no}", timeout_s=timeout_s)

    def get_order(self, order_id: str, *, timeout_s: float) -> dict:
        return self._get(f"/v1/orders/{order_id}", timeout_s=timeout_s)


def _problem(r: httpx.Response) -> dict:
    try:
        return r.json()
    except ValueError:
        return {}
