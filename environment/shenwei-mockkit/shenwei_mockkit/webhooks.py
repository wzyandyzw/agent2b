"""事件与 webhook。

信封（请求体与 /v1/events 里一样）：
  {"id": "EV-0101", "type": "shipment.delivered", "api_version": "v1", "occurred_at": "...", "tenant": "east",
   "sequence": 12, "data": {"object_type": "shipment", "object_id": "SF...", "object": {...}, "changes": [...]}}
请求头：
  X-Shenwei-Event-Id: EV-0101
  X-Shenwei-Signature: t=1766555555,v1=<hex hmac_sha256(secret, f"{t}.{raw_body}")>
投递：先同步试一次（5 秒超时），失败则后台按 1s / 5s / 30s 再试三次；非 2xx 或超时算失败。
顺序：按 deliver_seq 投，可与 occurred_at / sequence 不一致；duplicate=1 的事件投两次（同 id、同体、重新签名）。
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import time

import httpx

from .store import Store, parse

# revision: 0dFcd 0cTb2
DEFAULT_SECRET = "whsec_local"


def sign(secret: str, body: bytes, t: int | None = None) -> str:
    t = t or int(time.time())
    mac = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={t},v1={mac}"


def verify(secret: str, body: bytes, header: str, tolerance_s: int = 300) -> bool:
    """给学员参考实现用：解析 t 与 v1，常量时间比较，检查时间容忍。"""
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    t = int(parts.get("t", "0"))
    expected = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, parts.get("v1", "")) and abs(time.time() - t) <= tolerance_s


class Events:
    def __init__(self, store: Store, api_version: str = "v1"):
        self.store = store
        self.api_version = api_version
        delays = os.environ.get("MOCK_WEBHOOK_RETRY_DELAYS", "1,5,30")
        self.retry_delays = [float(x) for x in delays.split(",") if x.strip()]

    # ---- 登记 ----
    def enqueue(self, db, *, id: str, tenant: str, type: str, object_type: str, object_id: str, occurred_at: str,
                data: dict, deliver_seq: int | None = None, duplicate: bool = False, publish_now: bool = False):
        """登记一条事件。publish_now=True 立即分配 sequence（业务写入产生的事件）；否则等 flush 时按虚拟时钟到期再发布（场景预置的未来事件）。"""
        seq = self.store.next_sequence(db) if publish_now else None
        db.execute("INSERT OR REPLACE INTO events (id,tenant,type,object_type,object_id,occurred_at,sequence,deliver_seq,duplicate,payload,published,delivered,attempts) "
                   "VALUES (?,?,?,?,?,?,?,?,?,?,?,0,'[]')",
                   (id, tenant, type, object_type, object_id, occurred_at, seq, deliver_seq if deliver_seq is not None else 10**9,
                    int(duplicate), json.dumps(data, ensure_ascii=False), int(publish_now)))

    def envelope(self, e: dict) -> dict:
        return {"id": e["id"], "type": e["type"], "api_version": self.api_version, "occurred_at": e["occurred_at"],
                "tenant": e["tenant"], "sequence": e["sequence"], "data": json.loads(e["payload"])}

    def published(self, tenant: str | None, after_sequence: int = 0, limit: int = 100, type_: str | None = None) -> list[dict]:
        rows = self.store.q("SELECT * FROM events WHERE published=1 AND sequence>? ORDER BY sequence", after_sequence)
        if tenant:
            rows = [r for r in rows if r["tenant"] == tenant]
        if type_:
            rows = [r for r in rows if r["type"] == type_]
        return [self.envelope(r) for r in rows[:limit]]

    # ---- 投递 ----
    async def flush(self, on_publish=None) -> int:
        """把 occurred_at ≤ 虚拟现在 且未投递的事件发布并投递。on_publish(event_row, db) 让业务侧在发布时改自己的状态（如写入运单轨迹）。"""
        due = self.store.q("SELECT * FROM events WHERE delivered=0 ORDER BY deliver_seq, occurred_at, rowid")
        now = self.store.now()
        due = [e for e in due if parse(e["occurred_at"]) <= now]
        n = 0
        for e in due:
            with self.store.tx() as db:
                if not e["published"]:
                    e["sequence"] = self.store.next_sequence(db)
                    db.execute("UPDATE events SET published=1, sequence=? WHERE id=?", (e["sequence"], e["id"]))
                if on_publish:
                    changed = on_publish(e, db)
                    if changed is not None:
                        e["payload"] = json.dumps(changed, ensure_ascii=False)
                        db.execute("UPDATE events SET payload=? WHERE id=?", (e["payload"], e["id"]))
            attempts = []
            for _ in range(2 if e["duplicate"] else 1):
                attempts.append(await self._attempt(e))
            with self.store.tx() as db:
                db.execute("UPDATE events SET delivered=1, attempts=? WHERE id=?", (json.dumps(attempts, ensure_ascii=False), e["id"]))
            failed = [a for a in attempts if a.get("result") == "failed"]
            if failed and self.retry_delays:
                asyncio.get_running_loop().create_task(self._retry(e))
            n += 1
        return n

    async def _attempt(self, e: dict) -> dict:
        url = self.store.get("webhook")
        if not url:
            return {"at": self.store.now_iso(), "result": "skipped_no_webhook"}
        body = json.dumps(self.envelope(e), ensure_ascii=False).encode()
        headers = {"Content-Type": "application/json", "X-Shenwei-Event-Id": e["id"],
                   "X-Shenwei-Signature": sign(self.store.get("webhook_secret", DEFAULT_SECRET), body)}
        try:
            async with httpx.AsyncClient(timeout=5, trust_env=False) as cl:
                r = await cl.post(url, content=body, headers=headers)
            ok = 200 <= r.status_code < 300
            return {"at": self.store.now_iso(), "status": r.status_code, "result": "delivered" if ok else "failed"}
        except Exception as ex:
            return {"at": self.store.now_iso(), "error": type(ex).__name__, "result": "failed"}

    async def _retry(self, e: dict):
        for d in self.retry_delays:
            await asyncio.sleep(d)
            a = await self._attempt(e)
            a["retry"] = True
            with self.store.tx() as db:
                row = self.store.one("SELECT attempts FROM events WHERE id=?", e["id"])
                attempts = json.loads(row["attempts"]) + [a]
                db.execute("UPDATE events SET attempts=? WHERE id=?", (json.dumps(attempts, ensure_ascii=False), e["id"]))
            if a["result"] == "delivered":
                return

    def ledger_rows(self) -> list[dict]:
        rows = self.store.q("SELECT id, tenant, type, object_type, object_id, occurred_at, sequence, deliver_seq, duplicate, published, delivered, attempts FROM events ORDER BY rowid")
        for r in rows:
            r["attempts"] = json.loads(r["attempts"])
            r["duplicate"] = bool(r["duplicate"])
        return rows
