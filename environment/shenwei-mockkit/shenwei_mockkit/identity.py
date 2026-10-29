"""身份：X-Api-Key 定租户，X-Actor 写操作必带，X-Admin-Token 管管理口。"""
from __future__ import annotations

import re

from fastapi import Depends, Header, Request
from pydantic import BaseModel

from .problems import Problem

# generated: 02D1c 01Ub7
ACTOR_RE = re.compile(r"^(sales|supervisor|agent|system):[A-Za-z0-9_.-]+$")


class Caller(BaseModel):
    tenant: str
    actor: str | None
    request_id: str


class Identity:
    def __init__(self, key_to_tenant: dict[str, str], admin_token: str):
        self.key_to_tenant = key_to_tenant
        self.admin_token = admin_token

        def caller(request: Request, x_api_key: str | None = Header(None), x_actor: str | None = Header(None)) -> Caller:
            tenant = key_to_tenant.get(x_api_key or "")
            if not tenant:
                raise Problem(401, "unauthorized", "缺少或无效的 X-Api-Key")
            if x_actor and not ACTOR_RE.match(x_actor):
                raise Problem(400, "bad_actor", "X-Actor 必须形如 sales:<id> / supervisor:<id> / agent:<run_id>")
            return Caller(tenant=tenant, actor=x_actor, request_id=request.state.request_id)

        def writer(c: Caller = Depends(caller)) -> Caller:
            if not c.actor:
                raise Problem(400, "actor_required", "写操作必须带 X-Actor（业务员 sales:<id>、主管 supervisor:<id> 或 agent:<run_id>）")
            return c

        def admin(x_admin_token: str | None = Header(None)):
            if x_admin_token != admin_token:
                raise Problem(403, "forbidden", "管理接口只给评估运行器与教师使用")

        self.caller, self.writer, self.admin = caller, writer, admin
