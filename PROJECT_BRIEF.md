# Agent Editor 项目简报（新对话交接用）

> 把本文件内容粘贴到新对话开头即可继续协作。项目位于 `D:\myxiangfa-MCPxuexi`。

## 一、项目是什么

**Agent Editor (wybzd)** — 可视化 AI Agent 搭建与对话平台。拖拽连线组合 LLM/工具/编排/技能组件，生成可交互工作流，带 SSE 流式对话页。

- 技术栈：**Python 3.14 + Flask 3.1 + 原生 JS（无构建工具）+ stdlib unittest**
- 启动：`python server.py`（端口 5000），双击 `StartServer.bat` / `StopServer.bat` 也可
- 访问：**http://localhost:5000**（必须 localhost，勿用 127.0.0.1——localStorage 独立导致技能配置"消失"）
- 页面：`/` 后台 · `/editor` 编辑器 · `/chat` 对话 · `/projects` 项目管理

## 二、核心结构

```
server.py                  Flask 入口（登录保护 before_request/项目/记忆/静态路由 + _merge_layout）
modules/                   50 个模块
  db.py                    SQLite 连接层（users/sessions/user_settings，线程本地连接）
  auth.py                  注册/登录/登出/me + 用户设置 CRUD（werkzeug 哈希、会话滑动续期）
  meta.py                  前端元数据单一来源（组件定义/renderKey/工具映射/模板/厂商/设置）
  orchestrator.py          编排链（布局→工具注入含中介链→payload）
  chat_routes.py           /api/chat SSE + 智能模式（use_skill）
  llm_client.py            tool-call 循环（超时保护、request_config 线程传递）
  tool_registry.py         execute(name,args,timeout,request_config) + 饱和检测
  utils.py                 with_heartbeat / set|get_request_api_config / safe_path / SSE
  mcp_utility.py           压缩/HTTP/截图/图片 8 工具
  vector_memory.py         向量库（documents/import-file/search/stats 路由）
  mcp_*.py                 各工具模块（office/weather/translate/git 等）
static/
  app.js (7176行，前端轻量化重构后)  编辑器（COMPONENT_DEFS/TOOL_NAME_MAP/连线规则/框选/模板/设置面板）
  chat.js / common.js      对话页（rAF 渲染、AbortController、MemoryPanel K 格式）
templates/index.html       编辑器（含 56 组件面板条目 + 设置面板 + 快速模板按钮）
docs/                      USAGE.md 使用说明 + 组件功能清单.xlsx + 测试报告.xlsx
tests/                     15 个测试文件（127 个测试，全部通过）
```

## 三、已实现功能（最新）

1. **性能优化**：工具超时保护（180s 线程池+饱和快失败）、SSE 心跳、前端 rAF 渲染、停止按钮、chat 路由抽取
2. **新组件**：压缩工具 / HTTP 请求 / 图片工具（mcp_zip/http_request/image_tools）、**知识库**（导入 txt/md/csv/json/pdf/docx/xlsx，仅连 Vector Memory，自动命名 知识库1/2 可改名）、**Token 计数器**（仅连 LLM，对话页显示用量）
3. **编辑器增强**：**框选**（整组移动/Delete 批量删/Ctrl 多选）、快速模板 11 个（含技能智能模式链路）、设置面板（主题/字体大小/行距滑块，正方形面板）、厂商模型预设更新（GPT-5/GLM-5/Qwen3.8/Kimi-K3 等）
4. **安全**：密钥不入库（serializeComponent 白名单）、git 历史已 filter-branch 清密钥、.gitignore 排除项目数据/记忆/测试产物
5. **测试**：test_components_auto.py 全组件测试（48 组件 45 PASS/3 WARN——WARN 是数据库/邮件/导航未配置，非故障）；generate_component_list.py 生成组件清单
6. **向量库持久化**：知识库/向量库落盘到 `data/vector_store/vector_store.json`（原子写 tmp+replace），重启自动恢复；`_next_id` 一并持久化保证 id 不重叠；无有效 API key 时跳过网络 embedding 直接本地向量化（避免 5s 等待）；`init_vector_store(path)` 支持重定向（测试/多实例隔离）；损坏文件容错为空库
7. **外部 MCP 工具**：手写轻量 MCP client（mcp_client.py，stdio+HTTP 双传输、JSON-RPC 2.0）；
   设置面板配置 MCP Servers（data/mcp_config.json，gitignore 排除）；
   工具动态注册进 tool_registry（命名 mcp_ext_<server_id>_<tool>），对话引擎零修改；
   编辑器"外部 MCP 工具"组件：引用 server + 勾选工具子集
