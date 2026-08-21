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

### 8. GET /api/projects — 列出当前用户项目（按文件修改时间倒序）

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

## 四、元数据接口（前端轻量化重构，`modules/meta.py`）

> 前端"瘦客户端"的数据单一来源：编辑器组件定义、工具名映射、工厂渲染参数、快速模板、
> 厂商预设均从这些端点拉取，app.js 不再内嵌硬编码（`static/app.js` 的 `applyMeta` 消费）。
> 拉取失败时编辑器回退到内置最小集（llm/agent/executor/memory 等 8 类，`FALLBACK_COMPONENT_DEFS`）。

### 12. GET /api/meta/components — 组件/工具/模板/厂商元数据

无参数。成功 `200`：

```json
{
  "success": true,
  "data": {
    "component_defs": {
      "llm": {"icon": "🔌", "title": "LLM API 设置", "color": "#4A90D9", "defaultSize": 6,
              "renderKey": "renderLLMPanel",
              "ports": {"outputs": [{"id": "llm-out", "label": "调用"}],
                        "inputs": [{"id": "llm-mem-in", "label": "记忆 ←"}]},
              "description": "...", "category": ["LLM", "cat-llm"]}
    },
    "tool_name_map": {"web_search": ["web_search"], "mcp_word": ["word_create", "..."]},
    "render_args": {"time_query": ["get_current_time", "当前时间/日期/星期/时间戳"]},
    "component_categories": {"llm": ["核心", "cat-core"], "web_search": ["工具", "cat-tools"]},
    "quick_templates": [{"key": "search", "name": "🔍 搜索助手", "description": "...",
                         "components": [{"type": "llm", "size": 5, "x": 3, "y": 3, "...": "..."}],
                         "connections": [{"source": 0, "target": 1, "sourcePort": "llm-out", "targetPort": "..."}]}],
    "provider_presets": [{"name": "OpenAI", "url": "https://api.openai.com/v1", "models": ["gpt-5"]}]
  }
}
```

字段说明：
- `component_defs`：全部组件定义（56+ 类）。`renderKey` 是前端 `RENDER_FN_MAP` 的键（渲染逻辑永留前端，
  后端只下发函数名）；`ports` 的 `inputs/outputs` 是连线端口定义。
- `tool_name_map`：组件类型 → 工具全名列表。工具注入链（`collectToolsFromPorts` /
  `autoSaveConnections` / `saveActive`）的**单一来源**。
- `render_args`：工厂渲染组件（simple-tool / mcp-simple / skill 三类，21 项）的显示参数数组，
  供前端工厂包装（`simpleToolPanelRender` / `mcpSimplePanelRender` / `skillPanelRender`）按类型取参。
- `component_categories`：组件分类映射——**键为组件类型**，值为 `[分类显示名, 分类 CSS class]`
  （如 `"llm": ["核心", "cat-core"]`），前端 `setupCategoryFilters` 据此渲染分类筛选。
- `quick_templates`：快速模板（11 个），`components` 用**布局内索引**（`connections.source/target`
  指向 components 下标），前端 `loadAgentPreset` 展开。
- `provider_presets`：厂商模型预设（`renderAPIConfigTab` 下拉用，空时前端回退"自定义"）。

### 13. GET /api/meta/settings — 设置面板元数据（主题/字号/行距滑块）

无参数。成功 `200`：

```json
{
  "success": true,
  "data": {
    "themes": [
      {"key": "industrial", "name": "Industrial", "description": "机能风 · 亮黄+黑灰"},
      {"key": "blue", "name": "Professional", "description": "专业风 · 蓝+白"},
      {"key": "glass", "name": "Glassmorphism", "description": "玻璃态 · 紫蓝渐变+毛玻璃"}
    ],
    "fontSizes": {"min": 0.8, "max": 1.2, "step": 0.05, "default": 1.0},
    "lineHeights": {"min": 1.2, "max": 2.2, "step": 0.1, "default": 1.6}
  }
}
```

> 说明：数据提取自 `templates/index.html` 设置面板（`.theme-option` 按钮 / 滑块）与
> `static/app.js` 的显示常量（FONT_SIZE_MIN 等），当前前端设置面板仍为静态 HTML（未接线消费本端点，
> 详见 task-6 报告"settings 前端接线评估"）。

失败 `401`：`{"success": false, "error": "未登录"}`

---

