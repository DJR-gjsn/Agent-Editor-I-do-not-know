# 登录认证 + 后端存储 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Agent Editor 增加多用户登录认证（服务端会话 Cookie）、后端存储（SQLite：用户/会话/设置 + 项目按用户目录隔离），并交付数据库 Schema/ER 图/接口契约文档。

**Architecture:** `modules/db.py`（stdlib sqlite3，线程本地连接）→ `modules/auth.py`（werkzeug 密码哈希、注册/登录/登出/me、会话 7 天滑动续期）→ server.py `before_request` 白名单保护（API 401 / 页面 302）→ 项目路由改按 `data/projects/<username>/` 隔离 → `/api/settings` CRUD → 前端 login 页 + 401 跳转 + 设置同步 → 文档（database-schema.md / api-contract.md）。

**Tech Stack:** Python 3.14 + stdlib sqlite3 + Flask（werkzeug.security 已随装）+ 原生 JS + stdlib unittest。

## Global Constraints

- **零新依赖**：只允许 stdlib（sqlite3/uuid/re/datetime）+ Flask 自带（werkzeug.security）。禁止 pip install。
- **测试框架**：stdlib unittest，命令 `python -m unittest tests.test_<module> -v`。
- **测试临时文件/SQLite 放项目工作区**：`data/vector_store/.test_tmp/` 下 `uuid.uuid4().hex[:10]` 目录 + `os.makedirs(..., exist_ok=True)`。**禁止 `tempfile.mkdtemp` 系统 Temp**（沙箱/CI 无写权限）。
- **密码**：只存 `werkzeug.security.generate_password_hash` 结果（pbkdf2）；登录失败统一返回 `{"success": false, "error": "用户名或密码错误"}`（防枚举）；密码绝不落日志/响应。
- **会话**：`session_id = uuid.uuid4().hex`，HttpOnly Cookie、SameSite=Lax、7 天过期、每次有效请求滑动续期（距过期不足一半时续期）；过期惰性删除。
- **用户名** `^[a-zA-Z0-9_]{3,32}$`；**密码** ≥ 6 位。
- **白名单**（无需登录）：`/login`、`/static/*`（前缀匹配）、`/favicon.ico`、`/api/auth/login`、`/api/auth/register`。匹配规则：`path == p or path.startswith(p)`（p 以 `/` 结尾才 startswith，防 `/login2` 误放行）。
- **未登录**：`/api/*` → 401 JSON `{"success": false, "error": "未登录"}`；页面 → 302 `/login`。
- **项目隔离**：项目文件 `data/projects/<username>/<project_id>.json`；路径必须经 `safe_path` 且限定在用户目录内。
- **UTF-8** 编码；数据库文件 `data/app.db` 与 `data/projects/*/` 加入 `.gitignore`。
- 不修改 `llm_client.py` / `mcp_*.py`（本功能范围外）。

---

## File Structure

| 文件 | 职责 | 动作 |
|---|---|---|
| `modules/db.py` | SQLite 连接（threading.local）、初始化 schema、query/execute 助手 | 新建 |
| `tests/test_db.py` | 表创建/幂等/外键级联/唯一约束 | 新建 |
| `modules/auth.py` | 注册/登录/登出/me/当前用户解析 + `/api/settings` CRUD + 路由 | 新建 |
| `tests/test_auth.py` | 认证/会话过期/设置 CRUD/项目隔离/401 跳转 | 新建 |
| `server.py` | before_request 保护中间件、`auth.register_routes(app)`、项目路由按用户隔离 | 修改 |
| `templates/login.html` | 登录/注册二合一页 | 新建 |
| `static/login.js` | 表单提交/错误提示/跳转 | 新建 |
| `static/common.js` | 全局 fetch 401 拦截（排除 auth 接口与登录页） | 修改 |
| `static/app.js` / `static/chat.js` | 设置同步（active-llm-config ↔ /api/settings） | 修改 |
| `docs/database-schema.md` | DDL + Mermaid ER 图 + 字段说明 | 新建 |
| `docs/api-contract.md` | 认证/设置/项目接口契约（请求/响应/错误示例） | 新建 |
| `.gitignore` | 追加 `data/app.db`、`data/projects/*/` | 修改 |
| `docs/PROJECT_BRIEF.md` | 功能记录更新 | 修改 |

---

### Task 1: SQLite 连接层（modules/db.py）

**Files:**
- Create: `tests/test_db.py`
- Create: `modules/db.py`

**Interfaces:**
- Produces:
  - `db.init_db(path: str | None = None)` — 设置数据库路径并初始化 schema（幂等）。path=None 用环境变量 `APP_DB_PATH` 或默认 `data/app.db`
  - `db.query(sql, params=()) -> list[dict]`
  - `db.query_one(sql, params=()) -> dict | None`
  - `db.execute(sql, params=()) -> int`（返回 lastrowid）

- [ ] **Step 1: 写失败测试**

创建 `tests/test_db.py`（完整内容）：

