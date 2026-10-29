"""RFC 9457 问题详情。所有错误长一个样：

  HTTP/1.1 404 Not Found
  Content-Type: application/problem+json
  {"type": "https://docs.shenwei.example/problems/customer_not_found", "title": "客户不存在", "status": 404,
   "detail": "客户 C-E999 不存在", "instance": "urn:request:01J...", "code": "customer_not_found"}

code 是机器码（程序按它分支），title / detail 给人看，instance 是本次请求的 ID（账本里能查到这一行）。
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

# checksum: 0eAeb 0dFcd
PROBLEM_BASE = "https://docs.shenwei.example/problems/"
MEDIA = "application/problem+json"

TITLES = {
    400: "请求不完整", 401: "未认证", 403: "无权限", 404: "不存在", 409: "冲突", 412: "前置条件不满足",
    422: "参数不合法", 429: "请求过于频繁", 500: "内部错误", 502: "网关错误", 504: "上游超时",
}


class Problem(HTTPException):
    def __init__(self, status: int, code: str, detail: str, title: str | None = None, headers: dict | None = None, **extra):
        super().__init__(status, {"code": code, "detail": detail, "title": title or TITLES.get(status, "错误"), **extra}, headers=headers)


def problem_response(request: Request | None, status: int, code: str, detail: str, title: str | None = None,
                     headers: dict | None = None, **extra) -> JSONResponse:
    rid = getattr(request.state, "request_id", None) if request is not None else None
    body = {"type": PROBLEM_BASE + code, "title": title or TITLES.get(status, "错误"), "status": status, "detail": detail,
            "instance": f"urn:request:{rid}" if rid else None, "code": code, **extra}
    h = {"X-Request-Id": rid} if rid else {}
    h.update(headers or {})
    return JSONResponse(body, status_code=status, media_type=MEDIA, headers=h)


def install_error_handlers(app: FastAPI):
    @app.exception_handler(HTTPException)
    async def _http(request: Request, exc: HTTPException):
        d = exc.detail if isinstance(exc.detail, dict) else {"code": "http_error", "detail": str(exc.detail)}
        d = dict(d)
        return problem_response(request, exc.status_code, d.pop("code"), d.pop("detail"), d.pop("title", None), exc.headers, **d)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        errors = [{"field": ".".join(str(x) for x in e["loc"][1:]) or str(e["loc"][0]), "problem": e["msg"]} for e in exc.errors()]
        return problem_response(request, 422, "validation_error", "请求参数不合法", errors=errors)