8. **登录认证与后端存储**：多用户注册/登录（服务端会话 Cookie、werkzeug 哈希）、SQLite 用户/会话/设置、项目按用户隔离（data/projects/<username>/）、设置多设备同步；docs/database-schema.md + docs/api-contract.md
9. **前端轻量化重构**（三阶段增量，app.js 8401→7176 行，净删 1225）：① 元数据 API 化——`/api/meta/components`（组件定义/renderKey/工具映射/工厂渲染参数 render_args/模板/厂商预设）、`/api/meta/settings`（主题色板/字号/行距滑块），前端启动拉取 + renderKey 本地映射（渲染逻辑永留前端）；② 编排链后端化——`modules/orchestrator.py`（布局→工具注入→payload，含 mcp_external 动态注册名），`/api/chat` 双格式（新 layout+消息 经 orchestrator 编排 / 旧 messages 透传过渡兼容），SSE 事件流两种格式完全一致；③ 收口——AGENT_PRESETS→QUICK_TEMPLATES 迁移、extract_meta 退役、死代码清理、模板拉取失败 toast。行数验收 ≤4000 未达标（见"前端轻量化重构验收记录"）。
10. **Docker 部署**：Dockerfile（python:3.14-slim + waitress 生产服务器）+ docker-compose（端口 5000、`./data` 卷持久化、FLASK_ENV=production）；server.py 的 app.run 加 `__main__` 保护；requirements.txt 补全 18 个功能依赖；已在用户本机构建运行验证（waitress 正常服务、数据持久化双向同步）
11. **账号功能**：设置面板"账号"区（当前用户/改密码/退出登录，`POST /api/auth/change-password` 改密码后其他会话失效）；共享设置面板 settings-panel.js 接入首页/项目管理页（修复首页设置按钮误跳转）；登录落点改为项目首页 /projects；页面与静态资源 no-cache（消除旧页面缓存）

## 四、Git / GitHub

- 88 提交，已与 GitHub 同步：`https://github.com/DJR-gjsn/Agent-Editor-I-do-not-know`（公开，无密钥无项目数据）
- 推送：本机 `cd D:\myxiangfa-MCPxuexi && git push`
- 注意：我的沙箱环境**无法直连 github.com**（git push 只能由用户本机执行；之前用 GitHub API 绕过推送过）

## 五、常用命令

```powershell
cd D:\myxiangfa-MCPxuexi
python server.py                          # 启动
python -m unittest discover -s tests -v   # 单元测试（127 个）
# 首次使用：浏览器打开 http://localhost:5000/login 注册账号并登录（全局登录保护，未登录页面 302、API 401）
$env:LLM_API_KEY="sk-xxx"; python test_components_auto.py data/projects/proj_b3f7d16fb5.json  # 全组件测试
python generate_component_list.py         # 重新生成组件清单 Excel
git push                                  # 推送到 GitHub
```

## 六、注意事项 / 待办

