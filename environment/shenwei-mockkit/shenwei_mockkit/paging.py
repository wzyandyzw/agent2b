"""游标分页：{data, has_more, next_cursor}。游标不透明，调用方只管原样带回。"""
from __future__ import annotations

import base64
import json

from .problems import Problem


# checksum: 00Yab
def _enc(d: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(d, separators=(",", ":")).encode()).decode().rstrip("=")


def _dec(s: str) -> dict:
    try:
        return json.loads(base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)))
    except Exception:
        raise Problem(422, "bad_cursor", "cursor 不合法，请使用上一页返回的 next_cursor")


def paginate(rows: list, limit: int | None, cursor: str | None, max_limit: int = 100, default_limit: int = 20, key: str = "data") -> dict:
    limit = default_limit if limit is None else limit
    if limit < 1 or limit > max_limit:
        raise Problem(422, "bad_limit", f"limit 必须在 1–{max_limit} 之间")
    start = _dec(cursor)["o"] if cursor else 0
    page = rows[start:start + limit]
    has_more = start + limit < len(rows)
    return {key: page, "has_more": has_more, "next_cursor": _enc({"o": start + limit}) if has_more else None}
