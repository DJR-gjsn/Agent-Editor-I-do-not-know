# Agent Editor (wybzd)

基于 Flask + 原生 JS 的可视化 AI Agent 搭建与对话平台。通过拖拽连线的方式组合 LLM、工具与编排组件，生成可交互的 AI 工作流，并提供流式对话界面。

## ✨ 功能特性

- **可视化编辑器**：拖拽连线组装 LLM / 工具 / 编排 / 技能组件（executor、plan、loop、agent、skills_manager 等）
- **86+ 内置工具**：网页搜索、文档（Word/Excel/PPT/PDF）、代码执行、翻译、天气、图片处理、HTTP 请求、文件压缩、Git、数据库等
- **技能系统**：内置文档处理、前端设计、UI/UX、技能创建、PUA 教练等技能；支持 Skill Auto Call 智能模式（LLM 自主选择技能）
- **流式对话**：SSE 实时输出、思考过程展示、工具调用监控、可中断停止
- **记忆系统**：对话历史持久化、自动总结、向量记忆（语义检索）
- **项目管理**：多项目布局保存、自动保存、连线拓扑管理

## 🚀 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 LLM（环境变量，推荐）
set LLM_API_BASE=https://api.deepseek.com/v1
set LLM_API_KEY=你的密钥
set LLM_MODEL=deepseek-chat

# 3. 启动服务器
python server.py

# 4. 浏览器打开
#    http://localhost:5000      （管理后台 / 项目列表）
#    http://localhost:5000/editor （可视化编辑器）
#    http://localhost:5000/chat   （AI 对话）
```

> 密钥也可以在每个项目 / 编辑器的 LLM 组件面板中填写；**项目文件不会保存 API 密钥**（密钥仅存于浏览器 localStorage）。

## 🧪 测试

```bash
# 单元测试（无需服务器）
python -m unittest discover -s tests -v

# 全组件自动测试（需先启动服务器 + 配置 LLM_API_KEY）
python test_components_auto.py data/projects/proj_7142edabd6.json
# 生成 Excel 报告: component_status_report.xlsx
```

## 📁 项目结构

```
├── server.py              # Flask 入口（路由注册、项目/记忆管理）
├── modules/               # 后端模块（工具、编排、技能、LLM 客户端）
│   ├── chat_routes.py     # /api/chat SSE 流式对话路由
│   ├── mcp_*.py           # 各工具模块（office/web_search/utility 等）
│   ├── llm_client.py      # LLM tool-call 循环（超时保护、线程安全）
│   └── utils.py           # SSE/日志/工作区安全等工具函数
├── static/                # 前端（编辑器 app.js / 对话 chat.js）
├── templates/             # 页面模板
├── tests/                 # 单元测试
└── data/                  # 运行时数据（项目布局、对话记忆）
```

## ⚙️ 环境变量

| 变量 | 说明 | 默认 |
|---|---|---|
| `LLM_API_BASE` | OpenAI 兼容 API 地址 | `https://api.openai.com/v1` |
| `LLM_API_KEY` | API 密钥 | 空 |
| `LLM_MODEL` | 模型名 | `gpt-3.5-turbo` |
| `LLM_TOOL_TIMEOUT` | 工具执行超时（秒，支持小数） | `180` |
| `PORT` | 服务端口 | `5000` |

## 🔒 安全说明

- API 密钥通过环境变量或编辑器面板提供，**不写入项目文件 / git 仓库**
- 工具文件操作限制在共享工作区内（防目录穿越）；zip 解压内置 zip-slip 防护
- 历史提交中曾出现的密钥已通过 git filter-branch 从全部提交中清除
