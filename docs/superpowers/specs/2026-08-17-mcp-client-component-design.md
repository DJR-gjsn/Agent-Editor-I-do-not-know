# 外部 MCP 工具组件 — 设计文档

> 日期：2026-08-17 · 状态：已获用户批准（分两节确认）
> 目标：为 Agent Editor 添加 MCP client 能力，编辑器内可用外部 MCP server 的工具

## 一、背景与目标

Agent Editor 目前只能使用**进程内注册**的内置工具（`tool_registry`，约 48 个）。用户希望接入 MCP 生态（filesystem/git/github 等现成 server），让可视化画布上的 LLM 能调用外部工具。

### 需求（用户已确认的决策）

| 决策点 | 选择 |
|---|---|
| 接入形态 | **混合**：全局配置（`data/mcp_config.json`）+ 编辑器组件引用 |
| 连接方式 | **stdio + HTTP 都支持**（统一抽象层） |
| 实现方式 | **手写轻量 client**（stdlib，不新增依赖） |
| 组件粒度 | **默认暴露 server 全部工具，节点上可筛选** |

### 非目标（YAGNI）

- 不支持 MCP resources / prompts（只实现 tools 子集）
- 不做工具调用流式结果（MCP 返回整体结果）
- 不做 server 自动发现/市场浏览
- 不改 `llm_client.py` 核心 tool-call 循环（零侵入，靠 `tool_registry` 动态注册）

## 二、架构总览

```
┌─ 前端（编辑器）────────────────────────────┐
│ 设置面板 "MCP Servers" 区（增删改查/测试连接）  │
│ 组件面板 "外部 MCP 工具" 节点（引用server+筛工具）│
└──────────────┬─────────────────────────────┘
               │ /api/mcp/*（JSON）
┌──────────────▼─────────────────────────────┐
│ server.py 路由层                            │
│  modules/mcp_manager.py  ← 配置+生命周期+注册 │
│  modules/mcp_client.py   ← 纯协议层（无Flask）│
│    ├ StdioTransport: subprocess + JSON-RPC   │
│    └ HttpTransport: requests + JSON-RPC/SSE  │
│  tool_registry（动态 register/unregister）    │
└─────────────────────────────────────────────┘
```

### 核心集成原则

所有工具调用最终走 `tool_registry.execute()`（`llm_client.py` 第 204/258 行已确认）。
MCP 工具通过 `tool_registry.register(name, definition, executor)` **动态注册**（第 50 行签名已确认），
因此对话引擎、SSE、超时、request_config 传递等基础设施**完全复用，零修改**。

## 三、模块设计

### 3.1 `modules/mcp_client.py`（协议层，~350 行，无 Flask 依赖）

**类结构**：

- `MCPError(Exception)` — 统一错误类型
- `MCPClient` — 核心门面：
  - `initialize()`：握手（协议版本协商，固定发 1.0 请求，容忍 server 返回更新版本）
  - `list_tools() -> list[dict]`：返回 `[{name, description, inputSchema}, ...]`（处理 cursor 分页，按页取全）
  - `call_tool(name, args) -> str`：返回文本结果（`isError` 标志为 true 时返回错误文本）
  - `close()`：关闭传输（stdio 终止子进程；HTTP 无状态）
- `StdioTransport`：
  - `subprocess.Popen(command, args, stdout=PIPE, stderr=PIPE, text=True)` 启动
  - MCP stdio 标准：**JSON-RPC 2.0，每行一个 JSON 消息**（newline-delimited，无 Content-Length）
  - stdout 由独立读线程推入 `queue.Queue`，`call_tool` 从队列等响应（按 `id` 匹配请求）
  - 60s 读超时；子进程意外退出时**自动重启一次**再报错
  - stderr 单独读线程收集，出错时拼进错误消息辅助排查
- `HttpTransport`：
  - `requests.post(url, json=payload, headers={"Accept": "application/json, text/event-stream"}, timeout=...)`
  - 响应体兼容两种格式：纯 JSON（`application/json`）与 SSE 流（逐 `data:` 行拼 JSON）
  - 60s 超时；非 2xx / 网络异常 → `MCPError`

**协议方法（JSON-RPC 2.0）**：

| 方法 | 方向 | 说明 |
|---|---|---|
| `initialize` | client→server | 握手，携带 protocolVersion=1.0、clientInfo |
| `notifications/initialized` | client→server | 握手完成通知（只发不期待响应） |
| `tools/list` | client→server | 工具清单（支持 cursor 分页） |
| `tools/call` | client→server | 调用工具，参数 `{name, arguments}` |
| `ping` | client→server | 健康检查（可选，test 连接时用） |

### 3.2 `modules/mcp_manager.py`（配置 + 生命周期 + 注册，~300 行）

**配置存储**：`data/mcp_config.json`（全局、gitignore 排除）

```json
{
  "servers": [
    {
      "id": "git",
      "name": "Git Tools",
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-git"],
      "enabled": true
    },
    {
      "id": "remote-ai",
      "name": "Remote AI Server",
      "type": "http",
      "url": "https://example.com/mcp",
      "token": "sk-xxx",
      "enabled": true
    }
  ]
}
```

字段说明：
- `id`：必填，唯一 slug（`^[a-zA-Z0-9_-]{1,32}$`，用于工具名前缀与路由）
- `name`：显示名
- `type`：`stdio` | `http`（互斥）
- stdio：`command` + `args[]`；http：`url` + 可选 `token`
- `enabled`：false 时不连接不注册（停用而不删除）

**生命周期**：