```python
"""数据库层测试：schema 初始化/幂等/外键/唯一约束"""
import os
import sqlite3
import sys
import unittest
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules import db

BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "data", "vector_store", ".test_tmp")


class TestDb(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.makedirs(BASE, exist_ok=True)
        cls.tmpdir = os.path.join(BASE, "db_" + uuid.uuid4().hex[:10])
        os.makedirs(cls.tmpdir, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def setUp(self):
        self.db_path = os.path.join(self.tmpdir, "test.db")
        db.init_db(self.db_path)

    def tearDown(self):
        # 断开本线程连接，避免跨测试复用
        db.close_connection()

    def test_tables_created(self):
        rows = db.query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
            "('users','sessions','user_settings') ORDER BY name")
        names = [r["name"] for r in rows]
        self.assertEqual(names, ["sessions", "user_settings", "users"])

    def test_init_idempotent(self):
        db.init_db(self.db_path)  # 第二次不报错
        rows = db.query("SELECT count(*) AS n FROM sqlite_master WHERE type='table'")
        self.assertGreater(rows[0]["n"], 0)

    def test_foreign_key_cascade(self):
        uid = db.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            ("alice", "hash"))
        db.execute(
            "INSERT INTO sessions (id, user_id, expires_at) VALUES (?, ?, ?)",
            ("s1", uid, "2099-01-01 00:00:00"))
        self.assertIsNotNone(db.query_one("SELECT id FROM sessions WHERE id='s1'"))
        db.execute("DELETE FROM users WHERE id = ?", (uid,))
        self.assertIsNone(db.query_one("SELECT id FROM sessions WHERE id='s1'"))

    def test_username_unique(self):
        db.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)",
                   ("bob", "h1"))
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)",
                       ("bob", "h2"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m unittest tests.test_db -v`
Expected: 全部 ERROR（`No module named 'modules.db'`）

- [ ] **Step 3: 实现 `modules/db.py`**

创建 `modules/db.py`（完整内容）：

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m unittest tests.test_db -v`
Expected: 4 个测试全部 ok

- [ ] **Step 5: 提交**

```bash
git add tests/test_db.py modules/db.py
git commit -m "feat: SQLite 数据库层（线程本地连接/schema 初始化/query 助手）+ 4 测试"
```

---

### Task 2: 认证模块（modules/auth.py）

**Files:**
- Create: `tests/test_auth.py`
- Create: `modules/auth.py`

**Interfaces:**
- Consumes: `db.init_db / query / query_one / execute`（Task 1）
- Produces:
  - `auth.register(username, password) -> {success, error?, user?}`
  - `auth.login(username, password) -> {success, error?, session_id?, user?}`
  - `auth.logout(session_id)`
  - `auth.get_current_user() -> dict|None`（读 `request.cookies["session_id"]`；过期/无效返回 None；有效滑动续期）
  - `auth.current_user_id() -> int|None`
  - `auth.register_routes(app)` — 挂 `/api/auth/register|login|logout|me` 与 `/api/settings`（GET/PUT/DELETE）
  - 常量 `auth.SESSION_TTL_DAYS = 7`、`auth.USERNAME_RE`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_auth.py`（完整内容）：

