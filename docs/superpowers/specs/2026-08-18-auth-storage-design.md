# 登录认证 + 后端存储 设计文档

> 日期：2026-08-18 · 状态：已获用户批准（分两节确认）
> 目标：为 Agent Editor 增加多用户登录认证、后端存储（SQLite + 用户隔离），并交付数据库 Schema/ER 图/接口契约文档

## 一、背景与目标

Agent Editor 目前**无认证**：任何人访问 `http://localhost:5000` 即可使用全部功能；项目数据存 `data/projects/*.json`（本机文件）；用户配置（API key、主题等）存浏览器 localStorage。需求：

1. **多用户登录**：注册/登录/登出，未登录无法使用
2. **后端存储**：用户账号、会话、用户设置持久化到 SQLite；项目数据按用户隔离
3. **文档交付**：数据库 Schema（DDL）+ ER 图（Mermaid）+ 接口契约文档

### 用户已确认的决策

| 决策点 | 选择 |
|---|---|
| 用户模型 | **多用户 + 项目隔离** |
| 认证机制 | **服务端会话 Cookie**（HttpOnly，sessions 表持久化） |
| 存储范围 | 认证 + 用户设置进 SQLite；**项目文件按用户分目录隔离** |
| 保护范围 | **全部保护**（除注册/登录/静态资源，页面 302 跳登录，API 401） |
| 文档形式 | **Markdown + Mermaid**（DDL + ER 图 + 接口契约）放 docs/ |

### 非目标（YAGNI）

- ❌ 不做注册限速/验证码/邮箱验证
- ❌ 不做 JWT / API Token（将来需要再加）
- ❌ 不做角色权限系统（全部登录用户同级）
- ❌ 项目数据不迁入数据库（保持 JSON 文件，按用户目录隔离）
- ❌ 不做密码找回

## 二、架构总览

```
┌─ 前端 ─────────────────────────────────┐
│ login.html（登录/注册二合一页）           │
│ 现有页面 + 401 自动跳登录 + 设置同步      │
└──────────────┬─────────────────────────┘
               │ Cookie (session_id, HttpOnly, SameSite=Lax)
┌──────────────▼─────────────────────────┐
│ server.py before_request 全局校验        │
│  白名单: /login /static/* /favicon.ico  │
│         /api/auth/login /api/auth/register
│  modules/auth.py    注册/登录/登出/me    │
│  modules/db.py      SQLite 连接与初始化  │
│  data/app.db（gitignore 排除）          │
│  项目文件: data/projects/<username>/    │
└────────────────────────────────────────┘
```

### 技术选型（零新依赖）

| 项 | 方案 |
|---|---|
| 数据库 | **stdlib `sqlite3`**，文件 `data/app.db`（gitignore 排除） |
| 密码哈希 | **werkzeug.security**（Flask 自带依赖）：`generate_password_hash`（pbkdf2）+ `check_password_hash` |
| 会话 | 自定义 `session_id`（uuid hex）存 sessions 表 + HttpOnly Cookie（`session_id=...`），服务端校验/过期 |
| 会话有效期 | 7 天；每次有效请求滑动续期；过期惰性清理 |
| 登录页 | 独立 `templates/login.html`；已登录访问自动跳 /editor |

## 三、数据库 Schema

文件：`data/app.db`（`modules/db.py` 启动时 `CREATE TABLE IF NOT EXISTS` 初始化）

```sql
-- 用户表
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,              -- 登录名，唯一
    password_hash TEXT NOT NULL,                     -- werkzeug pbkdf2 哈希，绝不存明文
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 会话表（服务端会话）
CREATE TABLE IF NOT EXISTS sessions (
    id         TEXT PRIMARY KEY,                     -- session_id（uuid hex）
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL,                        -- 过期时间（7 天后）
    user_agent TEXT,
    ip         TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

-- 用户设置表（key-value，value 为 JSON 字符串）
CREATE TABLE IF NOT EXISTS user_settings (
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key        TEXT NOT NULL,                        -- 如 'llm_config'、'ui_prefs'
    value      TEXT NOT NULL,                        -- JSON 字符串
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, key)
);
```

## 四、ER 图（Mermaid）

```mermaid
erDiagram
    USERS ||--o{ SESSIONS : "登录会话"
    USERS ||--o{ USER_SETTINGS : "配置"

    USERS {
        int id PK
        string username UK "唯一登录名"
        string password_hash "pbkdf2 哈希"
        string created_at
    }
    SESSIONS {
        string id PK "session_id uuid"
        int user_id FK "级联删除"
        string created_at
        string expires_at "7 天过期"
        string user_agent
        string ip
    }
    USER_SETTINGS {
        int user_id PK_FK "级联删除"
        string key PK "如 llm_config"
        string value "JSON 字符串"
        string updated_at
    }
```

## 五、项目数据隔离

- 项目文件路径：`data/projects/<username>/xxx.json`（当前为 `data/projects/xxx.json`）
- `/api/projects` 系列接口按当前登录用户路由（`safe_path` 校验防目录穿越，且路径强制以 `data/projects/<username>/` 为根）
- 不同用户看不到彼此项目
- `.gitignore` 追加：`data/app.db`；`data/projects/*/`（用户名目录整个排除；现有 `data/projects/*.json` 规则保留兼容旧文件）

