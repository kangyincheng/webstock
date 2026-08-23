"""用户与鉴权服务：SQLite + JWT（access + refresh）。

与自选股/审计日志共用同一个 SQLite：backend/data/auth.db。
未登录用户可匿名使用（get_current_user_or_guest 返回 None），
但所有写操作会在审计表中以 user_id 记录（登录 = 具体用户；匿名 = NULL）。
"""
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from jose import JWTError, jwt
from passlib.context import CryptContext

DB_LOCK = threading.Lock()

# JWT 配置：生产环境请用环境变量 AUTH_SECRET 覆盖随机值。
# 这里默认生成一次持久化到文件，避免每次重启把所有老 token 判失效。
DEFAULT_SECRET_FILE = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "data", ".auth_secret"))
_SECRET_FALLBACK: Optional[str] = None


def _secret() -> str:
    global _SECRET_FALLBACK
    from_env = os.environ.get("AUTH_SECRET")
    if from_env:
        return from_env
    if _SECRET_FALLBACK:
        return _SECRET_FALLBACK
    os.makedirs(os.path.dirname(DEFAULT_SECRET_FILE), exist_ok=True)
    if os.path.exists(DEFAULT_SECRET_FILE):
        with open(DEFAULT_SECRET_FILE, "r", encoding="utf-8") as f:
            _SECRET_FALLBACK = f.read().strip()
    if not _SECRET_FALLBACK:
        import secrets
        _SECRET_FALLBACK = secrets.token_urlsafe(48)
        with open(DEFAULT_SECRET_FILE, "w", encoding="utf-8") as f:
            f.write(_SECRET_FALLBACK)
        try:
            os.chmod(DEFAULT_SECRET_FILE, 0o600)
        except Exception:
            pass
    return _SECRET_FALLBACK


JWT_ALG = "HS256"
ACCESS_TTL_MIN = 60 * 6          # access 6 小时
REFRESH_TTL_HOURS = 24 * 14      # refresh 14 天

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