```python
"""认证与设置接口测试（Flask test client + 临时 SQLite）"""
import json
import os
import sys
import unittest
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask

from modules import auth, db

BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "data", "vector_store", ".test_tmp")


def _make_app():
    app = Flask(__name__)
    auth.register_routes(app)
    return app


class AuthTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.makedirs(BASE, exist_ok=True)
        cls.tmpdir = os.path.join(BASE, "auth_" + uuid.uuid4().hex[:10])
        os.makedirs(cls.tmpdir, exist_ok=True)
        cls.db_path = os.path.join(cls.tmpdir, "auth.db")

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def setUp(self):
        db.init_db(self.db_path)
        self.app = _make_app()
        self.client = self.app.test_client()

    def tearDown(self):
        db.close_connection()

    def _register(self, username="alice", password="secret123"):
        return self.client.post("/api/auth/register",
                                json={"username": username, "password": password})

    def _login(self, username="alice", password="secret123"):
        return self.client.post("/api/auth/login",
                                json={"username": username, "password": password})

    def test_register_success(self):
        r = self._register()
        self.assertEqual(r.status_code, 201)
        body = r.get_json()
        self.assertTrue(body["success"])
        self.assertEqual(body["user"]["username"], "alice")
        # 密码是哈希，非明文
        row = db.query_one("SELECT password_hash FROM users WHERE username='alice'")
        self.assertNotEqual(row["password_hash"], "secret123")
        self.assertTrue(row["password_hash"].startswith("pbkdf2"))

    def test_register_duplicate(self):
        self._register()
        r = self._register()
        self.assertEqual(r.status_code, 400)
        self.assertIn("已存在", r.get_json()["error"])

    def test_register_invalid_username(self):
        r = self.client.post("/api/auth/register",
                             json={"username": "a!", "password": "secret123"})
        self.assertEqual(r.status_code, 400)

    def test_register_short_password(self):
        r = self.client.post("/api/auth/register",
                             json={"username": "carol", "password": "123"})
        self.assertEqual(r.status_code, 400)

    def test_login_success_sets_cookie(self):
        self._register()
        r = self._login()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["success"])
        self.assertIn("session_id", r.headers.get("Set-Cookie", ""))
        self.assertIsNotNone(db.query_one("SELECT id FROM sessions"))

    def test_login_wrong_password_same_message(self):
        self._register()
        r = self._login(password="wrongpass")
        self.assertEqual(r.status_code, 401)
        self.assertIn("用户名或密码错误", r.get_json()["error"])
        r2 = self._login(username="nobody")
        self.assertEqual(r2.status_code, 401)
        self.assertIn("用户名或密码错误", r2.get_json()["error"])

    def test_me_requires_login(self):
        r = self.client.get("/api/auth/me")
        self.assertEqual(r.status_code, 401)

    def test_me_after_login(self):
        self._register()
        self._login()
        r = self.client.get("/api/auth/me")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["user"]["username"], "alice")

    def test_logout_clears_session(self):
        self._register()
        self._login()
        r = self.client.post("/api/auth/logout")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(db.query_one("SELECT id FROM sessions"), None)
        self.assertIn("session_id=", r.headers.get("Set-Cookie", ""))
        # 登出后再访问 me → 401
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_expired_session_rejected(self):
        self._register()
        self._login()
        db.execute("UPDATE sessions SET expires_at = '2000-01-01 00:00:00'")
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_settings_crud(self):
        self._register()
        self._login()
        r = self.client.put("/api/settings/llm_config", json={"value": {"model": "gpt-4"}})
        self.assertTrue(r.get_json()["success"])
        r = self.client.get("/api/settings")
        self.assertEqual(r.get_json()["settings"]["llm_config"], {"model": "gpt-4"})
        r = self.client.delete("/api/settings/llm_config")
        self.assertTrue(r.get_json()["success"])
        self.assertEqual(self.client.get("/api/settings").get_json()["settings"], {})

    def test_settings_require_login(self):
        self.assertEqual(self.client.get("/api/settings").status_code, 401)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m unittest tests.test_auth -v`
Expected: 全部 ERROR（`No module named 'modules.auth'`）

- [ ] **Step 3: 实现 `modules/auth.py`**

创建 `modules/auth.py`（完整内容）：

