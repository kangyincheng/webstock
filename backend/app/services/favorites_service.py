"""自选股持久化：SQLite（比原 JSON 更安全、更快、支持索引/查询）。"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any, Dict, List, Optional

DB_LOCK = threading.Lock()


def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.strptime(str(s), "%Y-%m-%d").date()
    except Exception:
        return None


class FavoritesService:

    def __init__(self, db_path: Optional[str] = None):
        base = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        self.db_path = db_path or os.path.join(base, "backend", "data", "favorites.db")
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
            CREATE TABLE IF NOT EXISTS favorite_stocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 0,
                code TEXT NOT NULL,
                name TEXT NOT NULL,
                buy_date TEXT,
                buy_price REAL,
                current_price REAL,
                note TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now','localtime')),
                updated_at TEXT DEFAULT (datetime('now','localtime'))
            );
            CREATE INDEX IF NOT EXISTS idx_fav_code ON favorite_stocks(code);
            CREATE INDEX IF NOT EXISTS idx_fav_user ON favorite_stocks(user_id);

            CREATE TABLE IF NOT EXISTS favorite_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fav_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                due_date TEXT NOT NULL,
                notified INTEGER DEFAULT 0,
                FOREIGN KEY(fav_id) REFERENCES favorite_stocks(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_evt_fav ON favorite_events(fav_id);
            CREATE INDEX IF NOT EXISTS idx_evt_due ON favorite_events(due_date);
            """)
            # 老表升级：加 user_id 列
            try:
                cols = [r[1] for r in c.execute("PRAGMA table_info(favorite_stocks)").fetchall()]
                if "user_id" not in cols:
                    c.execute("ALTER TABLE favorite_stocks ADD COLUMN user_id INTEGER NOT NULL DEFAULT 0")
                    c.execute("CREATE INDEX IF NOT EXISTS idx_fav_user ON favorite_stocks(user_id)")
            except Exception:
                pass

    # --------- CRUD ---------
    def add(self, data: Dict[str, Any]) -> int:
        with self._conn() as c:
            cur = c.execute(
                """INSERT INTO favorite_stocks(user_id,code,name,buy_date,buy_price,current_price,note)
                   VALUES (?,?,?,?,?,?,?)""",
                (int(data.get("user_id") or 0),
                 data.get("code", ""), data.get("name", ""),
                 data.get("buy_date") or None,
                 float(data["buy_price"]) if data.get("buy_price") not in (None, "") else None,
                 float(data["current_price"]) if data.get("current_price") not in (None, "") else None,
                 data.get("note") or ""),
            )
            fav_id = cur.lastrowid
            for ev in data.get("events") or []:
                c.execute(
                    "INSERT INTO favorite_events(fav_id,title,due_date) VALUES (?,?,?)",
                    (fav_id, ev.get("title", ""), ev.get("due_date", "")),
                )
            return fav_id

    def update(self, fav_id: int, data: Dict[str, Any]) -> bool:
        with self._conn() as c:
            row = c.execute("SELECT id FROM favorite_stocks WHERE id=?", (fav_id,)).fetchone()
            if not row:
                return False
            c.execute(
                """UPDATE favorite_stocks SET user_id=?,code=?,name=?,buy_date=?,buy_price=?,
                   current_price=?,note=?,updated_at=datetime('now','localtime') WHERE id=?""",
                (int(data.get("user_id") or 0),
                 data.get("code", ""), data.get("name", ""),
                 data.get("buy_date") or None,
                 float(data["buy_price"]) if data.get("buy_price") not in (None, "") else None,
                 float(data["current_price"]) if data.get("current_price") not in (None, "") else None,
                 data.get("note") or "", fav_id),
            )
            # 重置 events：先删后插
            c.execute("DELETE FROM favorite_events WHERE fav_id=?", (fav_id,))
            for ev in data.get("events") or []:
                c.execute(
                    "INSERT INTO favorite_events(fav_id,title,due_date) VALUES (?,?,?)",
                    (fav_id, ev.get("title", ""), ev.get("due_date", "")),
                )
            return True

    def delete(self, fav_id: int) -> bool:
        with self._conn() as c:
            c.execute("DELETE FROM favorite_events WHERE fav_id=?", (fav_id,))
            cur = c.execute("DELETE FROM favorite_stocks WHERE id=?", (fav_id,))
            return cur.rowcount > 0

    def list_all(self) -> List[Dict[str, Any]]:
        with self._conn() as c:
            stocks = [dict(r) for r in c.execute(
                "SELECT * FROM favorite_stocks ORDER BY id ASC").fetchall()]
            events_by_fav: Dict[int, List[Dict[str, Any]]] = {}
            for ev in c.execute("SELECT * FROM favorite_events ORDER BY due_date ASC").fetchall():
                d = dict(ev)
                events_by_fav.setdefault(d["fav_id"], []).append(d)
        out = []
        today = date.today().isoformat()
        for s in stocks:
            evts = events_by_fav.get(s["id"], [])
            # 最近到期的事件（剔除空日期）
            valid = [e for e in evts if e.get("due_date")]
            valid.sort(key=lambda x: x["due_date"])
            nearest = valid[0] if valid else None
            gain = None
            if s.get("buy_price") and s.get("current_price"):
                gain = round((s["current_price"] - s["buy_price"]) / s["buy_price"] * 100, 2)
            out.append({
                "id": s["id"],
                "user_id": s.get("user_id") or 0,
                "code": s["code"],
                "name": s["name"],
                "buy_date": s["buy_date"],
                "buy_price": s["buy_price"],
                "current_price": s["current_price"],
                "gain_pct": gain,
                "note": s["note"],
                "events": [{"title": e["title"], "due_date": e["due_date"],
                            "notified": bool(e.get("notified"))} for e in evts],
                "nearest_event": nearest["title"] if nearest else None,
                "nearest_due": nearest["due_date"] if nearest else None,
                "event_overdue": bool(nearest and nearest["due_date"] <= today
                                      and not nearest.get("notified")),
                "created_at": s["created_at"],
                "updated_at": s["updated_at"],
            })
        return out

    def update_prices(self, prices: Dict[str, float]) -> int:
        """prices: code -> current_price"""
        rows = [(float(v), k) for k, v in prices.items() if v is not None]
        if not rows:
            return 0
        with self._conn() as c:
            c.executemany(
                "UPDATE favorite_stocks SET current_price=?, updated_at=datetime('now','localtime') WHERE code=?",
                rows,
            )
            return c.total_changes

    def check_due_events(self) -> List[Dict[str, Any]]:
        """返回到期且未通知过的事件清单，并标记已通知（一次）。"""
        today = date.today().isoformat()
        with self._conn() as c:
            rows = c.execute("""
                SELECT e.id AS eid, e.title, e.due_date, s.id AS fav_id, s.code, s.name
                FROM favorite_events e JOIN favorite_stocks s ON s.id = e.fav_id
                WHERE e.due_date<=? AND e.notified=0
                ORDER BY e.due_date ASC
            """, (today,)).fetchall()
            result = [dict(r) for r in rows]
            if result:
                ids = [r["eid"] for r in result]
                c.executemany("UPDATE favorite_events SET notified=1 WHERE id=?", [(i,) for i in ids])
            return result

    # ---------- JSON 兼容导入（迁移原有 favorites.json） ----------
    def import_json(self, json_path: str) -> int:
        if not os.path.exists(json_path):
            return 0
        with open(json_path, "r", encoding="utf-8") as f:
            items = json.load(f)
        n = 0
        for it in items:
            try:
                self.add(it)
                n += 1
            except Exception:
                pass
        return n
