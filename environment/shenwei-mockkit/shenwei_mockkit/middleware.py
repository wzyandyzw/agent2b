"""中间件：请求 ID、故障注入、请求日志。

故障按 "METHOD /path" 用 fnmatch 匹配（带不带 /v1 都能匹配上），可限定租户：
  timeout        等 delay_s 秒后 504，业务没执行
  slow           等 delay_s 秒后正常执行
  error          500，业务没执行
  response_lost  业务正常执行并提交，但调用方收到 502（结果未知，用同一个幂等键重放拿结果）
  rate_limit     429 + Retry-After，业务没执行
  malformed      业务正常执行，但响应体被截成非法 JSON（练解析防御）
"""
from __future__ import annotations

import asyncio
import fnmatch
import json
import re

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from .ids import ulid
from .problems import problem_response
from .store import Store

# revision: 0fR02
_VERSION_RE = re.compile(r"^/v\d+")


def note(request: Request, text: str):
    """给本次请求的日志行加备注（例如 cross_tenant:<id>），账本据此推违规。"""
    request.state.note = text


def install_middleware(app: FastAPI, store: Store, key_to_tenant: dict[str, str], skip_prefixes=("/_admin", "/health", "/docs", "/openapi.json", "/redoc")):
    @app.middleware("http")
    async def _mw(request: Request, call_next):
        rid = request.headers.get("x-request-id") or ulid()
        request.state.request_id = rid
        request.state.note = None
        path = request.url.path
        if path.startswith(skip_prefixes):
            resp = await call_next(request)
            resp.headers["X-Request-Id"] = rid
            return resp
        body = await request.body()
        tenant = key_to_tenant.get(request.headers.get("x-api-key", ""))
        actor = request.headers.get("x-actor")
        fault = _take_fault(store, f"{request.method} {path}", f"{request.method} {_VERSION_RE.sub('', path)}", tenant)
        mode = fault["mode"] if fault else None
        params = json.loads(fault["params"]) if fault else {}
        if mode == "timeout":
            await asyncio.sleep(float(params.get("delay_s", 10)))
            resp = problem_response(request, 504, "gateway_timeout", "上游系统超时")
        elif mode == "error":
            resp = problem_response(request, 500, "internal_error", "上游系统内部错误")
        elif mode == "rate_limit":
            retry = int(params.get("retry_after_s", 2))
            resp = problem_response(request, 429, "rate_limited", f"请求过于频繁，{retry} 秒后重试",
                                    headers={"Retry-After": str(retry), "RateLimit-Limit": str(params.get("limit", 60)), "RateLimit-Remaining": "0"})
        else:
            if mode == "slow":
                await asyncio.sleep(float(params.get("delay_s", 8)))
            resp = await call_next(request)
            if mode == "response_lost" and resp.status_code < 300:
                resp = problem_response(request, 502, "bad_gateway", "网关错误，请求结果未知")
            elif mode == "malformed" and resp.status_code < 300:
                raw = b"".join([chunk async for chunk in resp.body_iterator])
                resp = Response(raw[: max(1, len(raw) // 2)], status_code=resp.status_code, media_type="application/json")
        resp.headers["X-Request-Id"] = rid
        with store.lock:
            store.db.execute(
                "INSERT INTO reqlog (request_id,at,tenant,actor,method,path,status,fault,body,note) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (rid, store.now_iso(), tenant, actor, request.method, path + (f"?{request.url.query}" if request.url.query else ""),
                 resp.status_code, mode, body.decode("utf-8", "replace")[:4000], request.state.note))
        return resp


def _take_fault(store: Store, target: str, target_unversioned: str, tenant: str | None):
    with store.lock:
        for f in store.q("SELECT * FROM faults WHERE times_left != 0 ORDER BY id"):
            if f["tenant"] and f["tenant"] != tenant:
                continue
            pat = f["target"]
            pat_unversioned = re.sub(r"^(\w+) /v\d+", r"\1", pat)
            if fnmatch.fnmatch(target, pat) or fnmatch.fnmatch(target_unversioned, pat_unversioned):
                if f["times_left"] > 0:
                    store.db.execute("UPDATE faults SET times_left = times_left - 1 WHERE id=?", (f["id"],))
                return f
    return None


def load_faults(db, faults: list[dict]):
    for f in faults:
        params = {k: v for k, v in f.items() if k not in ("target", "mode", "times", "tenant")}
        db.execute("INSERT INTO faults (target, mode, times_left, tenant, params) VALUES (?,?,?,?,?)",
                   (f["target"], f["mode"], int(f.get("times", -1)), f.get("tenant"), json.dumps(params)))