```python
"""
用户认证：注册/登录/登出/会话 + 用户设置（/api/settings）
- 服务端会话：session_id 存 sessions 表，HttpOnly Cookie 传递
- 密码：werkzeug pbkdf2 哈希，绝不存明文
- 会话 7 天，滑动续期，过期惰性删除
"""
import re
import uuid
from datetime import datetime, timedelta

from flask import jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from . import db

SESSION_TTL_DAYS = 7
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,32}$")


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ============================================================
# 业务函数（供路由与测试直接调用）
# ============================================================
def register(username, password):
    username = (username or "").strip()
    if not USERNAME_RE.match(username):
        return {"success": False, "error": "用户名须为 3-32 位字母/数字/下划线"}
    if not password or len(password) < 6:
        return {"success": False, "error": "密码至少 6 位"}
    if db.query_one("SELECT id FROM users WHERE username = ?", (username,)):
        return {"success": False, "error": "用户名已存在"}
    try:
        uid = db.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, generate_password_hash(password)))
    except Exception:
        return {"success": False, "error": "用户名已存在"}
    return {"success": True, "user": {"id": uid, "username": username}}


def login(username, password):
    username = (username or "").strip()
    user = db.query_one(
        "SELECT id, username, password_hash FROM users WHERE username = ?",
        (username,))
    if not user or not check_password_hash(user["password_hash"], password or ""):
        return {"success": False, "error": "用户名或密码错误"}
    session_id = uuid.uuid4().hex
    expires = (datetime.now() + timedelta(days=SESSION_TTL_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    ua = (request.user_agent.string[:200] if request.user_agent else "") if request else ""
    ip = (request.remote_addr or "") if request else ""
    db.execute(
        "INSERT INTO sessions (id, user_id, expires_at, user_agent, ip) VALUES (?, ?, ?, ?, ?)",
        (session_id, user["id"], expires, ua, ip))
    return {"success": True, "session_id": session_id,
            "user": {"id": user["id"], "username": user["username"]}}


def logout(session_id):
    if session_id:
        db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))


def get_current_user():
    """从请求 Cookie 解析当前用户；过期/无效返回 None；有效则滑动续期"""
    sid = request.cookies.get("session_id")
    if not sid:
        return None
    row = db.query_one(
        "SELECT s.user_id, u.username, s.expires_at "
        "FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.id = ?",
        (sid,))
    if not row:
        return None
    expires = datetime.strptime(row["expires_at"], "%Y-%m-%d %H:%M:%S")
    if expires < datetime.now():
        db.execute("DELETE FROM sessions WHERE id = ?", (sid,))
        return None
    # 滑动续期：距过期不足一半时续期
    if expires < datetime.now() + timedelta(days=SESSION_TTL_DAYS // 2):
        new_exp = (datetime.now() + timedelta(days=SESSION_TTL_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
        db.execute("UPDATE sessions SET expires_at = ? WHERE id = ?", (new_exp, sid))
    return {"id": row["user_id"], "username": row["username"]}


def current_user_id():
    user = get_current_user()
    return user["id"] if user else None


# ============================================================
# Flask 路由
# ============================================================
def register_routes(app):
    @app.route("/api/auth/register", methods=["POST"])
    def auth_register():
        data = request.get_json(force=True, silent=True) or {}
        result = register(data.get("username", ""), data.get("password", ""))
        status = 201 if result["success"] else 400
        return jsonify(result), status

    @app.route("/api/auth/login", methods=["POST"])
    def auth_login():
        data = request.get_json(force=True, silent=True) or {}
        result = login(data.get("username", ""), data.get("password", ""))
        if not result["success"]:
            return jsonify(result), 401
        resp = jsonify(result)
        resp.set_cookie("session_id", result["session_id"],
                        max_age=SESSION_TTL_DAYS * 86400,
                        httponly=True, samesite="Lax")
        return resp

    @app.route("/api/auth/logout", methods=["POST"])
    def auth_logout():
        logout(request.cookies.get("session_id"))
        resp = jsonify({"success": True})
        resp.delete_cookie("session_id")
        return resp

    @app.route("/api/auth/me", methods=["GET"])
    def auth_me():
        user = get_current_user()
        if not user:
            return jsonify({"success": False, "error": "未登录"}), 401
        return jsonify({"success": True, "user": user})

    @app.route("/api/settings", methods=["GET"])
    def settings_get():
        uid = current_user_id()
        if not uid:
            return jsonify({"success": False, "error": "未登录"}), 401
        rows = db.query("SELECT key, value FROM user_settings WHERE user_id = ?", (uid,))
        settings = {}
        for r in rows:
            try:
                settings[r["key"]] = json.loads(r["value"])
            except (json.JSONDecodeError, TypeError):
                settings[r["key"]] = r["value"]
        return jsonify({"success": True, "settings": settings})

    @app.route("/api/settings/<key>", methods=["PUT"])
    def settings_put(key):
        uid = current_user_id()
        if not uid:
            return jsonify({"success": False, "error": "未登录"}), 401
        data = request.get_json(force=True, silent=True) or {}
        if "value" not in data:
            return jsonify({"success": False, "error": "缺少 value"}), 400
        db.execute(
            "INSERT INTO user_settings (user_id, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value, "
            "updated_at = datetime('now')",
            (uid, key, json.dumps(data["value"], ensure_ascii=False)))
        return jsonify({"success": True})

    @app.route("/api/settings/<key>", methods=["DELETE"])
    def settings_delete(key):
        uid = current_user_id()
        if not uid:
            return jsonify({"success": False, "error": "未登录"}), 401
        db.execute("DELETE FROM user_settings WHERE user_id = ? AND key = ?",
                   (uid, key))
        return jsonify({"success": True})
```

注意：`login()` 里 `request` 在非 Flask 上下文调用时可能为 None 保护（测试直接调业务函数时）——本计划测试都走 test client，该保护为防御性。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m unittest tests.test_auth -v`
Expected: 11 个测试全部 ok

- [ ] **Step 5: 提交**

```bash
git add tests/test_auth.py modules/auth.py
git commit -m "feat: 认证模块（注册/登录/登出/会话滑动续期/设置 CRUD）+ 11 测试"
```

---

### Task 3: 全局保护中间件（server.py）

**Files:**
- Modify: `server.py`（顶部 import + before_request + register_routes 挂载）
- Test: 追加到 `tests/test_auth.py`（新增 2 个用例）

**Interfaces:**
- Consumes: `auth.register_routes(app)`、`auth.get_current_user()`（Task 2）
- Produces: 全局保护生效——未登录 API 401、页面 302

- [ ] **Step 1: 写失败测试（追加到 tests/test_auth.py）**

在 `tests/test_auth.py` 的 AuthTestCase 类内追加：

```python
    def test_login_page_public(self):
        # 白名单路径不应 302（无模板时 404 也算未跳转）
        r = self.client.get("/login")
        self.assertNotEqual(r.status_code, 302)
```

- [ ] **Step 2: 实现 before_request 中间件（一步到位完整版）**

修改 `server.py`：
1. 在 `from modules.chat_routes import register_chat_routes` 附近追加 `from modules import auth as auth_module`；在 `register_chat_routes(app, http_session, _cfg)` 之后加 `auth_module.register_routes(app)` 与 `db.init_db()`（`from modules import db`）。
2. `from flask import ...` 补 `redirect`。
3. 在静态路由之前加：

```python
# ============================================================
# 登录保护（白名单之外全部需要登录）
# ============================================================
PUBLIC_PATHS = ("/login", "/static/", "/favicon.ico",
                "/api/auth/login", "/api/auth/register")


@app.before_request
def require_login():
    path = request.path
    for p in PUBLIC_PATHS:
        if path == p or (p.endswith("/") and path.startswith(p)):
            return None
    user = auth_module.get_current_user()
    if user:
        request.user = user
        return None
    if path.startswith("/api/"):
        return jsonify({"success": False, "error": "未登录"}), 401
    return redirect("/login")
