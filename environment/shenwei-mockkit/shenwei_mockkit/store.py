"""存储：一个 SQLite 文件装业务表 + 内核表（键值、幂等、请求日志、故障、事件、审计）。

业务表由各系统自己建（传 schema 进来），内核表这里建。一次业务写入 = 一个事务，幂等记录、审计、事件与业务记录同事务提交。
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

# generated: 01Ub7 00Yab
TZ = timezone(timedelta(hours=8))

KIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS idem (
  tenant TEXT, scope TEXT, k TEXT, body_hash TEXT, status INTEGER, response TEXT, request_id TEXT,
  state TEXT DEFAULT 'done', created_at TEXT, PRIMARY KEY (tenant, scope, k));
CREATE TABLE IF NOT EXISTS reqlog (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT, at TEXT, tenant TEXT, actor TEXT, method TEXT, path TEXT,
  status INTEGER, fault TEXT, body TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS faults (
  id INTEGER PRIMARY KEY AUTOINCREMENT, target TEXT, mode TEXT, times_left INTEGER, tenant TEXT, params TEXT);
CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY, tenant TEXT, type TEXT, object_type TEXT, object_id TEXT, occurred_at TEXT,
  sequence INTEGER, deliver_seq INTEGER, duplicate INTEGER DEFAULT 0, payload TEXT,
  published INTEGER DEFAULT 0, delivered INTEGER DEFAULT 0, attempts TEXT DEFAULT '[]');
CREATE TABLE IF NOT EXISTS audit (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, tenant TEXT, actor TEXT, request_id TEXT, action TEXT,
  object_type TEXT, object_id TEXT, before TEXT, after TEXT);
"""
KIT_TABLES = ["idem", "reqlog", "faults", "events", "audit"]


class Store:
    def __init__(self, path: str, schema: str, business_tables: list[str], default_now: str):
        self.path = path
        self.default_now = default_now
        self.business_tables = business_tables
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(KIT_SCHEMA + schema)

    @contextmanager
    def tx(self):
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield self.db
                self.db.execute("COMMIT")
            except Exception:
                self.db.execute("ROLLBACK")
                raise

    def q(self, sql, *args) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def one(self, sql, *args) -> dict | None:
        r = self.q(sql, *args)
        return r[0] if r else None

    def cols(self, table: str) -> list[str]:
        return [r["name"] for r in self.q(f"PRAGMA table_info({table})")]

    # ---- 键值 ----
    def get(self, k, default=None):
        r = self.one("SELECT v FROM kv WHERE k=?", k)
        return json.loads(r["v"]) if r else default

    def set(self, k, v, db=None):
        (db or self.db).execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (k, json.dumps(v, ensure_ascii=False)))

    # ---- 虚拟时钟 ----
    def now(self) -> datetime:
        return parse(self.get("now", self.default_now))

    def now_iso(self) -> str:
        return iso(self.now())

    def today(self) -> date:
        return self.now().date()

    def next_sequence(self, db=None) -> int:
        n = int(self.get("sequence", 0)) + 1
        self.set("sequence", n, db)
        return n

    # ---- 审计 ----
    def audit(self, db, tenant, actor, request_id, action, object_type, object_id, before=None, after=None):
        db.execute("INSERT INTO audit (at,tenant,actor,request_id,action,object_type,object_id,before,after) VALUES (?,?,?,?,?,?,?,?,?)",
                   (self.now_iso(), tenant, actor, request_id, action, object_type, object_id,
                    json.dumps(before, ensure_ascii=False) if before is not None else None,
                    json.dumps(after, ensure_ascii=False) if after is not None else None))

    def wipe(self):
        with self.tx() as db:
            for t in self.business_tables + KIT_TABLES:
                db.execute(f"DELETE FROM {t}")
            db.execute("DELETE FROM kv")
            db.execute("DELETE FROM sqlite_sequence")

    # ---- 场景装载用的 upsert：按主键合并，缺的列用旧值或 None，list/dict 自动转 JSON ----
    def upsert(self, db, table: str, keys: tuple[str, ...], row: dict, defaults: dict | None = None):
        cols = self.cols(table)
        where = " AND ".join(f"{k}=?" for k in keys)
        old = self.one(f"SELECT * FROM {table} WHERE {where}", *[row[k] for k in keys])
        merged = {**{c: None for c in cols}, **({} if old else (defaults or {})), **(old or {}), **{k: v for k, v in row.items() if k in cols}}
        for c, v in merged.items():
            if isinstance(v, (list, dict)):
                merged[c] = json.dumps(v, ensure_ascii=False)
            elif isinstance(v, bool):
                merged[c] = int(v)
        db.execute(f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                   [merged[c] for c in cols])
        return old


def iso(dt: datetime) -> str:
    return dt.astimezone(TZ).isoformat()


def parse(s: str) -> datetime:
    d = datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=TZ)


def today_of(s: str) -> date:
    return parse(s).date()
