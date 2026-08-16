# 聊天性能与稳定性优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消除 LLM 流式输出的前端卡顿、增加停止/超时机制，并把 `/api/chat` 从 server.py 抽取到独立模块。

**Architecture:** 前端用 requestAnimationFrame 批量渲染 + AbortController 停止；后端工具执行加超时保护（共享线程池）、SSE 空闲心跳；`/api/chat` 路由整体迁移到 `modules/chat_routes.py`（纯移动，不改行为）。

**Tech Stack:** Python 3.14 / Flask 3.1 / 原生 JS（无构建工具）/ stdlib `unittest`（不新增依赖）

## Global Constraints

- 运行环境: Python 3.14.6, Flask 3.1.3（项目根 `D:\myxiangfa-MCPxuexi`）
- 项目**无 git 仓库**：每项修改前用 `Copy-Item <file> <file>.bak` 备份，不执行 commit 步骤
- 测试用 stdlib `unittest`（pytest 未安装且不引入新依赖）：`python -m unittest discover -s tests -v`（需在项目根运行）
- 后端修改后必须重启服务器进程（kill 旧 job 再 `python server.py`）验证
- 前端无 JS 测试设施：Task 3/4 以浏览器手动验收为准
- 所有改动必须保持现有 API 兼容（`/api/chat` 的 SSE 事件格式不变）

---

### Task 1: 工具执行超时保护

**Files:**
- Modify: `modules/config.py`（新增 `tool_timeout` 配置）
- Modify: `modules/tool_registry.py`（`execute` 支持超时）
- Modify: `modules/llm_client.py`（工具调用传入超时）
- Create: `tests/test_tool_timeout.py`
- Backup: `modules/tool_registry.py` → `tool_registry.py.bak`、`modules/llm_client.py` → `llm_client.py.bak`

**Interfaces:**
- Produces: `tool_registry.execute(name: str, args: dict, timeout: float | None = None) -> str` — 超时返回含"超时"的结果字符串；`get_config()["tool_timeout"]` 默认 180

- [ ] **Step 1: 备份待改文件**

```powershell
Copy-Item modules\tool_registry.py modules\tool_registry.py.bak
Copy-Item modules\llm_client.py modules\llm_client.py.bak
```

- [ ] **Step 2: 写失败测试** `tests/test_tool_timeout.py`

```python
"""工具执行超时保护测试"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules import tool_registry


class TestToolTimeout(unittest.TestCase):
    def test_timeout_returns_message(self):
        def slow(args):
            time.sleep(5)
            return "done"
        tool_registry.register("_test_slow", {"name": "_test_slow"}, slow)
        try:
            t0 = time.time()
            result = tool_registry.execute("_test_slow", {}, timeout=0.5)
            elapsed = time.time() - t0
            self.assertIn("超时", result)
            self.assertLess(elapsed, 3, "超时应快速返回而非等待工具完成")
        finally:
            tool_registry.unregister("_test_slow")

    def test_normal_execution_returns_result(self):
        def fast(args):
            return "ok:" + str(args.get("x"))
        tool_registry.register("_test_fast", {"name": "_test_fast"}, fast)
        try:
            self.assertEqual(tool_registry.execute("_test_fast", {"x": 1}), "ok:1")
        finally:
            tool_registry.unregister("_test_fast")

    def test_unknown_tool(self):
        self.assertIn("未知工具", tool_registry.execute("_no_such_tool", {}))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: 运行确认失败**

Run: `python -m unittest tests.test_tool_timeout -v`
Expected: `test_timeout_returns_message` FAIL（当前 `execute` 无 timeout 参数，TypeError）

- [ ] **Step 4: 实现超时保护** `modules/config.py`

在 `_DEFAULTS` 增加一行 `"tool_timeout": 180,`；`_ENV_MAP` 增加 `"LLM_TOOL_TIMEOUT": "tool_timeout",`；`_INT_KEYS` 改为 `{"max_tokens", "port", "tool_timeout"}`。

- [ ] **Step 5: 实现超时保护** `modules/tool_registry.py`

在文件顶部 `import threading` 后追加：

```python
import concurrent.futures

_executor = concurrent.futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix="tool")
```

将 `execute` 替换为：

```python
def execute(name: str, args: dict, timeout: float = None) -> str:
    """执行指定工具，返回结果字符串。timeout 不为 None 时限制执行时长，超时返回提示。"""
    with _lock:
        tool = _tools.get(name)
    if not tool:
        return f"错误: 未知工具 '{name}'"
    try:
        if timeout is None:
            return str(tool["executor"](args))
        future = _executor.submit(tool["executor"], args)
        try:
            return str(future.result(timeout=timeout))
        except concurrent.futures.TimeoutError:
            return f"工具执行超时（超过 {timeout} 秒），请简化请求或稍后重试"
    except Exception as e:
        return f"工具执行错误: {str(e)}"
