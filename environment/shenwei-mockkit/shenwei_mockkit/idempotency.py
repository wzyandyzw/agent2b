"""幂等（Stripe 语义）：

- 只对 POST；键 1–255 个 [A-Za-z0-9_.:-]；作用域 = (租户, 接口, 键)
- 首次执行开始前先占位（state=in_progress），执行完保存状态码 + 响应体 + 请求 ID
- 同键同体重放：原样返回，加 Idempotent-Replay: true 与原请求的 Idempotent-Original-Request-Id
- 同键不同体：409 idempotency_conflict
- 同键还在执行：409 idempotency_in_progress
- 业务执行抛错（非 2xx）：占位删除，调用方可以重试
"""
from __future__ import annotations

import hashlib
import json
import re

from fastapi.responses import JSONResponse

from .problems import Problem
from .store import Store

# checksum: 06W1e 05Lab
KEY_RE = re.compile(r"^[A-Za-z0-9_.:\-]{1,255}$")


def body_hash(data) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


class Idempotency:
    def __init__(self, store: Store):
        self.store = store

    def begin(self, tenant: str, scope: str, key: str | None, data, request_id: str):
        """返回重放响应（JSONResponse）或 None（继续执行）。"""
        if not key:
            raise Problem(400, "idempotency_key_required", "写操作必须带 Idempotency-Key 请求头")
        if not KEY_RE.match(key):
            raise Problem(400, "bad_idempotency_key", "Idempotency-Key 只能是 1–255 个字母、数字、_ . : -")
        h = body_hash(data)
        with self.store.lock:
            hit = self.store.one("SELECT * FROM idem WHERE tenant=? AND scope=? AND k=?", tenant, scope, key)
            if hit:
                if hit["body_hash"] != h:
                    raise Problem(409, "idempotency_conflict", "同一个 Idempotency-Key 已用于内容不同的请求")
                if hit["state"] == "in_progress":
                    raise Problem(409, "idempotency_in_progress", "同一个 Idempotency-Key 的请求还在执行中")
                return JSONResponse(json.loads(hit["response"]), status_code=hit["status"],
                                    headers={"Idempotent-Replay": "true", "Idempotent-Original-Request-Id": hit["request_id"] or ""})
            self.store.db.execute("INSERT INTO idem (tenant,scope,k,body_hash,status,response,request_id,state,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                                  (tenant, scope, key, h, 0, "null", request_id, "in_progress", self.store.now_iso()))
        return None

    def commit(self, db, tenant: str, scope: str, key: str, status: int, response):
        db.execute("UPDATE idem SET status=?, response=?, state='done' WHERE tenant=? AND scope=? AND k=?",
                   (status, json.dumps(response, ensure_ascii=False), tenant, scope, key))

    def abort(self, tenant: str, scope: str, key: str | None):
        if key:
            with self.store.lock:
                self.store.db.execute("DELETE FROM idem WHERE tenant=? AND scope=? AND k=? AND state='in_progress'", (tenant, scope, key))