## 六、接口契约（写入 docs/api-contract.md）

### 认证接口

| 接口 | 方法 | 请求 | 成功响应 | 失败 |
|---|---|---|---|---|
| `/api/auth/register` | POST | `{username, password}` | `201 {success:true, user:{id,username}}` | 400 用户名已存在/格式非法 |
| `/api/auth/login` | POST | `{username, password}` | `200 {success:true, user:{id,username}}` + `Set-Cookie: session_id=...` | 401 用户名或密码错误 |
| `/api/auth/logout` | POST | — | `200 {success:true}` + 清 Cookie | — |
| `/api/auth/me` | GET | — | `200 {success:true, user:{id,username}}` | 401 未登录 |

### 用户设置接口

| 接口 | 方法 | 请求 | 成功响应 | 失败 |
|---|---|---|---|---|
| `GET /api/settings` | GET | — | `200 {success:true, settings:{key:json_value,...}}` | 401 |
| `PUT /api/settings/<key>` | PUT | `{value: <任意 JSON>}` | `200 {success:true}` | 400 无 key / 401 |
| `DELETE /api/settings/<key>` | DELETE | — | `200 {success:true}` | 401 |

### 规则

- Cookie：`session_id`（HttpOnly、SameSite=Lax、7 天过期、每次请求滑动续期）
- 密码错误/用户不存在统一返回 401 "用户名或密码错误"（防枚举）
- 用户名 `^[a-zA-Z0-9_]{3,32}$`；密码至少 6 位
- 所有被保护接口未登录：API 返回 401 JSON `{success:false, error:"未登录"}`
- 受保护页面未登录：302 重定向 `/login`

## 七、保护中间件（server.py before_request）

```python
# 白名单（无需登录）
PUBLIC_PATHS = {
    "/login", "/static/", "/favicon.ico",
    "/api/auth/login", "/api/auth/register",
}

@app.before_request
def require_login():
    path = request.path
    if any(path == p or path.startswith(p.rstrip('/') + '/') for p in PUBLIC_PATHS):
        return None
    user = auth.get_current_user()
    if user:
        request.user = user
        return None
    if path.startswith("/api/"):
        return jsonify({"success": False, "error": "未登录"}), 401
    return redirect("/login")
```

注意：白名单匹配用 `path == p` 或 `path.startswith(p)`（对 `/static/` 等前缀），避免 `/login2` 误放行。

## 八、前端改动

| 文件 | 改动 |
|---|---|
| `templates/login.html` 新建 | 登录/注册二合一表单；已登录访问自动跳 /editor |
| `static/login.js` 新建 | 表单提交、错误提示、登录后跳转 |
| `static/common.js` | fetch 包装：响应 401 → 跳 /login；登录态初始化检查 |
| `static/app.js` / `static/chat.js` | 用户设置同步：localStorage `active-llm-config` 保存时同步 `PUT /api/settings/llm_config`；登录后 `GET /api/settings` 拉取合并（多设备同步） |

## 九、错误处理与安全

- 会话过期/无效：API 401 → 前端跳登录页；sessions 表惰性清理过期行
- 密码绝不落日志/前端；哈希 werkzeug pbkdf2
- CSRF：SameSite=Lax + 仅 JSON POST（非表单编码），风险可控；若后续加表单类接口再补 token
- `data/app.db` gitignore；`data/projects/<username>/` gitignore
- 目录穿越防护：项目路径用 `safe_path` 且强制限定在用户目录内

## 十、测试（新增 tests/test_auth.py，全量 70 → ~85）

| 用例 | 断言 |
|---|---|
| 注册成功 | 201 + users 表有哈希记录（非明文） |
| 重复用户名 | 400 |
| 用户名/密码格式非法 | 400 |
| 登录成功 | 200 + Set-Cookie + sessions 表有记录 |
| 密码错误/用户不存在 | 401（同一消息） |
| me 未登录 | 401 |
| 登出 | 清 cookie + session 删除 |
| 会话过期 | 篡改 expires_at → 401 |
| 设置 CRUD | PUT/GET/DELETE 往返 |
| 项目隔离 | 用户 A 建项目，用户 B 列表看不到 |
| 未登录访问页面 | 302 → /login |
| 未登录访问 API | 401 JSON |

测试用临时 SQLite 文件（`data/vector_store/.test_tmp/` 下 uuid 目录，遵循既有模式），不触碰真实 `data/app.db`；测试需要能注入 db 路径（`db.init_db(path)`）。

## 十一、实现顺序（供 writing-plans 参考）

1. `modules/db.py`（连接/初始化/路径注入）+ `tests/test_db.py`
2. `modules/auth.py`（注册/登录/登出/me/当前用户解析）+ `tests/test_auth.py`
3. server.py before_request 保护中间件 + 页面跳转 + 白名单
4. 项目隔离改造（`data/projects/<username>/` + `/api/projects` 按用户路由）+ 隔离测试
5. 设置接口（`/api/settings` CRUD）+ 测试
6. 前端：login.html + login.js + common.js 401 跳转 + 设置同步
7. 文档：docs/database-schema.md + docs/api-contract.md + .gitignore + PROJECT_BRIEF 更新
8. 端到端验证 + 全量回归