class AuthDB:
    """用户 + 已吊销 refresh token。"""

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
            CREATE TABLE IF NOT EXISTS users (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                username   TEXT NOT NULL UNIQUE,
                email      TEXT UNIQUE,
                password   TEXT NOT NULL,     -- bcrypt
                nickname   TEXT,
                avatar_url TEXT,
                is_admin   INTEGER NOT NULL DEFAULT 0,
                is_active  INTEGER NOT NULL DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now','localtime')),
                updated_at TEXT DEFAULT (datetime('now','localtime')),
                last_login_at TEXT,
                last_login_ip TEXT,
                login_count INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_users_name ON users(username);
            CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

            CREATE TABLE IF NOT EXISTS revoked_refresh (
                jti      TEXT PRIMARY KEY,
                user_id  INTEGER NOT NULL,
                expires  INTEGER NOT NULL,
                revoked  INTEGER NOT NULL DEFAULT 1
            );
            CREATE INDEX IF NOT EXISTS idx_revoked_user ON revoked_refresh(user_id);
            """)

            # 兼容老库：补齐缺失列
            cols = [r[1] for r in c.execute("PRAGMA table_info(users)").fetchall()]
            if "login_count" not in cols:
                c.execute("ALTER TABLE users ADD COLUMN login_count INTEGER NOT NULL DEFAULT 0")
            if "is_admin" not in cols:
                c.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
            if "is_active" not in cols:
                c.execute("ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
            # 自动创建默认管理员（首次启动）
            admin_exists = c.execute("SELECT 1 FROM users WHERE is_admin=1 LIMIT 1").fetchone()
            if not admin_exists:
                import os as _os
                admin_pwd = _os.environ.get("ADMIN_INIT_PASSWORD") or "admin123456"
                admin_user = _os.environ.get("ADMIN_INIT_USERNAME") or "admin"
                c.execute(
                    "INSERT OR IGNORE INTO users(username,email,password,nickname,is_admin) VALUES (?,?,?,?,1)",
                    (admin_user, "admin@webstock.local", hash_password(admin_pwd), "系统管理员"),
                )


_DB_INST: Optional[AuthDB] = None
_LOCK = threading.Lock()


def auth_db() -> AuthDB:
    global _DB_INST
    if _DB_INST is None:
        with _LOCK:
            if _DB_INST is None:
                _DB_INST = AuthDB()
    return _DB_INST


# =============== 密码 / JWT ===============
def hash_password(pwd: str) -> str:
    return pwd_ctx.hash(pwd)


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return pwd_ctx.verify(raw, hashed)
    except Exception:
        return False


def _now_ts() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def issue_tokens(user_id: int, username: str, is_admin: bool = False) -> Dict[str, Any]:
    import secrets
    now = datetime.now(timezone.utc)
    access_exp = now + timedelta(minutes=ACCESS_TTL_MIN)
    refresh_exp = now + timedelta(hours=REFRESH_TTL_HOURS)
    jti_access = secrets.token_urlsafe(12)
    jti_refresh = secrets.token_urlsafe(16)
    common = {"sub": str(user_id), "username": username, "iat": int(now.timestamp()),
              "is_admin": 1 if is_admin else 0}
    access = jwt.encode({**common, "jti": jti_access, "exp": int(access_exp.timestamp()), "type": "access"},
                        _secret(), algorithm=JWT_ALG)
    refresh = jwt.encode({**common, "jti": jti_refresh, "exp": int(refresh_exp.timestamp()), "type": "refresh"},
                         _secret(), algorithm=JWT_ALG)
    return {
        "token_type": "bearer",
        "access_token": access,
        "refresh_token": refresh,
        "expires_in": int((access_exp - now).total_seconds()),
    }


def decode_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        payload = jwt.decode(token, _secret(), algorithms=[JWT_ALG])
        if payload.get("exp", 0) < _now_ts():
            return None
        return payload
    except JWTError:
        return None


# =============== 业务 ===============
def create_user(username: str, password: str,
                email: Optional[str] = None,
                nickname: Optional[str] = None) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    username = (username or "").strip()
    email = (email or "").strip() or None
    if len(username) < 3:
        return False, "用户名至少 3 位", None
    if len(password) < 6:
        return False, "密码至少 6 位", None
    with auth_db()._conn() as c:
        dup = c.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
        if dup:
            return False, "用户名已存在", None
        if email:
            dup_email = c.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            if dup_email:
                return False, "邮箱已被注册", None
        cur = c.execute(
            "INSERT INTO users(username,email,password,nickname) VALUES (?,?,?,?)",
            (username, email, hash_password(password), nickname or username),
        )
        uid = cur.lastrowid
    return True, "ok", get_user_by_id(uid)


def authenticate_password(username: str, password: str,
                          ip: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """验证密码成功后更新 last_login_at/ip，返回用户信息。"""
    username = (username or "").strip()
    if not username:
        return None
    with auth_db()._conn() as c:
        row = c.execute("SELECT * FROM users WHERE username=? OR email=?",
                        (username, username)).fetchone()
        if not row:
            return None
        if not verify_password(password, row["password"]):
            return None
        c.execute(
            "UPDATE users SET last_login_at=datetime('now','localtime'), last_login_ip=?, login_count=COALESCE(login_count,0)+1, updated_at=datetime('now','localtime') WHERE id=?",
            (ip or "", int(row["id"])),
        )
    return get_user_by_id(int(row["id"]))


def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    with auth_db()._conn() as c:
        row = c.execute(
            "SELECT id,username,email,nickname,avatar_url,is_admin,is_active,"
            "created_at,updated_at,last_login_at,last_login_ip,login_count "
            "FROM users WHERE id=?", (user_id,)).fetchone()
        return dict(row) if row else None


def get_user_public(user_id: int) -> Optional[Dict[str, Any]]:
    """比 get_user_by_id 多返回上一次操作（由 AuditService 提供）。"""
    return get_user_by_id(user_id)


def revoke_refresh(jti: str, user_id: int, exp_ts: int) -> None:
    with auth_db()._conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO revoked_refresh(jti,user_id,expires,revoked) VALUES (?,?,?,1)",
            (jti, user_id, int(exp_ts)),
        )


def is_refresh_revoked(jti: str) -> bool:
    with auth_db()._conn() as c:
        row = c.execute("SELECT 1 FROM revoked_refresh WHERE jti=? AND revoked=1", (jti,)).fetchone()
        return bool(row)


def change_password(user_id: int, old_password: str, new_password: str) -> Tuple[bool, str]:
    if len(new_password) < 6:
        return False, "新密码至少 6 位"
    with auth_db()._conn() as c:
        row = c.execute("SELECT password FROM users WHERE id=?", (user_id,)).fetchone()
        if not row:
            return False, "用户不存在"
        if not verify_password(old_password, row["password"]):
            return False, "原密码错误"
        c.execute("UPDATE users SET password=?, updated_at=datetime('now','localtime') WHERE id=?",
                  (hash_password(new_password), user_id))
        return True, "修改成功"


# =============== 管理员功能 ===============
def list_users(page: int = 1, page_size: int = 20, keyword: str = "",
               admin_only: bool = False) -> Dict[str, Any]:
    page = max(1, int(page))
    page_size = min(200, max(1, int(page_size)))
    offset = (page - 1) * page_size
    where = []
    params = []
    if keyword:
        where.append("(username LIKE ? OR email LIKE ? OR nickname LIKE ?)")
        kw = f"%{keyword}%"
        params.extend([kw, kw, kw])
    if admin_only:
        where.append("is_admin=1")
    sql = "SELECT id,username,email,nickname,avatar_url,is_admin,is_active,created_at,updated_at,last_login_at,last_login_ip,login_count FROM users"
    count_sql = "SELECT COUNT(1) AS n FROM users"
    if where:
        cl = " WHERE " + " AND ".join(where)
        sql += cl
        count_sql += cl
    sql += " ORDER BY id ASC LIMIT ? OFFSET ?"
    params.extend([page_size, offset])
    with auth_db()._conn() as c:
        rows = [dict(r) for r in c.execute(sql, params).fetchall()]
        total = int(c.execute(count_sql, params[:-2]).fetchone()["n"])
    return {"rows": rows, "page": page, "page_size": page_size, "total": total,
            "pages": (total + page_size - 1) // page_size}


def admin_set_user_admin(user_id: int, is_admin: bool) -> Tuple[bool, str]:
    with auth_db()._conn() as c:
        row = c.execute("SELECT id,is_admin FROM users WHERE id=?", (user_id,)).fetchone()
        if not row:
            return False, "用户不存在"
        c.execute("UPDATE users SET is_admin=?, updated_at=datetime('now','localtime') WHERE id=?",
                  (1 if is_admin else 0, user_id))
        return True, "已设置" if is_admin else "已取消管理员"


def admin_set_user_active(user_id: int, is_active: bool) -> Tuple[bool, str]:
    with auth_db()._conn() as c:
        row = c.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone()
        if not row:
            return False, "用户不存在"
        c.execute("UPDATE users SET is_active=?, updated_at=datetime('now','localtime') WHERE id=?",
                  (1 if is_active else 0, user_id))
        return True, "已启用" if is_active else "已停用"


def admin_reset_password(user_id: int, new_password: str) -> Tuple[bool, str]:
    if len(new_password) < 6:
        return False, "新密码至少 6 位"
    with auth_db()._conn() as c:
        row = c.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone()
        if not row:
            return False, "用户不存在"
        c.execute("UPDATE users SET password=?, updated_at=datetime('now','localtime') WHERE id=?",
                  (hash_password(new_password), user_id))
        return True, "密码已重置"


def admin_delete_user(user_id: int) -> Tuple[bool, str]:
    with auth_db()._conn() as c:
        row = c.execute("SELECT id,is_admin FROM users WHERE id=?", (user_id,)).fetchone()
        if not row:
            return False, "用户不存在"
        if int(row["is_admin"]) == 1:
            cnt = c.execute("SELECT COUNT(1) AS n FROM users WHERE is_admin=1").fetchone()
            if int(cnt["n"]) <= 1:
                return False, "至少保留一个管理员，不能删除"
        c.execute("DELETE FROM users WHERE id=?", (user_id,))
        return True, "已删除"


def is_admin(user_id: int) -> bool:
    with auth_db()._conn() as c:
        row = c.execute("SELECT is_admin FROM users WHERE id=?", (user_id,)).fetchone()
        return bool(row and int(row["is_admin"]) == 1)
