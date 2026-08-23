"""操作审计服务：任何写操作（训练/自选增删/...）都会被记录，登录后可查看历史。"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

DB_LOCK = threading.Lock()

CATEGORY_LOGIN = "auth.login"
CATEGORY_LOGOUT = "auth.logout"
CATEGORY_REGISTER = "auth.register"
CATEGORY_CHANGE_PASSWORD = "auth.change_password"
CATEGORY_PREDICT_TRAIN = "predict.train"
CATEGORY_MODEL_DELETE = "predict.delete_model"
CATEGORY_FAV_ADD = "favorites.add"
CATEGORY_FAV_UPDATE = "favorites.update"
CATEGORY_FAV_DELETE = "favorites.delete"
CATEGORY_FAV_REFRESH = "favorites.refresh_prices"
CATEGORY_FAV_CHECK_EVENTS = "favorites.check_events"
CATEGORY_ST_SCAN = "market.st_scan"
CATEGORY_ST_REINSTATE_SCAN = "market.st_reinstate_scan"
CATEGORY_SECTOR_HEAT = "market.sector_heat"
CATEGORY_HOT_STOCKS = "market.hot_stocks"
CATEGORY_CBOND = "cbond.query"
CATEGORY_MISC = "misc"


class AuditService:
    def __init__(self, db_path: Optional[str] = None):
        base = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        self.db_path = db_path or os.path.join(base, "backend", "data", "auth.db")
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    @contextmanager
    def _conn(self):
        with DB_LOCK:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

    def _init_db(self):
        with self._conn() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER,                    -- NULL = 匿名用户
                username    TEXT,
                category    TEXT NOT NULL,              -- e.g. favorites.add / predict.train
                action      TEXT NOT NULL,              -- 简短中文说明
                target_key  TEXT,                       -- 自选ID/股票代码/模型名...
                ok          INTEGER NOT NULL DEFAULT 1, -- 1 success 0 error
                detail      TEXT,                       -- JSON 大字段: 请求/响应摘要
                ip          TEXT,
                ua          TEXT,
                created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
            );
            CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_logs(user_id);
            CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_audit_cat ON audit_logs(category);
            """)

    def log(self, *,
            user_id: Optional[int],
            username: Optional[str],
            category: str,
            action: str,
            ok: bool = True,
            target_key: Optional[str] = None,
            detail: Optional[Dict[str, Any]] = None,
            ip: Optional[str] = None,
            ua: Optional[str] = None) -> int:
        detail_str = None
        if detail is not None:
            try:
                detail_str = json.dumps(detail, ensure_ascii=False)
            except Exception:
                detail_str = str(detail)
        with self._conn() as c:
            cur = c.execute(
                """INSERT INTO audit_logs(user_id,username,category,action,target_key,ok,detail,ip,ua)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (int(user_id) if user_id is not None else None,
                 username,
                 category,
                 action,
                 target_key,
                 1 if ok else 0,
                 detail_str,
                 ip,
                 ua),
            )
            return cur.lastrowid

    # ---------- 查询 ----------
    def list_history(self, *,
                     user_id: Optional[int] = None,
                     category: Optional[str] = None,
                     only_errors: bool = False,
                     page: int = 1,
                     page_size: int = 20) -> Dict[str, Any]:
        page = max(1, int(page))
        page_size = min(200, max(1, int(page_size)))
        offset = (page - 1) * page_size

        where: List[str] = []
        params: List[Any] = []
        if user_id is not None:
            where.append("user_id=?")
            params.append(int(user_id))
        if category:
            where.append("category=?")
            params.append(category)
        if only_errors:
            where.append("ok=0")
        sql = "SELECT * FROM audit_logs"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
        params.extend([page_size, offset])
        with self._conn() as c:
            rows = [dict(r) for r in c.execute(sql, params).fetchall()]
            count_sql = "SELECT COUNT(1) AS n FROM audit_logs"
            if where:
                count_sql += " WHERE " + " AND ".join(where)
            total = int(c.execute(count_sql, params[:-2]).fetchone()["n"])

        # 大字段 detail 在列表里只摘要（防止一次返回太大）
        for r in rows:
            raw = r.get("detail")
            if isinstance(raw, str) and len(raw) > 256:
                r["detail"] = raw[:256] + "…"
        return {"rows": rows, "page": page, "page_size": page_size, "total": total, "pages": (total + page_size - 1) // page_size}

    def last_action(self, user_id: int) -> Optional[Dict[str, Any]]:
        with self._conn() as c:
            row = c.execute("""
                SELECT * FROM audit_logs
                WHERE user_id=? AND category NOT IN ('auth.login','auth.logout')
                ORDER BY id DESC LIMIT 1
            """, (int(user_id),)).fetchone()
            if not row:
                return None
            d = dict(row)
            raw = d.get("detail")
            if raw:
                try:
                    d["detail"] = json.loads(raw)
                except Exception:
                    pass
            return d

    def recent_failed(self, user_id: Optional[int] = None, limit: int = 10) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM audit_logs WHERE ok=0"
        params: List[Any] = []
        if user_id is not None:
            sql += " AND user_id=?"
            params.append(int(user_id))
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(int(limit))
        with self._conn() as c:
            return [dict(r) for r in c.execute(sql, params).fetchall()]


_INST: Optional[AuditService] = None
_LOCK = threading.Lock()


def audit() -> AuditService:
    global _INST
    if _INST is None:
        with _LOCK:
            if _INST is None:
                _INST = AuditService()
    return _INST