- DeepSeek key（sk-f007...）**未轮换**，用户被建议重置；测试需要真实 key（项目 apiKey 已清空，脚本读 LLM_API_KEY 环境变量）
- 3 个 WARN 组件需配置（SQLite 路径/SMTP/地图 API key）
- 向量库已落盘持久化（`data/vector_store/`，gitignore 排除，不上 GitHub）；多进程并发写同一 store 未做文件锁（单实例使用无影响）
- 编辑器 canvas 用 `zoom` 字体缩放时（非 100%）可能与画布 transform 合成冲突——已做防御
- 历史遗留：_smart_skills_cache 等全局态、双 HTTP Session（评估过可接受）
- `.gitignore` 已从 GBK 重写为 UTF-8（原 GBK 编码错位导致 *.xlsx / data/projects/*.json / .claude/ 等规则失效，已修复并验证）；`data/mcp_config.json`（MCP server 配置，可能含 token）也已加入 .gitignore 排除，仅存本地不上传
- 测试 127 个（42 旧 + 28 MCP：mcp_client 8 + mcp_manager 12 + mcp_routes 8 + 27 认证：db 4 + auth 13 + auth_routes 9 + chat_route 2 + meta 6 + orchestrator 23：直连/中介链/门控/记忆）

## 七、前端轻量化重构验收记录（2026-08-21，Task 6）

- **行数验收（核心指标 app.js ≤4000 行）**：**未达标**。最终 7176 行（重构前基线 commit 51f8152
  为 8401 行，净删 1225）。
  达标性评估：96 个 render 函数（≈3000 行）+ 画布交互/连线/框选（≈1100 行）属"界面外观不变"红线
  必须保留；剔除渲染必需后"业务代码"≈3100 行（状态/序列化/项目保存/设置同步/MCP 管理/模板展开/
  工具收集等，均为功能必需，无冗余数据可后移）。即使业务代码全部清零，剩余 ~4100 行仍 >4000——
  **该指标在保留全部渲染逻辑的前提下不可达**。T6 净删 35 行：工厂渲染参数表 render_args 后移
  meta.py（−31）、重复 findConnectedMemory（−9）、死守卫（−1）、模板失败 toast（+2）。剩余可瘦身项
  （MCP 面板共享 helper ~40 行、getComponentToolNames 并入 TOOL_NAME_MAP 会改变展示）均触碰渲染/展示
  红线或收益递减，评估后保留。
- **全量回归**：`python -m unittest discover -s tests` → 127 tests OK，exit 0；`node --check` 全部通过。
- **真实服务器冒烟（HTTP/契约级）**：**11/11 通过**（登录/session、/api/meta/components 结构、
  /api/meta/settings、/editor 页 11 模板按钮 + 3 主题、/chat 页、未登录 401、11 模板展开数与 T5
  基准逐一相等、/api/chat 新/旧格式全链、项目往返、render_args 与旧表逐项等值）。**浏览器点击级
  冒烟（拖拽/连线/框选实点）因沙箱环境限制未执行**（Edge 进程启动被沙箱拒绝，crashpad/mojo
  OpenProcess 0x5）——待用户本机验证。
- **中介链已收口（follow-up 完成）**：orchestrator.resolve_tools 现已支持 executor / sequential_executor / agent 三条中介链（单层，端口序收集、toolEnabled 门控、去重/替换语义与前端旧实现对齐，连线源端口双键兼容 sourcePort/sourcePortId）。编辑器内嵌对话（新格式）对中介链下游工具正常注入。已知遗留：①中介提示文本（sequential 顺序约束）未注入 prompt（前后端均已删 hint 函数，顺序语义仅靠有序 tools 数组体现）；②下游工具 toolEnabled 门控为后端超集（前端面板展示未同步）；③多跳中介（executor→agent）前端从未支持。
- **契约文档**：docs/api-contract.md 已补 /api/meta/components、/api/meta/settings、/api/chat 双格式 + SSE 契约。
- **遗留项**：settings 前端接线评估为"后续项"（数据无样式信息，接线收益低）；getComponentToolNames
  保留并记录（统一会为 11 项之外的 13 类工具新增展示，违反外观不变）。