## 五、对话接口（SSE 流式）

### 14. POST /api/chat — LLM 对话（双格式：新布局格式 + 旧透传格式）

> 实现：`modules/chat_routes.py` + `modules/orchestrator.py`。返回 `text/event-stream`；
> 两种格式的 SSE 事件流**完全一致**（阶段 2 硬约束，`tests/test_chat_route.py` 锁定）。

**新格式（编辑器编排，Task 3/4 后端化）**——请求体：

```json
{
  "layout": {"components": [{"id": 1, "type": "llm", "...": "..."}],
             "connections": [{"id": "conn_1", "sourceCompId": 1, "targetCompId": 2, "...": "..."}]},
  "comp_id": 1,
  "message": "你好",
  "llm_config": {"apiBase": "https://api.deepseek.com", "apiKey": "sk-...", "model": "deepseek-chat", "maxToolRounds": 50}
}
```

- `layout` 存在且 `comp_id` 非空 → 走 `orchestrator.build_payload(layout, comp_id, message, llm_config)`：
  `resolve_tools` 解析 LLM 可达工具（含外部 MCP 动态注册名 `mcp_ext_<server_id>_<tool>`）→
  `compose_messages` 组装（memory 组件历史 + system_prompt 人设注入 + 用户消息）。
- `llm_config` 键名 camelCase / snake_case 均可（`apiBase|api_base`、`apiKey|api_key`、
  `maxToolRounds|max_tool_rounds`）；缺省回退服务器全局配置。

**旧格式（过渡兼容，chat.js 独立对话页等使用）**——请求体：

```json
{
  "messages": [{"role": "user", "content": "你好"}],
  "tools": [{"type": "function", "function": {"name": "calculator", "description": "...", "parameters": {...}}}],
  "model": "deepseek-chat",
  "api_base": "https://api.deepseek.com",
  "api_key": "sk-...",
  "max_tool_rounds": 50,
  "smart_mode": false,
  "session_id": "default"
}
```

公共字段：`max_search_rounds`（搜索硬上限 10 / 软提醒 8）、`system_prompt`（默认人设，新格式由
orchestrator 注入组件人设后跳过）。

**响应（SSE，`text/event-stream`）**，每帧 `data: <json>`：

| 帧 | 含义 |
|---|---|
| `{"choices":[{"delta":{"content":"..."}}]}` | 增量文本 |
| `{"choices":[{"delta":{"reasoning_content":"..."}}]}` | 增量推理内容（模型支持时） |
| `{"tool_calls":[{"id","name","arguments"}]}` | 工具调用请求（LLM 决定调用工具） |
| `{"tool_result":{"name","result"}}` | 工具执行结果（最多 8000 字符） |
| `{"error":"..."}` | 错误（如连接失败 / 消息超长） |
| `data: [DONE]` | 流结束 |
| `: keep-alive` | 心跳注释帧（15 秒空闲时） |

未登录 `401`：`{"success": false, "error": "未登录"}`

---

## 六、页面路由说明

| 路径 | 页面 | 保护 |
|---|---|---|
| `/login` | 登录/注册二合一页（`templates/login.html`） | **公开**（白名单）；已登录访问由前端自动跳 `/editor` |
| `/` | 管理后台（`admin.html`） | 受保护，未登录 302 → /login |
| `/editor` | Agent Editor 编辑器（`index.html`） | 受保护，未登录 302 → /login |
| `/chat` | AI 对话页（`chat.html`） | 受保护，未登录 302 → /login |
| `/projects` | 项目管理页（`projects.html`） | 受保护，未登录 302 → /login |

## 七、前端协作约定（实现补充）

- `static/common.js` fetch 包装：任何响应 `401` → 跳转 `/login`；登录态初始化检查。
- 设置同步：本地 `active-llm-config` 保存时同步 `PUT /api/settings/llm_config`；登录后 `GET /api/settings` 拉取合并（多设备同步）。
- 元数据消费（前端轻量化重构）：`static/app.js` 启动时 `GET /api/meta/components` 一次，
  `applyMeta` 填充 `COMPONENT_DEFS` / `TOOL_NAME_MAP` / `RENDER_ARGS` / `QUICK_TEMPLATES` /
  `PROVIDERS`；拉取失败回退内置最小集（模板无 fallback，点击时 toast 提示）。
- 登出后清 localStorage 并回登录页。
