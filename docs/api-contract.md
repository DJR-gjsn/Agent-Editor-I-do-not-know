# 接口契约（登录认证 + 后端存储）

> 来源：`docs/superpowers/specs/2026-08-18-auth-storage-design.md` 第六节
> 核对：与 `modules/auth.py`、`server.py` 实际实现一致（2026-08-18）
> 所有接口均为 JSON；除注册/登录外均需登录（Cookie `session_id`）

## 〇、保护规则（所有接口/页面的前提）

- **白名单**（无需登录）：`/login`、`/static/*`、`/favicon.ico`、`/api/auth/login`、`/api/auth/register`
- **API 未登录** → `401 {"success": false, "error": "未登录"}`
- **页面未登录** → `302` 重定向 `/login`
- **Cookie**：`session_id`（HttpOnly、SameSite=Lax、7 天、每次有效请求滑动续期）
- **用户名**：`^[a-zA-Z0-9_]{3,32}$`；**密码**：至少 6 位
- **登录失败防枚举**：用户不存在/密码错误统一返回 `401 "用户名或密码错误"`
- **限流**：非静态/非 SSE/非 memory 路径每 IP 60 秒内最多 300 次，超限 `429 {"error": "请求过于频繁，请稍后重试"}`（实现补充）

---

## 一、认证接口（4 个）

### 1. POST /api/auth/register — 注册

请求体：

```json
{"username": "alice", "password": "secret123"}
```

成功 `201`：

```json
{"success": true, "user": {"id": 1, "username": "alice"}}
```

失败 `400`（用户名非法 / 已存在 / 密码过短）：

```json
{"success": false, "error": "用户名须为 3-32 位字母/数字/下划线"}
{"success": false, "error": "用户名已存在"}
{"success": false, "error": "密码至少 6 位"}
```

### 2. POST /api/auth/login — 登录

请求体：

```json
{"username": "alice", "password": "secret123"}
```

成功 `200`（同时 `Set-Cookie: session_id=<uuid hex>; HttpOnly; SameSite=Lax; Max-Age=604800`）：

```json
{"success": true, "session_id": "3f0a...", "user": {"id": 1, "username": "alice"}}
```

失败 `401`（用户不存在与密码错误同一消息，防枚举）：

```json
{"success": false, "error": "用户名或密码错误"}
```

### 3. POST /api/auth/logout — 登出

无请求体。成功 `200`（删除 sessions 行 + 清 Cookie）：

```json
{"success": true}
```

### 4. GET /api/auth/me — 当前用户

无参数。成功 `200`：

```json
{"success": true, "user": {"id": 1, "username": "alice"}}
```

失败 `401`（未登录/会话无效或过期）：

```json
{"success": false, "error": "未登录"}
```

---

## 二、用户设置接口（3 个，key-value，value 为任意 JSON）

### 5. GET /api/settings — 拉取全部设置（多设备同步）

无参数。成功 `200`：

```json
{"success": true, "settings": {"llm_config": {"apiBase": "https://api.deepseek.com", "model": "deepseek-chat"}, "ui_prefs": {"theme": "dark"}}}
```

失败 `401`：

```json
{"success": false, "error": "未登录"}
```

### 6. PUT /api/settings/<key> — 写入/覆盖一个设置

请求体（`value` 为任意 JSON，序列化后存 `user_settings.value`；UPSERT）：

```json
{"value": {"apiBase": "https://api.deepseek.com", "model": "deepseek-chat"}}
```

成功 `200`：

```json
{"success": true}
```

失败 `400`（缺 `value`）：

```json
{"success": false, "error": "缺少 value"}
```

失败 `401`：

```json
{"success": false, "error": "未登录"}
```

### 7. DELETE /api/settings/<key> — 删除一个设置

无请求体。成功 `200`（删除不存在的 key 也返回成功）：

```json
{"success": true}
```

失败 `401`：

```json
{"success": false, "error": "未登录"}
```

---

## 三、项目接口（4 个，按当前登录用户隔离）

> 文件存储：`data/projects/<username>/<project_id>.json`；`project_id` 仅允许 `[a-zA-Z0-9_-]{1,64}`（`fullmatch` 校验，防目录穿越）。
> 注意：项目接口沿用存量响应格式（**裸 JSON，不包 `success` 字段**），前端已按此适配。

### 8. GET /api/projects — 列出当前用户项目（按更新时间倒序）

成功 `200`：

```json
[
  {"id": "proj_ab12cd34ef", "name": "我的工作流", "componentCount": 5, "connectionCount": 4, "updatedAt": "2026-08-18 12:00:00"}
]
```

失败 `401`：`{"success": false, "error": "未登录"}`

### 9. POST /api/projects — 创建或更新项目

请求体：`{"id": "proj_ab12cd34ef", "name": "...", "layout": {...}}`（`id` 缺省则新建，`uuid4().hex[:10]` 生成 `proj_<10hex>`；带 `id` 则合并更新，`layout` 经 `_merge_layout` 保护历史类字段）。

成功 `200`：

```json
{"id": "proj_ab12cd34ef", "name": "我的工作流"}
```

失败 `400`（非法 project_id）：`{"error": "非法 project_id"}`；`404`（更新不存在的项目）：`{"error": "项目不存在"}`；`401`：`{"success": false, "error": "未登录"}`

### 10. GET /api/projects/<project_id> — 读取单个项目

成功 `200`（完整项目 JSON）：

```json
{"id": "proj_ab12cd34ef", "name": "我的工作流", "layout": {"components": [], "connections": []}, "createdAt": "2026-08-18 10:00:00", "updatedAt": "2026-08-18 12:00:00"}
```

失败 `400`：`{"error": "非法 project_id"}`；`404`：`{"error": "项目不存在"}`；`401`：`{"success": false, "error": "未登录"}`

### 11. DELETE /api/projects/<project_id> — 删除项目

成功 `200`：

```json
{"ok": true}
```

失败 `400`：`{"error": "非法 project_id"}`；`401`：`{"success": false, "error": "未登录"}`

---

## 四、页面路由说明

| 路径 | 页面 | 保护 |
|---|---|---|
| `/login` | 登录/注册二合一页（`templates/login.html`） | **公开**（白名单）；已登录访问由前端自动跳 `/editor` |
| `/` | 管理后台（`admin.html`） | 受保护，未登录 302 → /login |
| `/editor` | Agent Editor 编辑器（`index.html`） | 受保护，未登录 302 → /login |
| `/chat` | AI 对话页（`chat.html`） | 受保护，未登录 302 → /login |
| `/projects` | 项目管理页（`projects.html`） | 受保护，未登录 302 → /login |

## 五、前端协作约定（实现补充）

- `static/common.js` fetch 包装：任何响应 `401` → 跳转 `/login`；登录态初始化检查。
- 设置同步：本地 `active-llm-config` 保存时同步 `PUT /api/settings/llm_config`；登录后 `GET /api/settings` 拉取合并（多设备同步）。
- 登出后清 localStorage 并回登录页。