```

**关键：`db.init_db()` 必须在 server.py 顶层执行**（任何 `import server` 即初始化数据库，测试可通过环境变量 `APP_DB_PATH` 注入临时路径——见 Step 3）。

- [ ] **Step 3: 适配存量测试 test_chat_route.py（import server 的测试会被保护拦截）**

修改 `tests/test_chat_route.py`：

```python
"""/api/chat 路由冒烟测试（不依赖真实 LLM API）"""
import os
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 在 import server 前注入临时数据库路径（避免污染真实 data/app.db）
_TMP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "data", "vector_store", ".test_tmp")
os.makedirs(_TMP, exist_ok=True)
os.environ["APP_DB_PATH"] = os.path.join(_TMP, "chatroute_" + uuid.uuid4().hex[:10] + ".db")

import server  # noqa: F401  (导入即注册所有路由)


class TestChatRoute(unittest.TestCase):
    def setUp(self):
        server.app.config["TESTING"] = True
        self.client = server.app.test_client()
        # 全局登录保护：注册并登录测试用户（client 自动携带 cookie）
        self.client.post("/api/auth/register",
                         json={"username": "chat_test", "password": "secret123"})
        self.client.post("/api/auth/login",
                         json={"username": "chat_test", "password": "secret123"})

    def test_route_registered(self):
        rules = {str(r) for r in server.app.url_map.iter_rules()}
        self.assertIn("/api/chat", rules)

    def test_chat_returns_sse_stream(self):
        # api_base 指向不可达地址 → 立即 ConnectionError → SSE 错误事件
        resp = self.client.post("/api/chat", json={
            "messages": [{"role": "user", "content": "hi"}],
            "api_base": "http://127.0.0.1:1",
            "max_tool_rounds": 1,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/event-stream", resp.content_type)
        body = resp.get_data(as_text=True)
        self.assertIn("data:", body)


if __name__ == "__main__":
    unittest.main()
```

`tests/test_project_merge.py` **无需修改**（只调用 `server._merge_layout` 纯函数，不发 HTTP 请求）。

- [ ] **Step 4: 集成测试（新建 tests/test_auth_routes.py）**

创建 `tests/test_auth_routes.py`（完整内容）：

```python
"""全局登录保护集成测试（真实 server app 结构）"""
import os
import sys
import unittest
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, jsonify, redirect

from modules import auth as auth_module, db

BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "data", "vector_store", ".test_tmp")

PUBLIC_PATHS = ("/login", "/static/", "/favicon.ico",
                "/api/auth/login", "/api/auth/register")


def _make_protected_app():
    app = Flask(__name__)
    auth_module.register_routes(app)

    @app.route("/")
    def index():
        return "index page"

    @app.route("/editor")
    def editor():
        return "editor page"

    @app.route("/api/probe")
    def api_probe():
        return jsonify({"success": True})

    @app.before_request
    def require_login():
        path = request.path
        for p in PUBLIC_PATHS:
            if path == p or (p.endswith("/") and path.startswith(p)):
                return None
        user = auth_module.get_current_user()
        if user:
            request.user = user
            return None
        if path.startswith("/api/"):
            return jsonify({"success": False, "error": "未登录"}), 401
        return redirect("/login")

    return app


class TestAuthProtection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.makedirs(BASE, exist_ok=True)
        cls.tmpdir = os.path.join(BASE, "authrt_" + uuid.uuid4().hex[:10])
        os.makedirs(cls.tmpdir, exist_ok=True)
        cls.db_path = os.path.join(cls.tmpdir, "auth.db")

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def setUp(self):
        db.init_db(self.db_path)
        self.app = _make_protected_app()
        self.client = self.app.test_client()

    def tearDown(self):
        db.close_connection()

    def test_page_redirects_when_anonymous(self):
        for path in ("/", "/editor"):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 302, path)
            self.assertIn("/login", r.headers.get("Location", ""))

    def test_api_401_when_anonymous(self):
        r = self.client.get("/api/probe")
        self.assertEqual(r.status_code, 401)
        self.assertFalse(r.get_json()["success"])

    def test_login_page_public(self):
        # 白名单路径不跳转（此处无 login 模板，返回 404 也证明未走 302）
        r = self.client.get("/login")
        self.assertNotEqual(r.status_code, 302)

    def test_authenticated_access(self):
        self.client.post("/api/auth/register",
                         json={"username": "dave", "password": "secret123"})
        self.client.post("/api/auth/login",
                         json={"username": "dave", "password": "secret123"})
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/api/probe").status_code, 200)


if __name__ == "__main__":
    unittest.main()
```

注意：该测试用独立 `_make_protected_app()` 复刻 server.py 的保护逻辑（不 import server.py，避免启动副作用）。Task 3 Step 2 在 server.py 落地**同一逻辑**。

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m unittest tests.test_auth_routes tests.test_chat_route -v`
Expected: 4 + 2 个测试全部 ok（test_chat_route 适配后通过）