```

- [ ] **Step 6: 让 llm_client 传入超时** `modules/llm_client.py`

两处工具执行（流式模式 L201、非流式模式 L255）：

```python
result = tool_registry.execute(tc["name"], tool_args, timeout=cfg["tool_timeout"])
```

（`cfg` 在函数开头已通过 `get_config()` 获取；非流式模式变量名为 `tool_name`、`tool_args`，保持原样只加第三个参数。）

- [ ] **Step 7: 运行测试确认通过**

Run: `python -m unittest tests.test_tool_timeout -v`
Expected: 3 个测试全部 PASS

- [ ] **Step 8: 全量回归**

Run: `python -m unittest discover -s tests -v`（确认现有测试无回归；随后任务逐步新增）

- [ ] **Step 9: 重启服务器验证**

```powershell
# kill 旧后台 job（pwsh-1）后重新启动
python server.py   # run_in_background
```
Expected: 启动日志正常，`/api/health` 返回 200

---

### Task 2: SSE 空闲心跳

**Files:**
- Modify: `modules/utils.py`（新增 `with_heartbeat` 生成器包装器）
- Modify: `server.py`（`generate()` 使用心跳包装，发送 `: keep-alive` 帧）
- Create: `tests/test_sse_heartbeat.py`

**Interfaces:**
- Produces: `with_heartbeat(events, idle_seconds=15.0) -> Generator[(str, object)]` — 每个元素为 `("event", ev)` 或 `("heartbeat", None)`；`server.py` 的 `generate()` 内将 `("heartbeat", None)` 映射为 `yield ": keep-alive\n\n"`

- [ ] **Step 1: 写失败测试** `tests/test_sse_heartbeat.py`

```python
"""SSE 空闲心跳测试"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.utils import with_heartbeat


class TestHeartbeat(unittest.TestCase):
    def test_heartbeat_emitted_when_idle(self):
        def slow_events():
            yield {"type": "content", "content": "a"}
            time.sleep(0.4)
            yield {"type": "content", "content": "b"}
        items = list(with_heartbeat(slow_events(), idle_seconds=0.2))
        kinds = [k for k, _ in items]
        self.assertIn("heartbeat", kinds)
        self.assertIn("event", kinds)
        self.assertEqual([k for k, _ in items if k == "event"], ["event", "event"])

    def test_no_heartbeat_when_fast(self):
        def fast_events():
            yield {"type": "content", "content": "x"}
        items = list(with_heartbeat(fast_events(), idle_seconds=0.2))
        kinds = [k for k, _ in items]
        self.assertNotIn("heartbeat", kinds)

    def test_event_order_preserved(self):
        def seq():
            for i in range(5):
                yield {"type": "content", "content": str(i)}
                time.sleep(0.05)
        contents = [p["content"] for k, p in with_heartbeat(seq(), idle_seconds=0.1) if k == "event"]
        self.assertEqual(contents, ["0", "1", "2", "3", "4"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m unittest tests.test_sse_heartbeat -v`
Expected: `ImportError: cannot import name 'with_heartbeat'`

- [ ] **Step 3: 实现 `with_heartbeat`** `modules/utils.py`

在文件末尾追加：

```python
def with_heartbeat(events, idle_seconds: float = 15.0):
    """
    包装事件生成器：事件流空闲超过 idle_seconds 时产出 ("heartbeat", None)，
    其余情况原样产出 ("event", event)。用于 SSE 长连接保活。
    内部用 daemon 泵线程 + 队列实现空闲检测；生成器被关闭（GeneratorExit）
    时会通知泵线程退出，避免线程泄漏。
    """
    import queue
    import threading

    q = queue.Queue(maxsize=16)
    stop = threading.Event()

    def _pump():
        try:
            for ev in events:
                while not stop.is_set():
                    try:
                        q.put(("event", ev), timeout=0.2)
                        break
                    except queue.Full:
                        continue
                else:
                    return
            q.put(("done", None))
        except Exception as exc:
            try:
                q.put(("error", exc))
            except Exception:
                pass

    t = threading.Thread(target=_pump, daemon=True)
    t.start()
    try:
        while True:
            try:
                kind, payload = q.get(timeout=idle_seconds)
            except queue.Empty:
                yield ("heartbeat", None)
                continue
            if kind == "done":
                return
            if kind == "error":
                raise payload
            yield (kind, payload)
    except GeneratorExit:
        stop.set()
        raise
```

- [ ] **Step 4: 接入 server.py 的 `generate()`**

将 `generate()` 开头的 `events = chat_with_tools(...)` 之后、`for event in events:` 之前，改为：

```python
        from modules.utils import with_heartbeat
        hb_events = with_heartbeat(events, idle_seconds=15)
        for hb_kind, hb_payload in hb_events:
            if hb_kind == "heartbeat":
                yield ": keep-alive\n\n"
                continue
            event = hb_payload
```

（后续 `etype = event["type"]` 等逻辑保持不变，事件变量名仍为 `event`。）

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m unittest tests.test_sse_heartbeat -v`
Expected: 3 个测试全部 PASS

- [ ] **Step 6: 全量回归 + 重启服务器**

Run: `python -m unittest discover -s tests -v`；重启服务器后 POST `/api/chat` 冒烟（无 Key 时应快速返回 SSE 错误事件而非挂起）

---

### Task 3: 前端流式渲染优化（rAF 批量渲染 + 智能滚动）

**Files:**
- Modify: `static/chat.js`（`sendMessage` 中 `onData`/`onReasoning` 回调、新增 `isNearBottom`）
- Backup: `static/chat.js` → `static/chat.js.bak`

**Interfaces:**
- Produces: 全局函数 `isNearBottom() -> boolean`（距底部 < 80px 判定）；`sendMessage` 内部维护 `pendingDelta`/`rafId` 状态
- 无自动测试设施，验收方式：浏览器手动验证

- [ ] **Step 1: 备份**

```powershell
Copy-Item static\chat.js static\chat.js.bak
```

- [ ] **Step 2: 新增智能滚动函数** `static/chat.js`

在 `function scrollToBottom()` 定义旁（L404）追加：

```js
function isNearBottom() {
    return chatMessages.scrollHeight - chatMessages.scrollTop - chatMessages.clientHeight < 80;
}
```

- [ ] **Step 3: 改造 `sendMessage` 的渲染回调**

在 `sendMessage` 的 `try` 块内、`await readSSEStream(...)` 之前（约 L474 `const toolEvents = [];` 处）新增状态：

```js
        // rAF 批量渲染状态：累积增量，每帧合并渲染一次
        let pendingDelta = '';
        let rafId = null;
        const renderAI = () => {
            rafId = null;
            if (pendingDelta) {
                fullContent += pendingDelta;
                pendingDelta = '';
                aiBubble.textContent = fullContent;
                if (isNearBottom()) scrollToBottom();
            }
        };
        let pendingReasoning = '';
        let rafReasoningId = null;
        const renderReasoning = () => {
            rafReasoningId = null;
            if (pendingReasoning) {
                reasoningContent += pendingReasoning;
                pendingReasoning = '';
                thinkingWrapper.style.display = 'block';
                const body = thinkingWrapper.querySelector('.thinking-body');
                if (body) body.textContent = reasoningContent;
                if (isNearBottom()) scrollToBottom();
            }
        };
```

将 `onReasoning` 回调替换为：

```js
            onReasoning(delta) {
                pendingReasoning += delta;
                if (rafReasoningId === null) rafReasoningId = requestAnimationFrame(renderReasoning);
            },
```

将 `onData` 回调替换为：

```js
            onData(delta) {
                pendingDelta += delta;
                aiBubble.classList.add('typing-cursor');
                if (rafId === null) rafId = requestAnimationFrame(renderAI);
            },
```

- [ ] **Step 4: 清理待渲染状态**

在 `await readSSEStream(...)` 之后（`aiBubble.classList.remove('typing-cursor')` 处）追加：

```js
        if (rafId !== null) { cancelAnimationFrame(rafId); renderAI(); }
        if (rafReasoningId !== null) { cancelAnimationFrame(rafReasoningId); renderReasoning(); }
```

（确保流结束时未刷新的增量全部落盘。）

- [ ] **Step 5: 浏览器验收**

刷新 `http://127.0.0.1:5000/chat`：
1. 发送长回复请求（可用真实 Key 或直接观察错误路径），输出过程中拖动滚动条到中部 → 不应被强制拉回底部
2. 输出全程 UI 无逐字抖动（肉眼对比优化前）

---

### Task 4: 停止生成按钮 + AbortController

**Files:**
- Modify: `templates/chat.html`（新增停止按钮）
- Modify: `static/chat.js`（AbortController 集成）
- Modify: `static/common.js`（`readSSEStream` 支持 onAbort）

**Interfaces:**
- Consumes: `readSSEStream(response, callbacks)` — callbacks 新增可选 `onAbort()`
- Produces: `sendMessage` 内 `abortController` 模块级变量；`btn-stop` 按钮 id

- [ ] **Step 1: chat.html 新增停止按钮**

在输入栏（`<button id="btn-send" class="llm-send-btn">发送</button>`，templates/chat.html L159）前插入：

```html
                <button id="btn-stop" class="llm-send-btn" style="display:none;background:#e74c3c;" title="停止生成">⏹ 停止</button>
```

- [ ] **Step 2: common.js 的 `readSSEStream` 支持中止**

在 `readSSEStream` 开头解构处（L66）改为：

```js
    const { onData, onReasoning, onToolCall, onToolResult, onError, onAbort } = callbacks || {};
```

在 catch 块（L122-125）改为：

```js
    } catch (e) {
        if (e.name === 'AbortError') {
            if (onAbort) onAbort();
            return { done: true, aborted: true };
        }
        if (onError) onError(e.message);
        return { done: true, error: e.message };
    }
```

- [ ] **Step 3: chat.js 集成 AbortController**

在 `const btnClear = document.getElementById('btn-clear-chat');`（L34）后追加：

```js
const btnStop = document.getElementById('btn-stop');
let abortController = null;   // 当前请求的取消控制器
```

在 `sendMessage` 的 `setInputDisabled(true)`（L435）后追加：

```js
    abortController = new AbortController();
    btnSend.style.display = 'none';
    btnStop.style.display = '';
    btnStop.onclick = () => { if (abortController) abortController.abort(); };
```

fetch 调用（L467-471）增加 signal：

```js
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
            signal: abortController.signal,
        });
```

`await readSSEStream(response, {...})` 的回调对象中增加：

```js
            onAbort() {
                fullContent = fullContent || '（已停止）';
            },
```

将 catch 块（L546-549）改为区分中止：

```js
    } catch (e) {
        if (e.name === 'AbortError') {
            aiBubble.textContent = fullContent || '（已停止）';
            aiBubble.classList.remove('typing-cursor');
        } else {
            aiBubble.textContent = '❌ 请求失败: ' + e.message;
            aiBubble.classList.remove('typing-cursor');
        }
    } finally {
        abortController = null;
        btnStop.style.display = 'none';
        btnSend.style.display = '';
    }
```

- [ ] **Step 4: 浏览器验收**

刷新 `http://127.0.0.1:5000/chat`：
1. 发送请求后"发送"按钮消失、"⏹ 停止"按钮出现
2. 点击停止 → 输出立即终止，已生成内容保留，气泡显示"（已停止）"或已有内容
3. 停止后输入框恢复可用，可再次发送

---

### Task 5: 抽取 `/api/chat` 到 `modules/chat_routes.py`

**Files:**
- Create: `modules/chat_routes.py`（迁移 ~300 行）
- Modify: `server.py`（删除迁移代码，改为调用 `register_chat_routes`）
- Create: `tests/test_chat_route.py`
- Backup: `server.py` → `server.py.bak`

**Interfaces:**
- Produces: `register_chat_routes(app, http_session, cfg)` — 无返回值；`cfg` 为 `get_config()` 结果（含 `api_base/api_key/model/max_tokens/temperature/port` 键）
- Consumes: `tool_registry`、`make_sse_response`、`sse_error`、`sse_done`、`chat_with_tools`（均已有）

- [ ] **Step 1: 备份**

```powershell
Copy-Item server.py server.py.bak
```

- [ ] **Step 2: 创建 `modules/chat_routes.py`**

文件头部：

```python
"""
聊天路由模块 — /api/chat SSE 流式接口
从 server.py 抽取，职责：LLM 对话 + 智能模式技能激活 + 工具调用循环
"""

import json
import threading
import time

from flask import g, request

from . import tool_registry
from .config import get_config
from .llm_client import chat_with_tools
from .utils import make_sse_response, sse_error, sse_done
```

迁移以下内容（从 server.py 原样拷贝，仅调整作用域）：
1. `_smart_skills_cache` / `_skills_cache_lock` / `_activated_skills`（L37-61）
2. `USE_SKILL_DEFINITION` 与 `_exec_use_skill`，以及 `tool_registry.register("use_skill", ...)`（L40-105）
3. `_inject_system_prompt`（L193-205）
4. `chat()` 路由及其 `generate()`（L247-446），签名改为 `def chat():`，内部引用改为：
   - `API_BASE` → `_cfg["api_base"]`、`API_KEY` → `_cfg["api_key"]`、`MODEL` → `_cfg["model"]`、`MAX_TOKENS` → `_cfg["max_tokens"]`、`TEMPERATURE` → `_cfg["temperature"]`
   - `logger` → 模块内 `logging.getLogger("wybzd")`
   - `http_session`、`_cfg`、`tool_registry`、`make_sse_response` 等通过闭包或模块引用
5. 注册函数：

```python
def register_chat_routes(app, http_session, cfg):
    """注册 /api/chat 路由。http_session: 共享 HTTP Session；cfg: get_config() 结果"""
    global _cfg
    _cfg = cfg

    @app.route("/api/chat", methods=["POST"])
    def chat():
        # ... 迁移后的完整路由实现（使用闭包中的 http_session / _cfg / app） ...
        return make_sse_response(generate())

    return app
```

（实现时把 `chat` 函数体定义为 `register_chat_routes` 内部闭包，保证能访问 `http_session` 与 `_cfg`；`g._api_config` 注入逻辑保持不变。）

- [ ] **Step 3: server.py 接入新模块**

删除 server.py 中 L26 `from modules.llm_client import chat_with_tools`、L37-105（智能模式缓存 + use_skill 定义）、L193-205（`_inject_system_prompt`）、L247-446（`/api/chat` 路由）。保留 `from modules.utils import make_sse_response, sse_event, sse_error, sse_done, setup_logging, get_logger`（其他路由仍用）。

在 `register_all(app)` 之后（L31 附近）追加：

```python
# 聊天路由（SSE 流式对话）
from modules.chat_routes import register_chat_routes
register_chat_routes(app, http_session, _cfg)
```

（`http_session` 在 server.py 顶部已有定义；若 `register_all` 内部创建的 session 未被引用，则按 `modules/__init__.py` 中 `app._http_session` 的方式获取：`http_session = getattr(app, "_http_session", None)`，不存在则新建。）

- [ ] **Step 4: 写冒烟测试** `tests/test_chat_route.py`

```python
"""/api/chat 路由冒烟测试（不依赖真实 LLM API）"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server  # noqa: F401  (导入即注册所有路由)


