# 会话摘要 — Agent Editor (wybzd) 项目状态

> 生成于 2026-08-16 会话结束。上下文压缩后以此文件为准恢复。

## 项目位置与环境

- **项目根目录**: `D:\myxiangfa-MCPxuexi`
- **技术栈**: Python 3.14.6 + Flask 3.1.3 + 原生 JS（无构建工具）+ stdlib unittest
- **启动方式**: `python server.py`（端口 5000，当前**已关闭**）
- **访问地址**: http://localhost:5000（**必须用 localhost 而非 127.0.0.1**，否则 localStorage 配置不共享——用户踩过这个坑）
- **浏览器**: 技能配置/API 配置在 localStorage（`active-llm-config`、`dashboard-layout`）

## Git 状态（23 个提交，工作区干净）

- **分支**: main；**remote**: https://github.com/DJR-gjsn/Agent-Editor-I-do-not-know（公开，已同步）
- **本地提交与 GitHub 同步**（force push 后一致，以后正常 push 即可）
- **重要安全措施**:
  - 历史密钥已用 filter-branch 清除（曾入历史的 DeepSeek key 已擦除，勿再写入）
  - 项目 apiKey 已清空；`app.js serializeComponent` 白名单化，**不再持久化 apiKey**
  - `.gitignore` 排除: build/, dist/, __pycache__/, *.xlsx, *.log, *.bak, .claude/, .superpowers/, data/memories/, data/projects/*.json, data/storage_config.json, baidu_debug.json
  - 测试脚本密钥改为 `os.environ.get("LLM_API_KEY", "")` 读取
- **待办（用户确认事项）**: 用户被建议轮换 DeepSeek API 密钥（原 key `sk-f007...` 仍在使用，未轮换；测试临时注入过该 key，勿写入任何文件）

## 已完成的主要工作（按提交）

### 性能与稳定性优化
1. **工具执行超时保护** (`f5eade8`): tool_registry.execute() 支持 timeout，共享 ThreadPoolExecutor(8)，超时返回提示；`tool_timeout` 配置（支持小数）
2. **SSE 空闲心跳** (`5a4367a`): utils.with_heartbeat() 泵线程+队列，空闲 15s 发 `: keep-alive`
3. **前端 rAF 渲染** (`0d16f7d`): chat.js pendingDelta/rafId 批量渲染 + isNearBottom() 智能滚动
4. **停止按钮** (`51bec04`): chat.html #btn-stop + AbortController + common.js readSSEStream onAbort
5. **抽取 /api/chat** (`d3855c6`): server.py 887→596 行，迁至 modules/chat_routes.py (register_chat_routes)
6. **修复波** (`3355abc`): 线程上下文配置传递（utils.set/get_request_api_config + tool_registry request_config）、断开中止流（hb_events.close + _safe_close）、停止气泡显示、死导入清理
7. **延期项** (`7b77062`): tool_timeout 支持小数、线程池饱和快速失败（繁忙提示）、智能模式缓存加锁

### 测试
8. **自动测试脚本** (`2ffaca5` + `7342645`): test_components_auto.py — 基于真实连线的全组件测试，输出 Excel
9. **全量测试结果**: 参考项目 proj_b3f7d16fb5（48 组件）: **45 PASS / 3 WARN / 0 FAIL / 0 SKIP**
   - WARN: mcp_database（未配 SQLite 路径）、mcp_email（未配 SMTP）、mcp_navigation（OSRM 不支持地点搜索）——均为配置缺失非故障
   - Excel: `component_status_report.xlsx`（48 行）；JSON: `test_all_results.json`
   - 测试需真实 key（脚本自动读项目 apiSettings 或 LLM_API_KEY）

### 新功能
10. **通用工具集** (`efed48a`): modules/mcp_utility.py — 8 工具（zip_create/zip_extract/http_request/screenshot/image_info/image_convert/image_resize/image_compress）+ 编辑器 3 组件（mcp_zip/http_request/image_tools，已加到 index.html 面板"工具能力"区）
11. **GitHub 发布**: README.md（中英双语简介）、项目名翻译 Agent Editor、favicon、仓库描述/标签（9 个，openai 未加）

### 数据安全
12. **合并保护** (`e7fbf8f`): server.py _merge_layout — 自动保存携带空历史时保留已有对话记录
13. **项目历史清空**: 5 个项目 JSON 的 messages/searchHistory 等历史字段已清空（保留拓扑+apiSettings）；data/projects/ 已移出 git

## 文件结构要点

- `server.py` (631 行): Flask 入口、/api/projects（含 _merge_layout）、/api/memory、静态路由
- `modules/chat_routes.py`: /api/chat SSE + 智能模式（use_skill + _smart_skills_cache + _activated_skills，加锁）
- `modules/mcp_utility.py`: 8 个通用工具
- `modules/utils.py`: with_heartbeat、set/get_request_api_config、safe_path、SSE 辅助
- `modules/tool_registry.py`: execute(name, args, timeout, request_config)、饱和检测
- `static/app.js` (~7660 行): 编辑器（COMPONENT_DEFS/TOOL_NAME_MAP/COMPONENT_CATEGORIES/serializeComponent 不含 apiKey）
- `static/chat.js`/`common.js`: 对话页 + rAF + AbortController + MemoryPanel（K 显示 formatTokens）
- `tests/`: 9 个测试文件（34 个测试，`python -m unittest discover -s tests -v` 全绿）
- `templates/index.html`: 编辑器面板（**新增 3 个工具条目在"工具能力"区**）

## 已知待办/注意

- DeepSeek key 未轮换（建议用户重置；服务器无 LLM_API_KEY 环境变量）
- GitHub 仓库描述/标签：9 个标签已生效，`openai` 缺失（用户可选补）
- 3 个 WARN 组件需配置才能完整使用
- 本地提交 push 前先 fetch（远程与本地已同步，正常 push 即可）

## 常用命令

```powershell
cd D:\myxiangfa-MCPxuexi
python server.py                          # 启动服务器（端口 5000）
python -m unittest discover -s tests -v   # 单元测试（34 个）
$env:LLM_API_KEY="sk-xxx"; python test_components_auto.py data/projects/proj_b3f7d16fb5.json  # 全组件测试
git push                                  # 推送到 GitHub（已同步）
```