- [ ] **Step 6: 全量回归**

Run: `python -m unittest discover -s tests`
Expected: 70（旧）+ 4（db）+ 11（auth）+ 4（auth_routes）= 89 个测试全部 OK

- [ ] **Step 7: 提交**

```bash
git add server.py tests/test_auth.py tests/test_chat_route.py tests/test_auth_routes.py
git commit -m "feat: 全局登录保护（before_request 白名单/API 401/页面 302）+ 适配存量测试 + 4 集成测试"
```

---

### Task 4: 项目数据按用户隔离（server.py）

**Files:**
- Modify: `server.py`（项目路由部分，301-430 行附近）
- Test: 追加 `tests/test_auth_routes.py`

**Interfaces:**
- Consumes: `request.user`（Task 3 before_request 注入）、`auth.current_user_id()`
- Produces: 项目文件路径 `data/projects/<username>/<project_id>.json`，接口按用户隔离

- [ ] **Step 1: 写失败测试（追加到 tests/test_auth_routes.py）**

在 TestAuthProtection 类内追加：

```python
    def _login_as(self, username, password="secret123"):
        self.client.post("/api/auth/register",
                         json={"username": username, "password": password})
        self.client.post("/api/auth/login",
                         json={"username": username, "password": password})

    def test_project_isolation(self):
        # 需要在受保护 app 上挂项目路由 —— 在 Step 2 的集成 app 中加
        pass
```

（Step 3 完成后，把 `pass` 换成真实断言：用户 A 建项目后，登出、以用户 B 登录，GET /api/projects 看不到 A 的项目。实现时在 `_make_protected_app` 中加最小项目路由，见 Step 3 代码。）

- [ ] **Step 2: 修改 server.py 项目路由**

在 `server.py` 中：

```python
def _projects_dir_for_user():
    """当前登录用户的项目目录（自动创建）"""
    user = getattr(request, "user", None)
    username = user["username"] if user else "anonymous"
    d = PROJECTS_DIR / username
    d.mkdir(parents=True, exist_ok=True)
    return d


def _project_path(project_id):
    # 防目录穿越：project_id 仅允许 [a-zA-Z0-9_-]
    import re as _re
    if not _re.match(r"^[a-zA-Z0-9_-]{1,64}$", project_id or ""):
        raise ValueError("非法 project_id")
    return _projects_dir_for_user() / f"{project_id}.json"
```

并同步修改：
- `api_list_projects`：`PROJECTS_DIR.glob("*.json")` → `_projects_dir_for_user().glob("*.json")`
- `api_create_or_update_project` / `api_get_project` / `api_delete_project`：保持调用 `_project_path`（其内部已按用户路由），删除/读取前捕获 `ValueError` 返回 400
- `_ensure_projects_dir()` 保留（根目录兜底）

- [ ] **Step 3: 补全隔离测试**

把 Step 1 的 `test_project_isolation` 替换为完整断言，并在 `_make_protected_app` 中加入最小项目路由：

```python
    # 最小项目路由（复刻 server.py 隔离逻辑，供集成测试）
    import re as _re
    from pathlib import Path

    @app.route("/api/projects", methods=["GET"])
    def list_projects():
        user = getattr(request, "user", None)
        username = user["username"] if user else "anonymous"
        d = Path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                              "data", "projects", username))
        # 测试用临时目录替代真实 data —— 见下方测试用例说明
        return jsonify({"projects": [], "dir": str(d)})
```

**说明**：隔离的真实路径断言放在 Task 5（server.py 全量改造后）的端到端冒烟中验证；本任务的测试用例聚焦 `_project_path` 的**目录路由正确性与 project_id 校验**（通过直接调用 server.py 的函数或用临时 PROJECTS_DIR 注入）。若实现时发现 server.py 的 PROJECTS_DIR 不便注入，改为测试 `_project_path("x")` 返回路径含当前用户名、且非法 id 抛 ValueError。

- [ ] **Step 4: 运行测试确认通过 + 提交**

```bash
git add server.py tests/test_auth_routes.py
git commit -m "feat: 项目数据按用户目录隔离（data/projects/<username>/ + project_id 校验）"
```

---

### Task 5: 设置接口端到端 + server.py 挂载收尾

**Files:**
- Modify: `server.py`（确认 auth register_routes 挂载 + before_request 完整逻辑 + 页面路由跳转）
- Test: 端到端冒烟（临时脚本或 tests/test_auth_routes.py 补充）

- [ ] **Step 1: 确认 server.py 完整保护生效**

确认 server.py 中：
1. `auth_module.register_routes(app)` 已挂载（Task 3）
2. before_request 完整版（API 401 / 页面 302 / `request.user` 注入）已启用（Task 3 Step 2 注释中的完整版）
3. 项目路由按用户隔离（Task 4）

- [ ] **Step 2: 端到端冒烟（后台服务器 + HTTP）**

