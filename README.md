# Agent Editor (wybzd)

**Agent Editor** is a visual AI-agent builder and chat platform built with Python/Flask and vanilla JavaScript. Instead of writing glue code, you design AI workflows by dragging and connecting components — LLMs, tools, orchestrators, and skills — onto an interactive canvas, then talk to your agent through a real-time streaming chat interface.

Key capabilities:

- **Visual workflow editor** — wire together LLM, tool, orchestration (executor / plan / loop / agent), and skill components with drag-and-drop connections; save multiple project layouts with auto-save
- **80+ built-in tools** — web search, office documents (Word / Excel / PPT / PDF), code execution, translation, weather, image processing, generic HTTP requests, file compression, Git, databases, and more
- **External MCP tools** — connect any MCP server (stdio or HTTP) and use its tools in your flows; tools are registered dynamically at runtime
- **Skill system** — built-in domain skills (document processing, frontend design, UI/UX, skill creation, PUA coaching, …) plus an intelligent mode where the LLM auto-selects the right skill via `use_skill`
- **Streaming chat** — SSE token-by-token output, reasoning display, live tool-call monitoring, and abortable generation
- **Memory system** — persistent conversation history, auto-summarization, and vector semantic search (disk-persisted)
- **Multi-user authentication** — register / login (server-side sessions), per-user project isolation, and cross-device settings sync
- **Security first** — API keys never persist in project files or git; workspace path confinement and zip-slip protection built in

**Tech stack:** Python 3.14 · Flask 3.1 · SQLite (stdlib) · vanilla JS (no build step) · SSE streaming · stdlib-only unit tests · Docker

---

基于 Flask + 原生 JS 的可视化 AI Agent 搭建与对话平台。通过拖拽连线的方式组合 LLM、工具与编排组件，生成可交互的 AI 工作流，并提供流式对话界面。

## ✨ 功能特性

- **可视化编辑器**：拖拽连线组装 LLM / 工具 / 编排 / 技能组件（executor、plan、loop、agent、skills_manager 等），支持框选、快速模板
- **86+ 内置工具**：网页搜索、文档（Word/Excel/PPT/PDF）、代码执行、翻译、天气、图片处理、HTTP 请求、文件压缩、Git、数据库等
- **外部 MCP 工具**：设置面板配置 MCP Server（stdio / HTTP），工具动态注册进对话引擎，编辑器"外部 MCP 工具"组件可勾选使用
- **技能系统**：内置文档处理、前端设计、UI/UX、技能创建、PUA 教练等技能；支持 Skill Auto Call 智能模式（LLM 自主选择技能）
- **流式对话**：SSE 实时输出、思考过程展示、工具调用监控、可中断停止
- **记忆系统**：对话历史持久化、自动总结、向量记忆（语义检索，落盘持久化重启不丢）
- **多用户认证**：注册 / 登录（服务端会话 Cookie、密码哈希），项目按用户隔离，设置多设备同步
- **前端轻量化**：组件/工具/模板元数据后端下发（`/api/meta/*`），对话编排后端化（orchestrator），前端为薄壳

## 🚀 快速开始

### 方式一：Docker（推荐，公网部署）

```bash
docker compose up -d --build
# 浏览器打开 http://服务器IP:5000 → 注册账号 → 登录
# 数据持久化在 ./data/（SQLite/项目/向量库/MCP 配置）
```

### 方式二：本机直接运行

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 LLM（环境变量，推荐）
set LLM_API_BASE=https://api.deepseek.com/v1
set LLM_API_KEY=你的密钥
set LLM_MODEL=deepseek-chat

# 3. 启动服务器
python server.py            # 或双击 StartServer.bat

# 4. 浏览器打开 http://localhost:5000 → 注册账号 → 登录
#    （全局登录保护：未登录页面 302 到 /login，API 返回 401）
```

> 密钥也可以在每个项目 / 编辑器的 LLM 组件面板中填写；**项目文件不会保存 API 密钥**。

## 🧪 测试

```bash
# 单元测试（无需服务器）
python -m unittest discover -s tests -v

# 全组件自动测试（需先启动服务器 + 配置 LLM_API_KEY + 登录账号）
set LLM_API_KEY=你的密钥
python test_components_auto.py data/projects/djr/proj_b3f7d16fb5.json
# 默认用 djr 账号登录测试；可设置 TEST_USER / TEST_PASS 指定账号
# 按组件类型分块：set TEST_TYPES=skill_frontend,skill_pua
# 生成 Excel 报告: component_status_report.xlsx
```

## 📁 项目结构

```
├── server.py              # Flask 入口（登录保护 before_request / 项目/记忆/静态路由）
├── modules/               # 后端模块
│   ├── db.py              # SQLite 连接层（users/sessions/user_settings）
│   ├── auth.py            # 注册/登录/登出/改密码 + 用户设置 CRUD
│   ├── meta.py            # 前端元数据单一来源（组件/工具映射/模板/厂商/设置）
│   ├── orchestrator.py    # 编排链（布局→工具注入→payload，含 executor/agent 中介链）
│   ├── chat_routes.py     # /api/chat SSE 流式对话路由（双格式）
│   ├── llm_client.py      # LLM tool-call 循环（超时保护、线程安全）
│   ├── mcp_client.py      # 轻量 MCP client（stdio/HTTP，JSON-RPC 2.0）
│   ├── mcp_manager.py     # MCP Server 配置/生命周期/动态注册
│   ├── vector_memory.py   # 向量记忆（落盘持久化）
│   └── mcp_*.py           # 各工具模块
├── static/                # 前端（app.js 薄壳 / chat.js / login.js / settings-panel.js）
├── templates/             # 页面模板（index/chat/login/projects/admin）
├── tests/                 # 单元测试（127 个）
├── Dockerfile / docker-compose.yml   # Docker 部署
└── data/                  # 运行时数据（SQLite/项目/向量库/MCP 配置，卷挂载/被 git 忽略）
```

## ⚙️ 环境变量

| 变量 | 说明 | 默认 |
|---|---|---|
| `LLM_API_BASE` | OpenAI 兼容 API 地址 | `https://api.openai.com/v1` |
| `LLM_API_KEY` | API 密钥 | 空 |
| `LLM_MODEL` | 模型名 | `gpt-3.5-turbo` |
| `LLM_TOOL_TIMEOUT` | 工具执行超时（秒，支持小数） | `180` |
| `PORT` | 服务端口 | `5000` |
| `FLASK_ENV` | `production` 关闭 debug/reloader（生产必须） | 空（debug） |

## 🔒 安全说明

- 全局登录保护：除登录/注册/静态资源外，页面 302 跳登录、API 401
- 密码使用 werkzeug pbkdf2 哈希存储，登录失败统一提示（防枚举）
- 项目按用户隔离（`data/projects/<username>/`），目录穿越防护
- API 密钥通过环境变量或编辑器面板提供，**不写入项目文件 / git 仓库**
- 工具文件操作限制在共享工作区内（防目录穿越）；zip 解压内置 zip-slip 防护
- MCP Server 配置（可能含 token）仅存本地 `data/mcp_config.json`，git 忽略

## 📚 文档

- `docs/USAGE.md` — 详细使用说明
- `docs/database-schema.md` — 数据库 Schema / ER 图
- `docs/api-contract.md` — API 接口契约
- `PROJECT_BRIEF.md` — 项目简报（新对话交接用）