class TestChatRoute(unittest.TestCase):
    def setUp(self):
        server.app.config["TESTING"] = True
        self.client = server.app.test_client()

    def test_route_registered(self):
        rules = {str(r) for r in server.app.url_map.iter_rules()}
        self.assertIn("/api/chat", rules)

    def test_chat_returns_sse_stream(self):
        # api_base 指向不可达地址 → 立即 ConnectionError → SSE 错误事件
        resp = self.client.post("/api/chat", json={
            "messages": [{"role": "user", "content": "hi"}],
            "api_base": "http://127.0.0.1:1",
            "max_tool_rounds": 1,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/event-stream", resp.content_type)
        body = resp.get_data(as_text=True)
        self.assertIn("data:", body)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m unittest tests.test_chat_route -v`
Expected: 2 个测试 PASS（若 `test_chat_returns_sse_stream` 超时，说明迁移后 generate() 有死循环/未返回问题，检查闭包变量）

- [ ] **Step 6: 全量回归 + 重启验证**

Run: `python -m unittest discover -s tests -v`；重启服务器，浏览器访问 `/chat` 发送一条消息（真实 Key 时）确认流式输出与工具调用行为与优化前一致

---

### Task 6: 收尾清理

- [ ] **Step 1: 全量测试**

Run: `python -m unittest discover -s tests -v`
Expected: 全部 PASS（`test_tool_timeout` 3 项 + `test_sse_heartbeat` 3 项 + `test_chat_route` 2 项）

- [ ] **Step 2: 手动回归服务器**

重启服务器，验证：
1. `http://127.0.0.1:5000/` 管理后台、`/editor`、`/chat`、`/projects` 均正常加载
2. `/api/health` 200；`/api/tools/definitions` 返回工具列表
3. `/api/chat` 无 Key 时快速返回 SSE 错误（不挂起）
4. 聊天页：流式输出流畅、停止按钮可用、滚动行为正确

- [ ] **Step 3: 确认备份可删**

确认所有改动验证通过后，删除 `*.bak` 备份文件（`modules/tool_registry.py.bak`、`modules/llm_client.py.bak`、`static/chat.js.bak`、`server.py.bak`）