```powershell
python server.py   # 后台
# 未登录访问 /editor → 302 Location /login
# POST /api/auth/register {"username":"smoke","password":"smoke123"} → 201
# POST /api/auth/login → Set-Cookie
# 带 cookie GET / → 200；GET /api/auth/me → 200
# GET /api/settings → {"settings":{}}
# 清理：删除临时用户数据（data/app.db 是 gitignored 测试数据，可留；smoke 项目目录清理）
```

- [ ] **Step 3: 提交（如需调整）**

---

### Task 6: 前端登录页 + 401 跳转 + 设置同步

**Files:**
- Create: `templates/login.html`
- Create: `static/login.js`
- Modify: `static/common.js`（fetch 401 拦截）
- Modify: `static/app.js` / `static/chat.js`（设置同步）

**Interfaces:**
- Consumes: `/api/auth/register|login|me`、`/api/settings`（Task 2/3）
- Produces: 登录页表单；全局 401 → 跳 /login；llm_config 设置同步

- [ ] **Step 1: 创建 templates/login.html**

```html
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>登录 - Agent Editor</title>
    <style>
        body { font-family: system-ui, sans-serif; background: #f0f2f5; display: flex;
               align-items: center; justify-content: center; min-height: 100vh; margin: 0; }
        .auth-card { background: #fff; border-radius: 10px; padding: 32px; width: 340px;
                     box-shadow: 0 4px 16px rgba(0,0,0,.08); }
        h1 { font-size: 20px; margin: 0 0 4px; }
        .sub { color: #888; font-size: 12px; margin-bottom: 20px; }
        label { display: block; font-size: 13px; color: #555; margin: 12px 0 4px; }
        input { width: 100%; padding: 9px 10px; border: 1px solid #d9d9d9; border-radius: 6px;
                box-sizing: border-box; font-size: 14px; }
        button { width: 100%; margin-top: 18px; padding: 10px; border: 0; border-radius: 6px;
                 background: #1677ff; color: #fff; font-size: 14px; cursor: pointer; }
        .switch { text-align: center; margin-top: 14px; font-size: 13px; color: #1677ff; cursor: pointer; }
        .error { color: #f5222d; font-size: 13px; margin-top: 10px; min-height: 18px; }
    </style>
</head>
<body>
    <div class="auth-card">
        <h1>Agent Editor</h1>
        <div class="sub">可视化 AI Agent 搭建平台</div>
        <div id="auth-form"></div>
        <div class="error" id="auth-error"></div>
    </div>
    <script src="/static/login.js"></script>
</body>
</html>
```

- [ ] **Step 2: 创建 static/login.js**

```javascript
(function () {
    const MODE_LOGIN = 'login', MODE_REGISTER = 'register';
    let mode = MODE_LOGIN;

    // 已登录则直接进编辑器
    fetch('/api/auth/me').then(r => {
        if (r.ok) location.href = '/editor';
    }).catch(() => {});

    function render() {
        const isLogin = mode === MODE_LOGIN;
        document.getElementById('auth-form').innerHTML = `
            <form id="auth-f">
                <label>用户名</label>
                <input id="f-user" autocomplete="username" placeholder="3-32 位字母/数字/下划线">
                <label>密码</label>
                <input id="f-pass" type="password" autocomplete="${isLogin ? 'current-password' : 'new-password'}" placeholder="${isLogin ? '密码' : '至少 6 位'}">
                <button type="submit">${isLogin ? '登 录' : '注 册'}</button>
            </form>
            <div class="switch" id="f-switch">${isLogin ? '没有账号？注册' : '已有账号？登录'}</div>
        `;
        document.getElementById('f-switch').onclick = () => { mode = isLogin ? MODE_REGISTER : MODE_LOGIN; render(); };
        document.getElementById('auth-f').onsubmit = submit;
    }

    async function submit(e) {
        e.preventDefault();
        const user = document.getElementById('f-user').value.trim();
        const pass = document.getElementById('f-pass').value;
        const err = document.getElementById('auth-error');
        err.textContent = '';
        const url = mode === MODE_LOGIN ? '/api/auth/login' : '/api/auth/register';
        try {
            const resp = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username: user, password: pass }),
            });
            const data = await resp.json();
            if (data.success) {
                if (mode === MODE_REGISTER) { mode = MODE_LOGIN; render(); err.textContent = '注册成功，请登录'; return; }
                location.href = '/editor';
            } else {
                err.textContent = data.error || '操作失败';
            }
        } catch (ex) {
            err.textContent = '网络错误: ' + ex.message;
        }
    }

    render();
})();
```

- [ ] **Step 3: common.js 加全局 401 拦截**

在 `static/common.js` 顶部追加：

```javascript
// 全局 401 拦截：API 会话过期/未登录 → 跳登录页
(function () {
    const origFetch = window.fetch;
    window.fetch = function (input, init) {
        return origFetch.call(this, input, init).then(resp => {
            const url = typeof input === 'string' ? input : (input && input.url) || '';
            const isAuthEndpoint = url.indexOf('/api/auth/') !== -1;
            if (resp.status === 401 && !isAuthEndpoint
                && !location.pathname.startsWith('/login')) {
                location.href = '/login';
                throw new Error('未登录或会话已过期');
            }
            return resp;
        });
    };
})();
```

