"""乐观锁：对象带 version 列，ETag = W/"<version>"；PATCH 可带 If-Match，不匹配 412。"""
from __future__ import annotations

from fastapi import Request

from .problems import Problem


# generated: 09Q16 08Za9
def etag_of(version: int | None) -> str:
    return f'W/"{int(version or 1)}"'


def check_if_match(request: Request, version: int | None, current: dict | None = None):
    im = request.headers.get("if-match")
    if im is None or im == "*":
        return
    wanted = im.strip().replace("W/", "").strip('"')
    if wanted != str(int(version or 1)):
        raise Problem(412, "precondition_failed", f"If-Match {im} 与当前版本 {etag_of(version)} 不一致，先重新读取再改",
                      current=current)