- 启动时：`load_and_sync()` 读配置 → 对每个 enabled server：连接 → `list_tools` → 注册
- 工具命名：`mcp_ext_<server_id>_<tool_name>`（`mcp_ext_` 前缀避开内置 `mcp_git`/`mcp_zip` 等）
- 配置变更：`sync_server(server_id)` 先 `unregister` 旧工具，再按新配置重连注册（热更新）
- 删除：`remove_server(server_id)` 注销工具 + 移除配置
- **失败隔离**：单个 server 连接/注册失败 → 标记 `error` + 保存错误消息，**不阻塞其他 server**，不阻塞服务器启动
- **状态查询**：`get_status() -> [{id, name, type, enabled, connected, error, tool_count}]`

**命名冲突与校验**：
- server id 新增时查重（重复 400）
- 注册前检查 `mcp_ext_<id>_<tool>` 是否已被占用（内置工具不可能冲突，防御性检查）

### 3.3 `server.py` 路由层

| 路由 | 方法 | 作用 |
|---|---|---|
| `/api/mcp/servers` | GET | 配置列表 + 连接状态 + 工具数 |
| `/api/mcp/servers` | POST | 新增（校验 + 保存 + 连接注册） |
| `/api/mcp/servers/<id>` | PUT | 更新（热更新注册；**id 不可变**，仅更新其他字段） |
| `/api/mcp/servers/<id>` | DELETE | 删除 + 注销 |
| `/api/mcp/servers/<id>/test` | POST | 测试连接（initialize + list_tools，不注册） |
| `/api/mcp/servers/<id>/tools` | GET | 工具列表（供前端筛选 UI） |

响应统一 `{success, ...}` 或 `{success: false, error}`。

### 3.4 前端（编辑器）

**设置面板新增 "MCP Servers" 区**：
- server 列表：名称、类型、状态徽标（已连接/错误/已停用）、工具数
- 新增/编辑表单：id、name、type 切换（stdio→命令+args 多行；http→url+token）、enabled 开关
- 操作按钮：测试连接、保存、删除
- stdio 类型下显示警示文案："将以本机权限启动该命令，仅添加可信来源"

**`COMPONENT_DEFS` 新增 `mcp_external` 节点**（"外部 MCP 工具"）：
- `render`：server 下拉（`GET /api/mcp/servers`，仅列 enabled）→ 选后拉 `GET /api/mcp/servers/<id>/tools` 显示工具多选（默认全选，可勾选子集）
- 组件数据：`{serverId, toolNames: [...]}`（toolNames 空 = 全部）
- 端口：参照现有工具组件（inputs 接 LLM/执行器）

**工具名注入扩展**：
- `collectToolsFromPorts`（app.js 第 158 行）：`TOOL_NAME_MAP` 是静态映射，MCP 工具是动态的——扩展逻辑：命中 `mcp_external` 类型时，回退读取 `comp.toolNames`（节点保存的具体工具名，见 3.4），不再依赖静态 map
- `serializeComponent` 白名单：新增 `serverId`、`toolNames` 字段（**不含 token/命令/URL**，密钥只存全局配置）

## 四、错误处理与超时

- **双层超时**：外层 `tool_registry.execute` 180s（现有机制）兜底；内层 MCP 调用 60s（stdio 读线程 queue 等待 / HTTP requests timeout）
- **超时结果**：返回明确错误文本（"外部 MCP 工具调用超时（60s）"），不悬挂
- **server 崩溃**：`call_tool` 抛 `MCPError` → handler 返回错误字符串；stdio 子进程意外退出自动重启一次
- **HTTP 失败**：连接拒绝/超时/非 2xx → 统一 `MCPError` 文本
- **注册冲突**：`mcp_ext_` 前缀 + id 校验 + 防御性占用检查

## 五、安全

- **配置不入 git**：`data/mcp_config.json` 加入 `.gitignore`（与 `data/vector_store/` 同级）
- **token 不落项目 json**：MCP 配置存全局文件；`serializeComponent` 白名单只存 `serverId`/`toolNames` 引用
- **stdio 执行任意命令**：UI 警示文案提示用户；不做命令黑名单（合法工具也需任意命令）；风险靠用户自觉 + 配置仅存本地
- **enabled 开关**：停用不删除，可随时关闭外部能力

## 六、测试

新增 2 个文件（全量 42 → ~55）：

| 文件 | 覆盖 |
|---|---|
| `tests/fixtures/mini_mcp_server.py` | 测试 fixture：stdlib 实现的迷你 MCP server（stdio + HTTP 双模式），暴露 2 个工具：`echo`（回显 args）、`fail`（固定报错） |
| `tests/test_mcp_client.py` | 协议层：stdio 子进程往返（initialize/list_tools/call_tool）、参数传递、`fail` 错误响应、60s 超时（用挂起工具）、HTTP 传输往返、连接失败报错 |
| `tests/test_mcp_manager.py` | 配置 CRUD（临时文件隔离，不碰真实 `data/mcp_config.json`）、启动注册/注销、命名规则 `mcp_ext_<id>_<tool>`、单 server 失败不阻塞其他、token 不写入项目 json |

现有 42 个测试不受影响（新模块独立，无全局状态污染）。

## 七、实现顺序（供 writing-plans 参考）

1. `modules/mcp_client.py` 协议层 + fixture server + `test_mcp_client.py`
2. `modules/mcp_manager.py` 配置/生命周期/注册 + `test_mcp_manager.py`
3. `server.py` 路由挂载 + `.gitignore` 更新
4. 前端：设置面板 MCP 区 + `mcp_external` 组件 + 工具名注入扩展
5. 端到端验证（真实 npx server 或 fixture）+ 全量回归
