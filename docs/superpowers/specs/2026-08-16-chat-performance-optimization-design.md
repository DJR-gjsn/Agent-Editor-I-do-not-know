# 优化设计方案：LLM 聊天性能与稳定性（方案 B）

日期: 2026-08-16
状态: 已批准（用户确认方案 B）

## 背景与目标

用户反馈两个主要痛点：
1. **LLM 响应慢/卡顿** — 流式输出时前端逐 token 全量重渲染导致界面卡顿；工具链失控时无法中断
2. **代码难维护** — `server.py` 887 行，核心 `/api/chat` 路由内联

优先级：性能与稳定性优先，附带低风险结构重构。

## 诊断结论

| 问题 | 位置 | 影响 |
|---|---|---|
| 逐 token 全量 DOM 重写 + 强制滚动 | `static/chat.js` `onData`/`onReasoning`、`scrollToBottom()` | 长回复明显卡顿（布局抖动） |
| 无取消/停止机制 | `chat.js` `sendMessage` 无 AbortController | 工具循环（最多 50 轮）失控时只能干等 |
| 工具执行无超时 | `modules/tool_registry.py` `execute()` | 慢工具无限阻塞当前轮次 |
| SSE 长空闲无心跳 | `server.py` `generate()` | 代理/浏览器可能中断长工具链连接 |
| 核心路由内联在 server.py | `server.py` L247-446 | 维护困难 |

已确认无需修改：web_search 已并行引擎搜索；重型依赖已懒加载；静态资源已有 5 分钟缓存 + ETag。

## 设计方案

### 1. 前端流式渲染优化（`static/chat.js`）
- rAF 批量渲染：`onData`/`onReasoning` 累积增量，`requestAnimationFrame` 每帧合并渲染一次
- 智能滚动：仅当用户位于底部附近时自动滚动，向上翻阅历史时不强行拉回

### 2. 停止生成按钮 + 取消机制（`templates/chat.html`、`static/chat.js`、`static/common.js`）
- 发送后显示"⏹ 停止"按钮；点击调用 `AbortController.abort()` 终止 fetch 流
- 已生成内容保留在气泡中；客户端断开时后端生成器自动关闭

### 3. 工具执行超时保护（`modules/tool_registry.py`、`modules/llm_client.py`、`modules/config.py`）
- `execute(name, args, timeout=None)` 新增超时参数，模块级共享 `ThreadPoolExecutor`
- `llm_client.py` 工具调用传入超时（默认 180s，配置项 `TOOL_TIMEOUT`）
- 超时返回"工具执行超时"结果，LLM 可据此恢复

### 4. SSE 心跳（`server.py` `generate()`）
- 流空闲超过 15 秒发送 `: keep-alive` 注释帧，防止连接被判定超时

### 5. 结构重构：抽取 `/api/chat`（新建 `modules/chat_routes.py`）
- 迁移：`/api/chat` 路由、`_inject_system_prompt`、`_smart_skills_cache`、`_activated_skills`、`USE_SKILL_DEFINITION`、`_exec_use_skill`、`tool_registry.register("use_skill", ...)`
- 新模块导出 `register_chat_routes(app, http_session, cfg)`
- 纯移动不改行为；`server.py` 从 887 行降到约 550 行

## 验证计划

1. 重构前后跑 `test_all_components.py` 等现有测试，确认无回归
2. 启动服务器实测：页面加载、错误路径 SSE（无 Key 快速返回错误）、停止按钮、超时保护
3. 浏览器手动验收：流式输出流畅度、停止功能、滚动行为

## 明确不做（避免范围蔓延）

- web_search.py（1611 行）拆分
- app.js（376KB）模块化
- UI 视觉翻新
- 静态缓存调整（已有 5 分钟缓存）
