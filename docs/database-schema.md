# 数据库 Schema / ER 图（登录认证 + 后端存储）

> 来源：`docs/superpowers/specs/2026-08-18-auth-storage-design.md` 第三、四节
> 核对：与 `modules/db.py` 的 `_SCHEMA` 实际实现一致（2026-08-18 实现）

## 一、总览

| 项 | 值 |
|---|---|
| 数据库文件 | `data/app.db`（SQLite，stdlib `sqlite3`，零新依赖） |
| 初始化 | `modules/db.py` 启动时 `CREATE TABLE IF NOT EXISTS` 幂等建表 |
| 连接模型 | 线程本地连接（sqlite3 连接不可跨线程共享）；`PRAGMA foreign_keys = ON` 强制外键级联 |
| 路径注入 | `db.init_db(path)` 可重定向（测试/多实例隔离）；环境变量 `APP_DB_PATH` 亦可 |
| gitignore | `data/app.db` 已排除，不入库 |

共 3 张表：`users`（用户账号）、`sessions`（服务端会话）、`user_settings`（用户设置 key-value）。

## 二、DDL（实际实现，与 spec 一致）

```sql
-- 用户表
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 会话表（服务端会话）
CREATE TABLE IF NOT EXISTS sessions (
    id         TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL,
    user_agent TEXT,
    ip         TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

-- 用户设置表（key-value，value 为 JSON 字符串）
CREATE TABLE IF NOT EXISTS user_settings (
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key        TEXT NOT NULL,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, key)
);
```

## 三、字段说明

### users（用户表）

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 用户 ID |
| username | TEXT | NOT NULL, UNIQUE | 登录名；格式 `^[a-zA-Z0-9_]{3,32}$`（服务端校验） |
| password_hash | TEXT | NOT NULL | werkzeug pbkdf2 哈希（`pbkdf2:sha256`），**绝不存明文** |
| created_at | TEXT | NOT NULL DEFAULT datetime('now') | 注册时间（UTC 格式字符串） |

### sessions（会话表，服务端会话）

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | TEXT | PRIMARY KEY | session_id（`uuid.uuid4().hex`，32 位十六进制） |
| user_id | INTEGER | NOT NULL, REFERENCES users(id) ON DELETE CASCADE | 所属用户；用户删除则会话级联删除 |
| created_at | TEXT | NOT NULL DEFAULT datetime('now') | 创建时间 |
| expires_at | TEXT | NOT NULL | 过期时间（创建 + 7 天；滑动续期会更新） |
| user_agent | TEXT | — | 登录时请求 UA（截断 200 字符，可空） |
| ip | TEXT | — | 登录时客户端 IP（可空） |

### user_settings（用户设置表）

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| user_id | INTEGER | NOT NULL, REFERENCES users(id) ON DELETE CASCADE，复合主键之一 | 所属用户 |
| key | TEXT | NOT NULL，复合主键之一 | 设置名（如 `llm_config`、`ui_prefs`） |
| value | TEXT | NOT NULL | JSON 字符串（任意 JSON 序列化存储） |
| updated_at | TEXT | NOT NULL DEFAULT datetime('now') | 最后更新时间（UPSERT 时刷新） |

## 四、索引说明

| 索引 | 表 | 列 | 目的 |
|---|---|---|---|
| `idx_sessions_user` | sessions | user_id | 按用户查会话（滑动续期/登出清理）加速 |

其余查询均为单行主键/唯一键访问（`users.username` UNIQUE、`users.id` PK、`sessions.id` PK、`user_settings(user_id, key)` 复合 PK），SQLite 自动建索引，无需额外索引。

## 五、ER 图（Mermaid）

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

## 六、密码哈希与会话策略

- **密码哈希**：`werkzeug.security.generate_password_hash(password, method="pbkdf2:sha256")`；校验用 `check_password_hash`。数据库只存哈希，明文绝不出现在数据库/日志/前端。
- **会话生成**：登录成功生成 `session_id = uuid.uuid4().hex`，写入 sessions 表，并通过 HttpOnly Cookie（`session_id=...`，SameSite=Lax，max_age = 7×86400 秒）下发给浏览器。
- **有效期**：7 天（`SESSION_TTL_DAYS = 7`）。
- **滑动续期**：每次有效请求（`auth.get_current_user()`）若剩余有效期不足一半（< 3.5 天），则把 `expires_at` 续到当前时间 + 7 天。
- **惰性清理**：会话过期后首次被访问即删除该行（`DELETE FROM sessions WHERE id = ?`）；登出时按 session_id 删除。
- **登录失败防枚举**：用户不存在与密码错误统一返回 401 "用户名或密码错误"。
- **CSRF 缓解**：SameSite=Lax + 认证/设置接口仅接受 JSON POST，风险可控（设计文档第九节）。

## 七、项目数据隔离（存储层面）

- 项目数据**不入数据库**：保持 JSON 文件，路径为 `data/projects/<username>/<project_id>.json`（`<project_id>` 仅允许 `[a-zA-Z0-9_-]{1,64}`，`_project_path` 防目录穿越，强制落在当前用户目录内）。
- 不同用户互不可见：列表/读写均按 `request.user.username` 路由到各自目录。
- gitignore：`data/projects/*/` 整个排除用户名目录；既有 `data/projects/*.json` 规则保留兼容旧文件。
