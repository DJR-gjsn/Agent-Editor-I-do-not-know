"""
SQLite 数据库层（stdlib sqlite3）
- 线程本地连接（sqlite3 连接不可跨线程共享）
- init_db(path) 设置路径并初始化 schema（幂等）
- query / query_one / execute 助手
"""
import os
import sqlite3
import threading

_lock = threading.Lock()
_local = threading.local()
_db_path = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    id         TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL,
    user_agent TEXT,
    ip         TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS user_settings (
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key        TEXT NOT NULL,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, key)
);
"""

_DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "app.db")


def init_db(path=None):
    """设置数据库路径并初始化 schema（幂等）。"""
    global _db_path
    with _lock:
        _db_path = (path or os.environ.get("APP_DB_PATH") or _DEFAULT_DB_PATH)
    close_connection()
    _conn().executescript(_SCHEMA)


def _conn():
    conn = getattr(_local, "conn", None)
    if conn is None:
        os.makedirs(os.path.dirname(_db_path), exist_ok=True)
        conn = sqlite3.connect(_db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        _local.conn = conn
    return conn


def close_connection():
    """关闭当前线程的连接（测试隔离用）"""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except sqlite3.Error:
            pass
        _local.conn = None


def query(sql, params=()):
    with _conn() as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]


def query_one(sql, params=()):
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql, params=()):
    with _conn() as c:
        cur = c.execute(sql, params)
        return cur.lastrowid