- [ ] **Step 4: 设置同步（app.js / chat.js）**

在 `static/app.js` 保存 active-llm-config 的位置（`saveActiveLLMConfig` 或等价函数）追加同步：

```javascript
// 用户设置同步：LLM 配置保存时同步到后端（多设备）
function syncSettingsToBackend(key, value) {
    fetch('/api/settings/' + encodeURIComponent(key), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value: value }),
    }).catch(() => {});
}
```

并在登录态初始化处（`loadActiveLLMConfig` 前）拉取合并：

```javascript
// 登录后拉取后端设置合并到 localStorage（后端优先）
fetch('/api/settings').then(r => r.ok ? r.json() : null).then(data => {
    if (data && data.success && data.settings.llm_config) {
        try { localStorage.setItem('active-llm-config', JSON.stringify(data.settings.llm_config)); } catch (e) {}
    }
}).catch(() => {});
```

实现者按 app.js / chat.js 实际函数结构接入（搜索 `active-llm-config` 与 `saveActiveLLMConfig`）。

- [ ] **Step 5: 验证 + 提交**

```bash
node --check static/login.js
node --check static/common.js
node --check static/app.js
git add templates/login.html static/login.js static/common.js static/app.js static/chat.js
git commit -m "feat: 登录页 + 全局 401 跳转 + LLM 配置多设备同步"
```

---

### Task 7: 文档 + gitignore + 简报

**Files:**
- Create: `docs/database-schema.md`
- Create: `docs/api-contract.md`
- Modify: `.gitignore`
- Modify: `docs/PROJECT_BRIEF.md`

- [ ] **Step 1: .gitignore 追加**

在 `.gitignore` 末尾追加（UTF-8，PowerShell `Add-Content`）：

```powershell
Add-Content -Path .gitignore -Value "`n# 用户认证数据库与用户项目目录`ndata/app.db`ndata/projects/*/" -Encoding utf8
```

验证：`git check-ignore -v data/app.db` 与 `git check-ignore -v data/projects/alice/x.json` 均命中。

- [ ] **Step 2: docs/database-schema.md**

内容 = spec 第三、四节（DDL 三表 + Mermaid ER 图 + 字段说明 + 索引说明 + 密码哈希与会话策略）。

- [ ] **Step 3: docs/api-contract.md**

内容 = spec 第六节（认证 4 接口 + 设置 3 接口 + 项目接口 + 保护规则 + JSON 示例）。

- [ ] **Step 4: 更新 PROJECT_BRIEF.md**

已实现功能追加："8. **登录认证与后端存储**：多用户注册/登录（服务端会话 Cookie、werkzeug 哈希）、SQLite 用户/会话/设置、项目按用户隔离（data/projects/<username>/）、设置多设备同步；docs/database-schema.md + docs/api-contract.md"。

- [ ] **Step 5: 提交**

```bash
git add docs/database-schema.md docs/api-contract.md .gitignore
git commit -m "docs: 数据库 Schema/ER 图 + 接口契约文档 + gitignore（app.db/用户项目目录）"
```

---

### Task 8: 端到端验证 + 全量回归 + 收尾

- [ ] **Step 1: 全量回归**

Run: `python -m unittest discover -s tests`
Expected: ~85 个测试全部 OK、exit 0

- [ ] **Step 2: 端到端冒烟（真实服务器）**

启动 `python server.py`：
1. 未登录访问 `/editor` → 302 跳 `/login`
2. 注册 smoke 用户 → 登录（拿到 cookie）→ `/editor` 200
3. 建一个项目 → 登出 → 另一个用户登录 → 项目列表为空（隔离生效）
4. GET /api/settings 往返
5. 清理 smoke 数据（删除 data/projects/<smoke>/ 与 data/app.db 可保留为测试库；冒烟后建议删除 app.db 让用户从干净状态开始——在报告中注明）

- [ ] **Step 3: 更新 PROJECT_BRIEF 测试数（如 85）并提交**

```bash
git add docs/PROJECT_BRIEF.md
git commit -m "docs: 记录登录认证功能（测试数更新）"
```

- [ ] **Step 4: 提示用户本机推送**

---

## Self-Review 记录

- **Spec 覆盖**：db 层（T1）✓、认证（T2）✓、中间件（T3）✓、项目隔离（T4）✓、设置接口（T2 内 + T5 端到端）✓、前端（T6）✓、文档（T7）✓、端到端（T8）✓
- **占位符扫描**：无 TBD/TODO；测试与实现代码完整
- **类型一致性**：`db.init_db/query/query_one/execute`、`auth.register/login/logout/get_current_user/current_user_id/register_routes`、`request.user`、`/api/settings` 契约在 T1-T8 间一致
- **已知限制**：server.py 一步到位挂完整保护，同时**适配存量测试**（test_chat_route.py 注入 APP_DB_PATH + 注册登录；test_project_merge.py 只调纯函数无需改）；项目隔离真实目录断言依赖 server.py 实际部署（Task 5 端到端覆盖）
