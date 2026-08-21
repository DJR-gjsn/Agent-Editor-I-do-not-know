# Agent Editor 使用说明

> 可视化 AI Agent 搭建与对话平台 · Flask + 原生 JS · 无构建步骤

---

## 一、快速开始

### 0. Docker 部署（可选，公网部署推荐）
```bash
docker compose up -d --build
# 浏览器访问 http://服务器IP:5000 → 注册账号 → 登录
# 数据持久化在 ./data/（SQLite/项目/向量库/MCP 配置）
```

### 1. 安装依赖
```bash
pip install -r requirements.txt
```

### 2. 配置 LLM
两种方式任选：

**方式 A：环境变量（推荐）**
```powershell
set LLM_API_BASE=https://api.deepseek.com/v1
set LLM_API_KEY=你的密钥
set LLM_MODEL=deepseek-chat
```

**方式 B：编辑器内配置**
在编辑器的 LLM 组件面板选择厂商（内置 OpenAI / DeepSeek / Groq / 智谱 / 通义千问 / Kimi / Gemini / Ollama 预设，均为最新模型），填入 API Base 与 Key。
> 安全：API 密钥**不会写入项目文件**，仅存于浏览器 localStorage。

### 3. 注册与登录（全局登录保护）
首次访问任何页面会跳转到 **登录页（/login）**，需**注册账号**后才能使用：
- 注册：填写用户名（3-32 位字母/数字/下划线）+ 密码（至少 6 位）
- 登录：会话 Cookie 有效期 7 天（滑动续期），期间免登录
- 退出：页面右上角"⏻ 登出"或设置面板"账号"区的退出按钮
- 改密码：设置面板"账号"区（改密码后其他设备会话自动失效）

### 4. 启动
- **双击 `StartServer.bat`**（自动打开浏览器），或
- `python server.py` 后访问 **http://localhost:5000**（务必用 localhost，勿用 127.0.0.1）

### 5. 停止
- 双击 `StopServer.bat`，或直接关闭服务器窗口

---

## 二、页面导航

| 页面 | 地址 | 用途 |
|---|---|---|
| 登录/注册 | `/login` | 注册账号 / 登录（未登录自动跳转至此） |
| 管理后台 | `/` | 统计总览、快捷入口 |
| 可视化编辑器 | `/editor` | 拖拽连线搭建 Agent 工作流 |
| AI 对话 | `/chat` | 与 Agent 对话（SSE 流式） |
| 项目管理 | `/projects` | 项目列表与切换（登录后落点） |

> 登录后默认进入项目管理页；项目按用户隔离（不同账号看不到彼此项目）。

---

## 三、编辑器使用

### 组件面板
左侧面板按分类列出全部 **56 个组件**（核心/编排/流程/记忆/Skill/工具/MCP），支持搜索与分类筛选。拖拽到画布即可使用。

### 连线规则
- LLM → 执行器（Executor/Agent/Sequential）→ 工具
- 技能组件只能连到 Skills Manager
- Skill Auto Call 只能连在 LLM 与 Skills Manager 之间
- **Token 计数器 / 知识库只能连接 LLM / Vector Memory**
- 非法连线会被阻止并提示

### 画布操作
| 操作 | 方式 |
|---|---|
| 缩放 | 滚轮 |
| 平移 | 中键拖拽 |
| 单选 | 单击组件 |
| **框选** | **左键在空白处拖拽**（框内组件高亮） |
| 多选增删 | Ctrl/⌘ + 单击 |
| 整组移动 | 拖动组内任意组件标题栏 |
| 批量删除 | 选中组后按 Delete/Backspace |
| 撤销 | Ctrl+Z |

### 常用组件速览
- **LLM**：模型大脑，配置厂商/模型/密钥
- **Executor / Plan / Loop / Agent**：任务执行、计划、循环、编排中枢
- **Web Search / URL Fetch**：联网搜索与网页抓取
- **Word / Excel / PPT / PDF**：办公文档生成
- **HTTP 请求 / 压缩工具 / 图片工具**：通用 API 调用、文件打包、图片处理
- **Vector Memory + 知识库**：语义记忆库，知识库可从电脑导入 txt/md/csv/json/pdf/docx/xlsx 并支持改名
- **Token 计数器**：连接 LLM 后对话页实时显示用量
- **Skills Manager + Skill Auto Call**：智能技能调度（LLM 自主选技能）

### 快速模板
顶部"⭐ 快速模板"提供 11 个场景模板（搜索助手/数据分析/计划执行/文档/设计/技能工坊/开发包/深度研究/办公套件/PUA/全能 Agent），一键加载连线完毕的工作流。

### 设置面板（⚙️）
- 主题：Industrial / Professional / Glassmorphism
- 字体大小：0.8x–1.2x 滑块
- 行距：1.2–2.2 滑块
- **MCP Servers**：配置外部 MCP Server（stdio 命令或 HTTP 地址），添加后画布可用"外部 MCP 工具"组件
- **账号**：当前用户、修改密码、退出登录

---

## 四、对话页使用

- SSE 流式输出、思考过程折叠展示、工具调用监控面板
- 停止按钮（⏹）可随时中断生成
- 技能选择：通用模式 / 各技能 / 智能模式（LLM 自主选技能）
- 记忆面板显示 Token 用量（K 格式）
- 文件面板：可把生成的文件保存到本地目录

---

## 五、组件功能清单

- `组件功能清单.xlsx`：全部 56 个组件的类型/名称/分类/工具/功能说明
- `component_status_report.xlsx`：全组件自动化测试结果（45 PASS / 3 WARN，WARN 为数据库/邮件/导航未配置所致，非故障）

重新生成清单：`python generate_component_list.py`
重新跑测试：`python test_components_auto.py data/projects/proj_b3f7d16fb5.json`（需配置 LLM_API_KEY）

---

## 六、测试

```bash
# 单元测试（无需服务器）
python -m unittest discover -s tests -v

# 全组件自动测试（需先启动服务器 + 配置 LLM_API_KEY + 有效账号）
$env:LLM_API_KEY="sk-xxx"
python test_components_auto.py data/projects/djr/proj_b3f7d16fb5.json
# 默认用 djr 账号登录测试（可用 TEST_USER / TEST_PASS 指定其他账号）
# 按组件类型分块调试：$env:TEST_TYPES="skill_frontend,skill_pua"
```

---

## 七、常见问题

| 问题 | 解决 |
|---|---|
| 对话页没有技能选项 | 用 **localhost** 打开（127.0.0.1 的 localStorage 独立） |
| 没看到登录页 / 显示旧页面 | 浏览器 Ctrl+F5 强刷（页面已 no-cache）；确认服务器是最新代码（重启） |
| 登录后看不到旧项目 | 项目按用户隔离——旧平铺项目需移到 `data/projects/<用户名>/` 下 |
| 控制台报 favicon 404 | 无害（已内置图标，强制刷新即可） |
| 滚轮缩放边缘变黑块 | 设置面板把字体大小调回 100% |
| 停止生成后气泡空白 | 已修复：显示"（已停止）" |
| MCP 目录权限报错 | 点"选择存储目录"按钮重新授权（浏览器要求用户手势） |

---

## 八、GitHub 同步

```powershell
cd D:\myxiangfa-MCPxuexi
git push
```
仓库包含全部源码与文档，**不含任何项目数据与密钥**。
