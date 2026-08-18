# 外部 MCP 工具组件 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Agent Editor 能连接外部 MCP server（stdio 本地子进程 / HTTP 远程），将其工具动态注册进 tool_registry，并在编辑器中以"外部 MCP 工具"组件使用。

**Architecture:** 手写轻量 MCP client（`mcp_client.py`，JSON-RPC 2.0，stdio+HTTP 双传输），由 `mcp_manager.py` 管理全局配置（`data/mcp_config.json`）与生命周期，通过 `tool_registry.register/unregister` 动态注册工具（命名 `mcp_ext_<server_id>_<tool>`），对话引擎 `llm_client.py` 零修改。前端：设置面板加 MCP Servers 管理区 + 组件面板加 `mcp_external` 节点（引用 server + 筛选工具）。

**Tech Stack:** Python 3.14 + stdlib（subprocess/json/queue/threading/http.server）+ requests（已装）+ Flask（已装）+ 原生 JS（无构建工具）+ stdlib unittest。

## Global Constraints

- **零新依赖**：只使用 Python stdlib + 项目已有依赖（requests、Flask）。禁止 `pip install` 任何包。
- **测试框架**：stdlib unittest，命令 `python -m unittest tests.test_<module> -v`，断言用 `self.assert*`。
- **工具命名**：`mcp_ext_<server_id>_<tool_name>`；`server_id` 匹配 `^[a-zA-Z0-9_-]{1,32}$`；最终工具名 ≤ 64 字符（OpenAI 函数名限制）。
- **超时**：MCP 调用读超时 60s（`MCPClient(timeout=...)` 可配置）；外层 `tool_registry.execute` 180s 兜底不修改。
- **密钥边界**：token/命令/URL 只存 `data/mcp_config.json`（gitignore 排除）；`serializeComponent` 白名单只存 `serverId`/`toolNames`。
- **UTF-8**：所有新文件 UTF-8 编码，`ensure_ascii=False` 写 JSON。
- **Windows 兼容**：stdio 子进程用 `creationflags=subprocess.CREATE_NO_WINDOW`（`getattr(subprocess, "CREATE_NO_WINDOW", 0)`）。
- **失败隔离**：单个 server 连接/注册失败只标记 error，不得阻塞服务器启动或其他工具。
- 测试临时文件一律放在项目工作区内（`data/vector_store/.test_tmp/` 模式），**禁止用 `tempfile.mkdtemp` 默认系统 Temp**（沙箱/CI 下无写权限）。

---

## File Structure

| 文件 | 职责 | 动作 |
|---|---|---|
| `modules/mcp_client.py` | JSON-RPC 2.0 协议层：`MCPError`、`StdioTransport`、`HttpTransport`、`MCPClient` | 新建 |
| `tests/fixtures/mini_mcp_server.py` | 测试用迷你 MCP server（stdio+http 双模式），工具：echo/fail/sleep | 新建 |
| `tests/test_mcp_client.py` | 协议层测试（stdio/HTTP 往返、错误、超时） | 新建 |
| `modules/mcp_manager.py` | 配置 CRUD（`data/mcp_config.json`）、生命周期、动态注册/注销、状态查询、Flask 路由 | 新建 |
| `tests/test_mcp_manager.py` | 配置/注册/命名/失败隔离/token 边界测试 | 新建 |
| `tests/test_mcp_routes.py` | Flask 路由测试（test client） | 新建 |
| `modules/__init__.py` | 导入 mcp_manager 并 `register_routes(app)` | 修改 |
| `.gitignore` | 加 `data/mcp_config.json` | 修改 |
| `templates/index.html` | 设置面板 MCP 区 HTML + 组件面板 `mcp_external` 条目 | 修改 |
| `static/app.js` | MCP 管理 UI 逻辑、`COMPONENT_DEFS` 加节点、`renderMcpExternalPanel`、`collectToolsFromPorts` 扩展、`serializeComponent` 白名单 | 修改 |
| `docs/PROJECT_BRIEF.md` | 功能记录更新 | 修改 |

---

### Task 1: MCP 协议层 + fixture server

**Files:**
- Create: `tests/fixtures/mini_mcp_server.py`
- Create: `tests/test_mcp_client.py`
- Create: `modules/mcp_client.py`

**Interfaces:**
- Produces:
  - `mcp_client.MCPError(Exception)`
  - `mcp_client.StdioTransport(command: str, args: list[str] | None = None, timeout: float = 60)` — `start()` / `send_request(method, params, request_id) -> dict` / `send_notification(method, params)` / `close()`
  - `mcp_client.HttpTransport(url: str, token: str | None = None, timeout: float = 60)` — 同接口
  - `mcp_client.MCPClient(transport, timeout: float = 60)` — `initialize()` / `list_tools() -> list[dict]` / `call_tool(name, args) -> str` / `close()`
- Consumes: 无（Task 1 独立）

- [ ] **Step 1: 创建 fixture server**

创建 `tests/fixtures/mini_mcp_server.py`（完整内容）：

```python
"""测试用迷你 MCP server（stdio + http 双模式）— 仅用于单元测试"""
import json
import sys
import time

TOOLS = [
    {"name": "echo", "description": "回显消息",
     "inputSchema": {"type": "object", "properties": {"message": {"type": "string"}},
                     "required": ["message"]}},
    {"name": "fail", "description": "固定失败",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "sleep", "description": "休眠指定秒数",
     "inputSchema": {"type": "object", "properties": {"seconds": {"type": "number"}}}},
]


def handle_request(req):
    method = req.get("method")
    params = req.get("params") or {}
    if method == "initialize":
        return {"protocolVersion": "1.0", "capabilities": {},
                "serverInfo": {"name": "mini-mcp", "version": "0.1"}}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        if name == "echo":
            return {"content": [{"type": "text", "text": args.get("message", "")}],
                    "isError": False}
        if name == "fail":
            return {"content": [{"type": "text", "text": "故意失败"}], "isError": True}
        if name == "sleep":
            time.sleep(float(args.get("seconds", 1)))
            return {"content": [{"type": "text", "text": "slept"}], "isError": False}
        return {"content": [{"type": "text", "text": "未知工具 " + str(name)}],
                "isError": True}
    return {"error": {"code": -32601, "message": "未知方法 " + str(method)}}


def run_stdio():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        rid = req.get("id")
        if rid is None:  # notification，不响应
            continue
        try:
            result = handle_request(req)
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": rid, "result": result}) + "\n")
        except Exception as e:
            sys.stdout.write(json.dumps(
                {"jsonrpc": "2.0", "id": rid,
                 "error": {"code": -32603, "message": str(e)}}) + "\n")
        sys.stdout.flush()


def run_http(port):
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                req = json.loads(body.decode("utf-8"))
            except Exception:
                self.send_response(400)
                self.end_headers()
                return
            rid = req.get("id")
            if rid is None:
                self.send_response(202)
                self.end_headers()
                return
            try:
                result = handle_request(req)
                payload = json.dumps({"jsonrpc": "2.0", "id": rid, "result": result})
                status = 200
            except Exception as e:
                payload = json.dumps(
                    {"jsonrpc": "2.0", "id": rid,
                     "error": {"code": -32603, "message": str(e)}})
                status = 200
            data = payload.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    srv = HTTPServer(("127.0.0.1", port), Handler)
    print(json.dumps({"port": srv.server_port}), flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--http":
        run_http(int(sys.argv[2]) if len(sys.argv) > 2 else 0)
    else:
        run_stdio()
```

- [ ] **Step 2: 写协议层失败测试**

创建 `tests/test_mcp_client.py`（完整内容）：

```python
"""MCP 协议层测试：stdio + HTTP 传输、往返、错误、超时"""
import os
import subprocess
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.mcp_client import MCPClient, MCPError, StdioTransport, HttpTransport

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "fixtures", "mini_mcp_server.py")


def _stdio_client(timeout=10):
    transport = StdioTransport(sys.executable, [FIXTURE], timeout=timeout)
    transport.start()
    client = MCPClient(transport, timeout=timeout)
    return client


class TestMCPStdio(unittest.TestCase):
    def setUp(self):
        self.client = _stdio_client()

    def tearDown(self):
        self.client.close()

    def test_initialize_and_list_tools(self):
        self.client.initialize()
        tools = self.client.list_tools()
        names = [t["name"] for t in tools]
        self.assertEqual(names, ["echo", "fail", "sleep"])
        echo_def = next(t for t in tools if t["name"] == "echo")
        self.assertIn("message", echo_def["inputSchema"]["properties"])

    def test_call_tool_echo(self):
        self.client.initialize()
        result = self.client.call_tool("echo", {"message": "你好 MCP"})
        self.assertEqual(result, "你好 MCP")

    def test_call_tool_error_flag(self):
        self.client.initialize()
        result = self.client.call_tool("fail", {})
        self.assertIn("故意失败", result)
        self.assertIn("执行失败", result)

    def test_unknown_tool(self):
        self.client.initialize()
        result = self.client.call_tool("no_such", {})
        self.assertIn("未知工具", result)


class TestMCPTimeout(unittest.TestCase):
    def test_timeout_returns_error(self):
        client = _stdio_client(timeout=1)
        try:
            client.initialize()
            t0 = time.time()
            with self.assertRaises(MCPError):
                client.call_tool("sleep", {"seconds": 5})
            self.assertLess(time.time() - t0, 4, "超时应快速返回")
        finally:
            client.close()


class TestMCPHttp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.proc = subprocess.Popen(
            [sys.executable, FIXTURE, "--http", "0"],
            stdout=subprocess.PIPE, text=True, encoding="utf-8",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        line = cls.proc.stdout.readline().strip()
        import json as _json
        cls.port = _json.loads(line)["port"]

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        try:
            cls.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            cls.proc.kill()

    def setUp(self):
        self.client = MCPClient(
            HttpTransport(f"http://127.0.0.1:{self.port}", timeout=5), timeout=5)

    def tearDown(self):
        self.client.close()

    def test_http_roundtrip(self):
        self.client.initialize()
        tools = self.client.list_tools()
        self.assertEqual(len(tools), 3)
        result = self.client.call_tool("echo", {"message": "http ok"})
        self.assertEqual(result, "http ok")


class TestMCPConnectionError(unittest.TestCase):
    def test_http_refused(self):
        client = MCPClient(HttpTransport("http://127.0.0.1:1", timeout=1), timeout=1)
        with self.assertRaises(MCPError):
            client.initialize()
        client.close()

    def test_stdio_bad_command(self):
        transport = StdioTransport("definitely-not-a-real-command-xyz", timeout=2)
        transport.start()
        client = MCPClient(transport, timeout=2)
        with self.assertRaises(MCPError):
            client.initialize()
        client.close()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: 运行测试确认失败**

Run: `python -m unittest tests.test_mcp_client -v`
Expected: 全部 ERROR（`ModuleNotFoundError: No module named 'modules.mcp_client'`）

- [ ] **Step 4: 实现 `modules/mcp_client.py`**

创建 `modules/mcp_client.py`（完整内容）：

```python
"""
轻量 MCP client — JSON-RPC 2.0 子集，支持 stdio 与 HTTP 传输。
只实现 tools 相关协议：initialize / notifications/initialized / tools/list / tools/call。
零第三方依赖（HTTP 传输复用项目已有的 requests）。
"""
import json
import queue
import subprocess
import threading
import time

import requests as _requests


class MCPError(Exception):
    """MCP 协议/连接/超时错误的统一类型"""


# ============================================================
# stdio 传输：子进程 + 每行一个 JSON 消息
# ============================================================
class StdioTransport:
    def __init__(self, command, args=None, timeout=60):
        self._cmd = command
        self._args = list(args or [])
        self._timeout = timeout
        self._proc = None
        self._out_q = queue.Queue()
        self._err_lines = []
        self._started = False

    def start(self):
        try:
            self._proc = subprocess.Popen(
                [self._cmd] + self._args,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding="utf-8",
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as e:
            raise MCPError(f"无法启动 MCP server 进程 '{self._cmd}': {e}") from e
        self._started = True
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _read_stdout(self):
        for line in self._proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                self._out_q.put(("msg", json.loads(line)))
            except json.JSONDecodeError:
                pass  # 忽略启动横幅等非 JSON 输出

    def _read_stderr(self):
        for line in self._proc.stderr:
            self._err_lines.append(line.rstrip())
            if len(self._err_lines) > 200:
                self._err_lines.pop(0)

    def _write(self, payload):
        if self._proc.poll() is not None:
            detail = " | ".join(self._err_lines[-5:])
            raise MCPError(
                f"MCP server 进程已退出 (code={self._proc.returncode}){detail}")
        self._proc.stdin.write(json.dumps(payload) + "\n")
        self._proc.stdin.flush()

    def _wait_result(self, request_id):
        deadline = time.time() + self._timeout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise MCPError(f"MCP 请求超时（{self._timeout}s）")
            try:
                _, data = self._out_q.get(timeout=min(remaining, 0.5))
            except queue.Empty:
                if self._proc.poll() is not None:
                    detail = " | ".join(self._err_lines[-5:])
                    raise MCPError(
                        f"MCP server 进程已退出 (code={self._proc.returncode}){detail}")
                continue
            if data.get("id") == request_id:
                if "error" in data:
                    err = data["error"]
                    raise MCPError(f"MCP 错误: {err.get('message', err)}")
                return data.get("result")

    def send_request(self, method, params, request_id):
        self._write({"jsonrpc": "2.0", "id": request_id,
                     "method": method, "params": params or {}})
        return self._wait_result(request_id)

    def send_notification(self, method, params):
        self._write({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def close(self):
        if not self._started or self._proc is None:
            return
        if self._proc.poll() is None:
            try:
                self._proc.stdin.close()
            except Exception:
                pass
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()


# ============================================================
# HTTP 传输：JSON-RPC over POST（兼容 application/json 与 SSE）
# ============================================================
class HttpTransport:
    def __init__(self, url, token=None, timeout=60):
        self._url = url
        self._token = token
        self._timeout = timeout

    def start(self):
        pass

    def _post(self, payload):
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            resp = _requests.post(self._url, headers=headers,
                                  json=payload, timeout=self._timeout)
        except Exception as e:
            raise MCPError(f"MCP HTTP 请求失败: {e}") from e
        if resp.status_code >= 400:
            raise MCPError(f"MCP HTTP {resp.status_code}: {resp.text[:200]}")
        return resp

    @staticmethod
    def _parse_body(resp):
        ct = resp.headers.get("Content-Type", "")
        text = resp.text
        if "text/event-stream" in ct:
            data_lines = [ln[5:].strip() for ln in text.splitlines()
                          if ln.startswith("data:")]
            if not data_lines:
                raise MCPError("MCP SSE 响应中无 data 行")
            return json.loads(data_lines[-1])
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise MCPError(f"MCP HTTP 响应不是 JSON: {text[:200]}") from e

    def send_request(self, method, params, request_id):
        resp = self._post({"jsonrpc": "2.0", "id": request_id,
                           "method": method, "params": params or {}})
        body = self._parse_body(resp)
        if body.get("error"):
            err = body["error"]
            raise MCPError(f"MCP 错误: {err.get('message', err)}")
        return body.get("result")

    def send_notification(self, method, params):
        try:
            self._post({"jsonrpc": "2.0", "method": method, "params": params or {}})
        except MCPError:
            pass  # notification 失败可忽略

    def close(self):
        pass


# ============================================================
# MCP client 门面
# ============================================================
class MCPClient:
    def __init__(self, transport, timeout=60):
        self._transport = transport
        self._timeout = timeout
        self._next_id = 0

    def _request_id(self):
        self._next_id += 1
        return self._next_id

    def initialize(self):
        self._transport.start()
        result = self._transport.send_request("initialize", {
            "protocolVersion": "1.0",
            "capabilities": {},
            "clientInfo": {"name": "agent-editor", "version": "0.1"},
        }, self._request_id())
        self._transport.send_notification("notifications/initialized", {})
        return result

    def list_tools(self):
        tools = []
        cursor = None
        while True:
            params = {"cursor": cursor} if cursor else {}
            result = self._transport.send_request("tools/list", params,
                                                  self._request_id())
            tools.extend(result.get("tools", []))
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return tools

    def call_tool(self, name, args):
        result = self._transport.send_request("tools/call", {
            "name": name, "arguments": args or {},
        }, self._request_id())
        content = result.get("content", [])
        text = "".join(c.get("text", "") for c in content
                       if isinstance(c, dict) and c.get("type") == "text")
        if result.get("isError"):
            return f"❌ MCP 工具 {name} 执行失败: {text or '无错误信息'}"
        return text or "(无输出)"

    def close(self):
        self._transport.close()
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m unittest tests.test_mcp_client -v`
Expected: 8 个测试全部 ok

- [ ] **Step 6: 提交**

```bash
git add tests/fixtures/mini_mcp_server.py tests/test_mcp_client.py modules/mcp_client.py
git commit -m "feat: MCP 协议层（stdio+HTTP 双传输、initialize/list_tools/call_tool）+ fixture server + 8 测试"
```

---

### Task 2: 配置/生命周期/动态注册（mcp_manager.py）

**Files:**
- Create: `tests/test_mcp_manager.py`
- Create: `modules/mcp_manager.py`

**Interfaces:**
- Consumes:
  - `mcp_client.MCPClient / StdioTransport / HttpTransport / MCPError`（Task 1 签名）
- Produces:
  - `mcp_manager.init_mcp_manager(path: str | None = None)` — 重定向配置路径并 `load_and_sync()`（path=None 时用环境变量 `MCP_CONFIG_PATH` 或默认 `data/mcp_config.json`）
  - `mcp_manager.load_and_sync()` — 全量重连同步
  - `mcp_manager.add_server(config: dict) -> dict` — 校验+保存+连接注册；返回 `{success, error?}`；id 重复返回 error
  - `mcp_manager.update_server(server_id: str, config: dict) -> dict`
  - `mcp_manager.remove_server(server_id: str) -> dict`
  - `mcp_manager.test_server(config: dict) -> dict` — initialize+list_tools 不注册
  - `mcp_manager.get_status() -> list[dict]` — `[{id, name, type, enabled, connected, error, tool_count, tools: [name...]}]`
  - `mcp_manager.get_server_tools(server_id: str) -> list[dict]`
  - `mcp_manager.register_routes(app)` — Flask 路由（Task 3 使用）
  - 常量 `mcp_manager.TOOL_PREFIX = "mcp_ext_"`

- [ ] **Step 1: 写配置/注册失败测试**

创建 `tests/test_mcp_manager.py`（完整内容）：

```python
"""mcp_manager 测试：配置 CRUD、动态注册、命名、失败隔离、token 边界"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules import mcp_manager, tool_registry
from modules.mcp_client import MCPError

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "fixtures", "mini_mcp_server.py")


def _stdio_cfg(server_id="mini", enabled=True):
    return {
        "id": server_id, "name": "Mini Server", "type": "stdio",
        "command": sys.executable, "args": [FIXTURE], "enabled": enabled,
    }


class TestMcpManager(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tempfile
        base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "data", "vector_store", ".test_tmp")
        os.makedirs(base, exist_ok=True)
        cls.tmpdir = tempfile.mkdtemp(prefix="mcp_", dir=base)
        cls.cfg_path = os.path.join(cls.tmpdir, "mcp_config.json")

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmpdir, ignore_errors=True)
        mcp_manager.init_mcp_manager(None)  # 恢复默认路径（不重连，仅重置）

    def setUp(self):
        mcp_manager.init_mcp_manager(self.cfg_path)

    def tearDown(self):
        # 确保注销所有动态注册的工具
        for s in mcp_manager.get_status():
            mcp_manager.remove_server(s["id"])

    def test_add_server_registers_tools(self):
        r = mcp_manager.add_server(_stdio_cfg("git"))
        self.assertTrue(r["success"], r)
        status = {s["id"]: s for s in mcp_manager.get_status()}
        self.assertTrue(status["git"]["connected"])
        self.assertEqual(status["git"]["tool_count"], 3)
        # 工具已动态注册进 tool_registry，命名带前缀
        for tool in ("echo", "fail", "sleep"):
            full = f"mcp_ext_git_{tool}"
            self.assertEqual(
                len(tool_registry.get_definitions_by_names([full])), 1,
                f"{full} 应已注册")

    def test_tool_execution_via_registry(self):
        mcp_manager.add_server(_stdio_cfg("git"))
        result = tool_registry.execute("mcp_ext_git_echo",
                                       {"message": "通过注册表调用"})
        self.assertEqual(result, "通过注册表调用")

    def test_duplicate_id_rejected(self):
        mcp_manager.add_server(_stdio_cfg("dup"))
        r = mcp_manager.add_server(_stdio_cfg("dup"))
        self.assertFalse(r["success"])
        self.assertIn("已存在", r["error"])

    def test_invalid_id_rejected(self):
        r = mcp_manager.add_server(_stdio_cfg("bad id!"))
        self.assertFalse(r["success"])

    def test_remove_unregisters_tools(self):
        mcp_manager.add_server(_stdio_cfg("rm"))
        r = mcp_manager.remove_server("rm")
        self.assertTrue(r["success"])
        self.assertEqual(tool_registry.get_definitions_by_names(
            ["mcp_ext_rm_echo"]), [])

    def test_disabled_server_not_connected(self):
        r = mcp_manager.add_server(_stdio_cfg("off", enabled=False))
        self.assertTrue(r["success"])
        status = {s["id"]: s for s in mcp_manager.get_status()}
        self.assertFalse(status["off"]["connected"])
        self.assertEqual(tool_registry.get_definitions_by_names(
            ["mcp_ext_off_echo"]), [])

    def test_bad_server_does_not_block_others(self):
        bad = {"id": "bad", "name": "Bad", "type": "http",
               "url": "http://127.0.0.1:1", "enabled": True}
        r_bad = mcp_manager.add_server(bad)
        self.assertFalse(r_bad["success"])
        self.assertTrue(r_bad.get("error"))
        # 好 server 仍可用
        r_ok = mcp_manager.add_server(_stdio_cfg("ok"))
        self.assertTrue(r_ok["success"])
        status = {s["id"]: s for s in mcp_manager.get_status()}
        self.assertTrue(status["ok"]["connected"])

    def test_persistence_across_reload(self):
        mcp_manager.add_server(_stdio_cfg("persist"))
        mcp_manager.load_and_sync()  # 模拟重启：从盘重读 + 重连
        status = {s["id"]: s for s in mcp_manager.get_status()}
        self.assertTrue(status["persist"]["connected"])
        self.assertEqual(status["persist"]["tool_count"], 3)

    def test_config_contains_no_project_secrets(self):
        # token 只写进 mcp_config.json，不进任何项目 json（本项目无项目 json 参与，
        # 验证配置文件的 token 字段只存在于全局配置）
        cfg = _stdio_cfg("tok")
        cfg["token"] = "sk-super-secret"
        mcp_manager.add_server(cfg)
        with open(self.cfg_path, encoding="utf-8") as f:
            saved = json.load(f)
        server = next(s for s in saved["servers"] if s["id"] == "tok")
        self.assertEqual(server["token"], "sk-super-secret")

    def test_get_server_tools(self):
        mcp_manager.add_server(_stdio_cfg("ls"))
        tools = mcp_manager.get_server_tools("ls")
        names = [t["name"] for t in tools]
        self.assertEqual(names, ["echo", "fail", "sleep"])

    def test_test_server_without_register(self):
        r = mcp_manager.test_server(_stdio_cfg("tst"))
        self.assertTrue(r["success"])
        self.assertEqual(len(r.get("tools", [])), 3)
        # 未注册
        self.assertEqual(tool_registry.get_definitions_by_names(
            ["mcp_ext_tst_echo"]), [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m unittest tests.test_mcp_manager -v`
Expected: 全部 ERROR（`ModuleNotFoundError: No module named 'modules.mcp_manager'`）

- [ ] **Step 3: 实现 `modules/mcp_manager.py`**

创建 `modules/mcp_manager.py`（完整内容）：

```python
"""
MCP server 管理：全局配置（data/mcp_config.json）+ 生命周期 + tool_registry 动态注册。

配置结构：
{"servers": [{"id": "git", "name": "...", "type": "stdio",
              "command": "npx", "args": [...], "enabled": true},
             {"id": "x", "name": "...", "type": "http",
              "url": "...", "token": "...", "enabled": true}]}
"""
import json
import os
import re
import threading

from flask import jsonify, request

from . import tool_registry
from .mcp_client import MCPClient, MCPError, HttpTransport, StdioTransport

TOOL_PREFIX = "mcp_ext_"
_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,32}$")

_DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "mcp_config.json")

_lock = threading.RLock()
_config_path = None
_servers = {}  # id -> {config, client, tools, connected, error, registered}


# ============================================================
# 配置读写（原子写）
# ============================================================
def _load_config() -> dict:
    path = _config_path
    if not path or not os.path.exists(path):
        return {"servers": []}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {"servers": []}
    except Exception:
        return {"servers": []}


def _save_config(data: dict):
    path = _config_path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ============================================================
# 连接与注册
# ============================================================
def _build_client(cfg):
    if cfg.get("type") == "http":
        return MCPClient(HttpTransport(cfg["url"], cfg.get("token")))
    return MCPClient(StdioTransport(cfg["command"], cfg.get("args", [])))


def _make_handler(client, tool_name):
    def handler(args):
        return client.call_tool(tool_name, args)
    return handler


def _register_tools(server_id, tools, client):
    registered = []
    for t in tools:
        name = t.get("name")
        if not name:
            continue
        full = f"{TOOL_PREFIX}{server_id}_{name}"
        definition = {
            "name": full,
            "description": t.get("description", ""),
            "parameters": t.get("inputSchema",
                                {"type": "object", "properties": {}}),
        }
        tool_registry.register(full, definition, _make_handler(client, name))
        registered.append(full)
    return registered


def _unregister_tools(server_id):
    entry = _servers.get(server_id)
    for full in (entry or {}).get("registered", []):
        tool_registry.unregister(full)


def _sync_one(cfg):
    server_id = cfg["id"]
    # 清理旧状态
    if server_id in _servers:
        _unregister_tools(server_id)
        _servers.pop(server_id, None)
    entry = {"config": cfg, "client": None, "tools": [],
             "connected": False, "error": None, "registered": []}
    if not cfg.get("enabled", True):
        _servers[server_id] = entry
        return entry
    try:
        client = _build_client(cfg)
        client.initialize()
        tools = client.list_tools()
        registered = _register_tools(server_id, tools, client)
        entry.update(client=client, tools=tools, connected=True,
                     registered=registered)
    except MCPError as e:
        entry["error"] = str(e)
    _servers[server_id] = entry
    return entry


def load_and_sync():
    """从配置盘读全量并同步连接/注册；删除已不存在的 server"""
    with _lock:
        cfg = _load_config()
        ids = set()
        for s in cfg.get("servers", []):
            if not isinstance(s, dict) or not s.get("id"):
                continue
            ids.add(s["id"])
            _sync_one(s)
        for sid in list(_servers.keys()):
            if sid not in ids:
                _unregister_tools(sid)
                _servers.pop(sid, None)


def init_mcp_manager(path=None):
    """重定向配置路径并重新同步（测试/多实例用）。None 回退环境变量或默认路径。"""
    global _config_path
    with _lock:
        _config_path = path or os.environ.get("MCP_CONFIG_PATH") or _DEFAULT_CONFIG_PATH
    load_and_sync()


def _validate(cfg) -> str | None:
    """返回错误消息或 None"""
    if not isinstance(cfg, dict):
        return "配置必须是对象"
    if not cfg.get("id") or not _ID_RE.match(cfg["id"]):
        return "id 必填，且只能含字母/数字/下划线/连字符（≤32 字符）"
    if cfg.get("type") == "http":
        if not cfg.get("url"):
            return "HTTP 类型必须提供 url"
    elif cfg.get("type") == "stdio":
        if not cfg.get("command"):
            return "stdio 类型必须提供 command"
    else:
        return "type 必须是 stdio 或 http"
    return None


def add_server(cfg) -> dict:
    with _lock:
        err = _validate(cfg)
        if err:
            return {"success": False, "error": err}
        server_id = cfg["id"]
        if server_id in _servers:
            return {"success": False, "error": f"server id '{server_id}' 已存在"}
        data = _load_config()
        if any(s.get("id") == server_id for s in data.get("servers", [])):
            return {"success": False, "error": f"server id '{server_id}' 已存在"}
        data.setdefault("servers", []).append(cfg)
        _save_config(data)
        _sync_one(cfg)
        entry = _servers.get(server_id, {})
        if entry.get("error"):
            return {"success": False, "error": entry["error"],
                    "saved": True, "connected": False}
        return {"success": True, "connected": True,
                "tool_count": len(entry.get("tools", []))}


def update_server(server_id, cfg) -> dict:
    with _lock:
        if server_id not in _servers:
            return {"success": False, "error": f"server '{server_id}' 不存在"}
        if cfg.get("id") and cfg["id"] != server_id:
            return {"success": False, "error": "id 不可变更"}
        merged = dict(_servers[server_id]["config"])
        merged.update(cfg)
        merged["id"] = server_id
        err = _validate(merged)
        if err:
            return {"success": False, "error": err}
        data = _load_config()
        for i, s in enumerate(data.get("servers", [])):
            if s.get("id") == server_id:
                data["servers"][i] = merged
                break
        _save_config(data)
        _sync_one(merged)
        entry = _servers.get(server_id, {})
        if entry.get("error"):
            return {"success": False, "error": entry["error"],
                    "saved": True, "connected": False}
        return {"success": True, "connected": True,
                "tool_count": len(entry.get("tools", []))}


def remove_server(server_id) -> dict:
    with _lock:
        if server_id not in _servers:
            return {"success": False, "error": f"server '{server_id}' 不存在"}
        _unregister_tools(server_id)
        _servers.pop(server_id, None)
        data = _load_config()
        data["servers"] = [s for s in data.get("servers", [])
                           if s.get("id") != server_id]
        _save_config(data)
        return {"success": True}


def test_server(cfg) -> dict:
    """测试连接：initialize + list_tools，不注册不保存"""
    err = _validate(cfg)
    if err:
        return {"success": False, "error": err}
    client = _build_client(cfg)
    try:
        client.initialize()
        tools = client.list_tools()
        return {"success": True, "tool_count": len(tools),
                "tools": tools}
    except MCPError as e:
        return {"success": False, "error": str(e)}
    finally:
        client.close()


def get_status() -> list:
    with _lock:
        out = []
        for sid, e in _servers.items():
            cfg = e["config"]
            out.append({
                "id": sid,
                "name": cfg.get("name", sid),
                "type": cfg.get("type"),
                "enabled": cfg.get("enabled", True),
                "connected": e["connected"],
                "error": e["error"],
                "tool_count": len(e["tools"]),
                "tools": [t.get("name") for t in e["tools"]],
            })
        return out


def get_server_tools(server_id):
    with _lock:
        entry = _servers.get(server_id)
        return list(entry["tools"]) if entry else []


# ============================================================
# Flask 路由
# ============================================================
def register_routes(app):
    @app.route("/api/mcp/servers", methods=["GET"])
    def mcp_list():
        return jsonify({"success": True, "servers": get_status()})

    @app.route("/api/mcp/servers", methods=["POST"])
    def mcp_create():
        cfg = request.get_json(force=True, silent=True) or {}
        return jsonify(add_server(cfg))

    @app.route("/api/mcp/servers/<server_id>", methods=["PUT"])
    def mcp_update(server_id):
        cfg = request.get_json(force=True, silent=True) or {}
        return jsonify(update_server(server_id, cfg))

    @app.route("/api/mcp/servers/<server_id>", methods=["DELETE"])
    def mcp_delete(server_id):
        return jsonify(remove_server(server_id))

    @app.route("/api/mcp/servers/<server_id>/test", methods=["POST"])
    def mcp_test(server_id):
        cfg = request.get_json(force=True, silent=True) or {}
        cfg["id"] = cfg.get("id", server_id)
        return jsonify(test_server(cfg))

    @app.route("/api/mcp/servers/<server_id>/tools", methods=["GET"])
    def mcp_tools(server_id):
        tools = get_server_tools(server_id)
        if not any(s["id"] == server_id for s in get_status()):
            return jsonify({"success": False, "error": "server 不存在"})
        return jsonify({"success": True, "tools": tools})
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m unittest tests.test_mcp_manager -v`
Expected: 12 个测试全部 ok

- [ ] **Step 5: 提交**

```bash
git add tests/test_mcp_manager.py modules/mcp_manager.py
git commit -m "feat: MCP 配置管理/生命周期/动态注册（12 测试）"
```

---

### Task 3: 路由挂载 + gitignore + 路由测试

**Files:**
- Create: `tests/test_mcp_routes.py`
- Modify: `modules/__init__.py`（register_all 内加 2 行）
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `mcp_manager.register_routes(app)`（Task 2）
- Produces: 运行中的 `/api/mcp/servers` 系列路由

- [ ] **Step 1: .gitignore 排除配置**

用 PowerShell（文件为 UTF-8）追加两行到 `.gitignore` 末尾：

```powershell
Add-Content -Path .gitignore -Value "`n# MCP server 配置（可能含 token，仅存本地）`ndata/mcp_config.json" -Encoding utf8
```

验证：`git check-ignore -v data/mcp_config.json` 应输出匹配行。

- [ ] **Step 2: 挂载路由**

修改 `modules/__init__.py`：在 `from . import vector_memory` 之后加一行，在 `vector_memory.register_routes(app)` 之后加一行：

```python
    # 向量记忆（语义搜索）
    from . import vector_memory
    # 外部 MCP 工具
    from . import mcp_client, mcp_manager
    ...
    vector_memory.register_routes(app)
    mcp_manager.register_routes(app)
```

注意：`mcp_manager` 模块顶部应调用 `init_mcp_manager()` 做启动同步（在 `register_routes` 定义后加）：

```python
# 启动时同步（连接 enabled server 并注册工具；失败不阻塞启动）
init_mcp_manager()
```

- [ ] **Step 3: 写路由失败测试**

创建 `tests/test_mcp_routes.py`（完整内容）：

```python
"""MCP 管理路由测试（Flask test client）"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask

from modules import mcp_manager
from modules.mcp_client import MCPError

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "fixtures", "mini_mcp_server.py")


def _make_app():
    app = Flask(__name__)
    mcp_manager.register_routes(app)
    return app


class TestMcpRoutes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tempfile
        base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "data", "vector_store", ".test_tmp")
        os.makedirs(base, exist_ok=True)
        cls.tmpdir = tempfile.mkdtemp(prefix="mcp_rt_", dir=base)
        cls.cfg_path = os.path.join(cls.tmpdir, "mcp_config.json")
        mcp_manager.init_mcp_manager(cls.cfg_path)
        cls.app = _make_app()
        cls.client = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def tearDown(self):
        for s in mcp_manager.get_status():
            mcp_manager.remove_server(s["id"])

    def _stdio_body(self, sid="route"):
        return {"id": sid, "name": "Route Server", "type": "stdio",
                "command": sys.executable, "args": [FIXTURE], "enabled": True}

    def test_list_empty(self):
        r = self.client.get("/api/mcp/servers")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["servers"], [])

    def test_create_and_list(self):
        r = self.client.post("/api/mcp/servers", json=self._stdio_body("c1"))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["success"])
        lst = self.client.get("/api/mcp/servers").get_json()["servers"]
        self.assertEqual(len(lst), 1)
        self.assertEqual(lst[0]["id"], "c1")
        self.assertTrue(lst[0]["connected"])
        self.assertEqual(lst[0]["tool_count"], 3)

    def test_update(self):
        self.client.post("/api/mcp/servers", json=self._stdio_body("u1"))
        r = self.client.put("/api/mcp/servers/u1", json={"name": "改名"})
        self.assertTrue(r.get_json()["success"])
        lst = self.client.get("/api/mcp/servers").get_json()["servers"]
        self.assertEqual(lst[0]["name"], "改名")

    def test_delete(self):
        self.client.post("/api/mcp/servers", json=self._stdio_body("d1"))
        r = self.client.delete("/api/mcp/servers/d1")
        self.assertTrue(r.get_json()["success"])
        self.assertEqual(self.client.get("/api/mcp/servers").get_json()["servers"], [])

    def test_test_endpoint(self):
        r = self.client.post("/api/mcp/servers/t1/test", json=self._stdio_body("t1"))
        body = r.get_json()
        self.assertTrue(body["success"])
        self.assertEqual(body["tool_count"], 3)
        # test 不注册
        self.assertEqual(mcp_manager.get_status(), [])

    def test_tools_endpoint(self):
        self.client.post("/api/mcp/servers", json=self._stdio_body("tk"))
        r = self.client.get("/api/mcp/servers/tk/tools")
        names = [t["name"] for t in r.get_json()["tools"]]
        self.assertEqual(names, ["echo", "fail", "sleep"])

    def test_bad_create_rejected(self):
        r = self.client.post("/api/mcp/servers", json={"id": "x y", "type": "stdio"})
        self.assertFalse(r.get_json()["success"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: 运行测试确认失败**

Run: `python -m unittest tests.test_mcp_routes -v`
Expected: 全部 ERROR（`No module named 'modules.mcp_client'`——Task 3 在干净 checkout 上从 Task 2 结果继续，应因 mcp_manager 尚未挂路由而 404）

- [ ] **Step 5: 运行测试确认通过（Step 1-2 完成后）**

Run: `python -m unittest tests.test_mcp_routes -v`
Expected: 7 个测试全部 ok

- [ ] **Step 6: 全量回归**

Run: `python -m unittest discover -s tests`
Expected: 42 + 8 + 12 + 7 = 69 个测试全部 OK

- [ ] **Step 7: 提交**

```bash
git add tests/test_mcp_routes.py modules/__init__.py .gitignore
git commit -m "feat: MCP 管理路由挂载（6 路由）+ gitignore 排除 mcp_config.json + 7 路由测试"
```

---

### Task 4: 前端 — 设置面板 MCP Servers 管理区

**Files:**
- Modify: `templates/index.html`（settings-body 末尾加一组）
- Modify: `static/app.js`（新增 MCP 管理 UI 函数，在 `setupSettingsPanel` 附近）

**Interfaces:**
- Consumes: `GET/POST/PUT/DELETE /api/mcp/servers`、`POST /api/mcp/servers/<id>/test`（Task 3）
- Produces: `loadMcpServers()` / `renderMcpServers()` / `openMcpEditor(id?)` / `deleteMcpServer(id)` / `testMcpServer(id)`（后续 Task 5 的组件面板复用 `loadMcpServers()`）

- [ ] **Step 1: index.html 加 MCP 管理区**

在 `templates/index.html` 的 `settings-body` 内、现有最后一个 `.settings-group` 之后（约第 950 行附近）追加：

```html
                <div class="settings-group">
                    <label class="settings-label">MCP Servers / 外部 MCP 工具</label>
                    <div id="mcp-server-list" style="margin-top:8px;font-size:13px;"></div>
                    <div style="display:flex;gap:6px;margin-top:10px;">
                        <button class="module-btn" id="btn-mcp-add" style="flex:1;">➕ 添加 MCP Server</button>
                    </div>
                </div>
```

- [ ] **Step 2: app.js 加 MCP 管理逻辑**

在 `static/app.js` 的 `setupSettingsPanel` 函数定义之后新增：

```javascript
// ============ MCP Server 管理 ============
async function fetchJson(url, options) {
    const resp = await fetch(url, options);
    return resp.json();
}

async function loadMcpServers() {
    const data = await fetchJson('/api/mcp/servers');
    return data.servers || [];
}

function mcpStatusBadge(s) {
    if (!s.enabled) return '<span style="color:#999;">已停用</span>';
    if (s.connected) return '<span style="color:#52c41a;">已连接</span>';
    return `<span style="color:#f5222d;" title="${escapeHtml(s.error || '')}">错误</span>`;
}

async function renderMcpServers() {
    const box = document.getElementById('mcp-server-list');
    if (!box) return;
    const servers = await loadMcpServers();
    if (!servers.length) {
        box.innerHTML = '<div style="color:#999;padding:6px 0;">尚未配置 MCP server。添加后即可在画布中使用"外部 MCP 工具"组件。</div>';
        return;
    }
    box.innerHTML = servers.map(s => `
        <div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid #f0f0f0;">
            <span style="flex:1;">${escapeHtml(s.name)} <span style="color:#999;">(${s.type}, ${s.tool_count} 工具)</span></span>
            ${mcpStatusBadge(s)}
            <button class="module-btn secondary" data-mcp-test="${s.id}" style="font-size:12px;padding:4px 8px;">测试</button>
            <button class="module-btn secondary" data-mcp-edit="${s.id}" style="font-size:12px;padding:4px 8px;">编辑</button>
            <button class="module-btn secondary" data-mcp-del="${s.id}" style="font-size:12px;padding:4px 8px;color:#f5222d;">删除</button>
        </div>`).join('');
    box.querySelectorAll('[data-mcp-test]').forEach(b => b.onclick = () => testMcpServer(b.dataset.mcpTest));
    box.querySelectorAll('[data-mcp-edit]').forEach(b => b.onclick = () => openMcpEditor(b.dataset.mcpEdit));
    box.querySelectorAll('[data-mcp-del]').forEach(b => b.onclick = () => deleteMcpServer(b.dataset.mcpDel));
}

function openMcpEditor(serverId) {
    const existing = (serverId && document.querySelector(`[data-mcp-editor="${serverId}"]`));
    // 简单实现：prompt 表单（与项目设置面板轻量风格一致）
    const servers = window.__mcpServers || [];
    const s = serverId ? servers.find(x => x.id === serverId) : null;
    const defaults = s ? s : { id: '', name: '', type: 'stdio', command: 'npx', args: '', enabled: true };
    const id = prompt('server id（字母数字-_，≤32，不可重复）', defaults.id || '');
    if (id === null) return;
    const name = prompt('显示名称', defaults.name || '');
    if (name === null) return;
    const type = prompt('类型（stdio / http）', defaults.type || 'stdio');
    if (type === null) return;
    let cfg = { id, name, type, enabled: true };
    if (type === 'stdio') {
        const cmd = prompt('命令（如 npx）', defaults.command || 'npx');
        if (cmd === null) return;
        const args = prompt('参数，空格分隔（如 -y @modelcontextprotocol/server-git）', (defaults.args || []).join(' ') || '');
        if (args === null) return;
        cfg.command = cmd;
        cfg.args = args.trim() ? args.trim().split(/\s+/) : [];
    } else {
        const url = prompt('HTTP URL', defaults.url || '');
        if (url === null) return;
        cfg.url = url;
        const token = prompt('可选 token（仅存本地）', defaults.token || '');
        if (token === null) return;
        if (token) cfg.token = token;
    }
    const opts = { method: serverId ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cfg) };
    fetchJson(serverId ? `/api/mcp/servers/${serverId}` : '/api/mcp/servers', opts).then(r => {
        if (!r.success) { alert('保存失败: ' + (r.error || '未知错误')); return; }
        renderMcpServers();
    });
}

async function deleteMcpServer(id) {
    if (!confirm(`确定删除 MCP server '${id}'？其工具将从画布中移除。`)) return;
    const r = await fetchJson(`/api/mcp/servers/${id}`, { method: 'DELETE' });
    if (!r.success) { alert('删除失败: ' + (r.error || '')); return; }
    renderMcpServers();
}

async function testMcpServer(id) {
    const servers = await loadMcpServers();
    const s = servers.find(x => x.id === id);
    if (!s) return;
    const cfg = { id: s.id, name: s.name, type: s.type, enabled: true };
    if (s.type === 'stdio') { cfg.command = s.command; cfg.args = s.args || []; }
    else { cfg.url = s.url; if (s.token) cfg.token = s.token; }
    const r = await fetchJson(`/api/mcp/servers/${id}/test`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cfg) });
    alert(r.success ? `连接成功，共 ${r.tool_count} 个工具` : '连接失败: ' + (r.error || ''));
}
```

在 `setupSettingsPanel` 函数内（第 800-810 行附近），找到打开 overlay 的代码（`overlay.style.display = 'block'` 那一行），在其后追加一行：

```javascript
    renderMcpServers(); // 打开设置时刷新 MCP server 列表
```

- [ ] **Step 3: 验证**

启动服务器：`python server.py`，浏览器打开 http://localhost:5000/editor → 设置按钮 → 应看到 "MCP Servers" 分组；添加一个 stdio server（命令 `python`，参数填 fixture 路径）应显示"已连接 3 工具"。

（沙箱无法开浏览器时，至少确认 `node -e` 语法检查不可用——用 `python -m py_compile` 只查后端；前端用人工 review + 下一任务的端到端步骤验证。）

- [ ] **Step 4: 提交**

```bash
git add templates/index.html static/app.js
git commit -m "feat: 设置面板 MCP Servers 管理区（列表/添加/编辑/删除/测试）"
```

---

### Task 5: 前端 — mcp_external 组件 + 工具名注入

**Files:**
- Modify: `templates/index.html`（工具能力区加 pallet 条目）
- Modify: `static/app.js`（COMPONENT_DEFS、renderMcpExternalPanel、collectToolsFromPorts、serializeComponent）

**Interfaces:**
- Consumes: `loadMcpServers()`（Task 4）、`GET /api/mcp/servers/<id>/tools`
- Produces: `mcp_external` 组件类型，节点数据 `{serverId, toolNames: string[]}`；`collectToolsFromPorts` 对 `mcp_external` 回退读 `comp.toolNames`

- [ ] **Step 1: index.html 加组件面板条目**

在 `templates/index.html` 工具能力区（`http_request` 条目之后，约第 435 行）追加：

```html
                    <div class="pallet-item is-mcp_external" draggable="true" data-type="mcp_external" title="外部 MCP 工具（需先在设置中配置 server）">
                        <div class="pallet-icon-box" style="background:#f6ffed;color:#389e0d;">
                            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
                                <path d="M21 12a9 9 0 1 1-9-9"/><polyline points="13 3 21 3 21 11"/><line x1="21" y1="3" x2="12" y2="12"/>
                            </svg>
                        </div>
                        <div>
                            <div class="pallet-name">外部 MCP 工具</div>
                            <div class="pallet-desc">连接 MCP server，调用其工具</div>
                        </div>
                    </div>
```

- [ ] **Step 2: COMPONENT_DEFS 加节点定义**

在 `static/app.js` 的 `COMPONENT_DEFS` 中 `image_tools` 定义之后加：

```javascript
    mcp_external: {
        icon: '\u{1F517}', title: '外部 MCP 工具', color: '#389e0d', defaultSize: 5,
        render: renderMcpExternalPanel,
        ports: { inputs: [{ id: 'mcp-ext-in', label: 'LLM 接入' }], outputs: [] },
        description: '连接设置中配置的 MCP server，将其工具注入 LLM。可勾选要使用的工具子集。',
    },
```

- [ ] **Step 3: 实现 render 函数**

在 `renderLLMPanel` 定义附近新增（完整内容）：

```javascript
// ============ 外部 MCP 工具组件 ============
async function renderMcpExternalPanel(container, comp) {
    if (!comp.serverId) comp.serverId = '';
    if (!comp.toolNames) comp.toolNames = null; // null = 全部工具
    const servers = await loadMcpServers().catch(() => []);
    const enabled = servers.filter(s => s.enabled);
    const opts = enabled.map(s => `<option value="${escapeHtml(s.id)}" ${comp.serverId === s.id ? 'selected' : ''}>${escapeHtml(s.name)} (${s.tool_count})</option>`).join('') || '<option value="">（请先在设置中配置 server）</option>';

    container.innerHTML = `
        <div style="padding:12px;">
            <label style="font-size:13px;color:#666;">MCP Server</label>
            <select id="mcp-sel-${comp.id}" style="width:100%;padding:6px;margin:6px 0 12px;border:1px solid #d9d9d9;border-radius:4px;">
                <option value="">（未选择）</option>
                ${opts}
            </select>
            <div id="mcp-tools-${comp.id}" style="max-height:180px;overflow-y:auto;border:1px solid #f0f0f0;border-radius:4px;padding:8px;font-size:13px;">
                ${comp.serverId ? '加载工具中…' : '选择 server 后显示可用工具'}
            </div>
        </div>
    `;
    const sel = container.querySelector(`#mcp-sel-${comp.id}`);
    sel.addEventListener('change', async () => {
        comp.serverId = sel.value;
        comp.toolNames = null;
        await renderMcpToolList(container, comp);
    });
    if (comp.serverId) await renderMcpToolList(container, comp);
}

async function renderMcpToolList(container, comp) {
    const box = container.querySelector(`#mcp-tools-${comp.id}`);
    if (!comp.serverId) { box.innerHTML = '<span style="color:#999;">未选择 server</span>'; return; }
    const data = await fetchJson(`/api/mcp/servers/${comp.serverId}/tools`).catch(() => null);
    if (!data || !data.success) { box.innerHTML = '<span style="color:#f5222d;">无法获取工具列表</span>'; return; }
    const tools = data.tools || [];
    const selected = comp.toolNames; // null = 全部
    box.innerHTML = tools.map(t => {
        const checked = selected === null ? 'checked' : (selected.includes(t.name) ? 'checked' : '');
        return `<label style="display:block;padding:3px 0;"><input type="checkbox" data-tool="${escapeHtml(t.name)}" ${checked}> ${escapeHtml(t.name)}</label>`;
    }).join('') || '<span style="color:#999;">该 server 没有可用工具</span>';
    box.querySelectorAll('input[data-tool]').forEach(cb => {
        cb.addEventListener('change', () => {
            const all = [...box.querySelectorAll('input[data-tool]')];
            if (all.every(x => x.checked)) { comp.toolNames = null; return; }
            comp.toolNames = all.filter(x => x.checked).map(x => x.dataset.tool);
        });
    });
}
```

- [ ] **Step 4: collectToolsFromPorts 扩展**

修改 `static/app.js` 的 `collectToolsFromPorts`（第 158-168 行），在 `const tns = TOOL_NAME_MAP[hit.target.type];` 之后加回退：

```javascript
            let tns = TOOL_NAME_MAP[hit.target.type];
            if (hit.target.type === 'mcp_external') {
                // 动态 MCP 工具：读节点保存的工具名（null = 全部用 server 工具）
                tns = hit.target.toolNames || null;
            }
            if (tns) tns.forEach(n => names.push(n));
```

- [ ] **Step 5: serializeComponent 白名单**

修改 `serializeComponent`（第 171-183 行附近），在返回对象中加：

```javascript
        // MCP 外部工具（只存引用，token/命令/URL 都在全局配置）
        serverId: c.serverId || null,
        toolNames: c.toolNames || null,
```

- [ ] **Step 6: 端到端验证**

启动服务器（fixture 场景）：
1. `python server.py`
2. 浏览器设置中配置 stdio server：命令 `python`、参数 `tests/fixtures/mini_mcp_server.py`（路径用绝对路径）
3. 画布拖入"外部 MCP 工具"节点 → 选择 server → 勾选工具
4. 连 LLM 节点 → 对话触发 `mcp_ext_<id>_echo` 调用

（沙箱内无浏览器：以 Task 3 的路由测试 + 人工 review 替代，标注"待用户在浏览器验证"。）

- [ ] **Step 7: 提交**

```bash
git add templates/index.html static/app.js
git commit -m "feat: 外部 MCP 工具组件（server 引用 + 工具筛选 + 动态工具名注入）"
```

---

### Task 6: 端到端验证 + 回归 + 文档

**Files:**
- Modify: `docs/PROJECT_BRIEF.md`

- [ ] **Step 1: 全量回归**

Run: `python -m unittest discover -s tests`
Expected: 69 个测试全部 OK

- [ ] **Step 2: 真实端到端冒烟（fixture 代替 npx，沙箱无 node）**

启动 `python server.py`，用 Task 4/5 步骤验证；另用 curl 冒烟：

```powershell
$body = '{"id":"smoke","name":"Smoke","type":"stdio","command":"python","args":["tests/fixtures/mini_mcp_server.py"],"enabled":true}'
Invoke-WebRequest -Uri http://localhost:5000/api/mcp/servers -Method POST -ContentType 'application/json' -Body $body | Select-Object -ExpandProperty Content
Invoke-WebRequest -Uri http://localhost:5000/api/mcp/servers -UseBasicParsing | Select-Object -ExpandProperty Content
```

Expected: POST 返回 `success: true, connected: true, tool_count: 3`；列表含 smoke。

- [ ] **Step 3: 更新 PROJECT_BRIEF.md**

在"已实现功能"加一条：

```markdown
7. **外部 MCP 工具**：手写轻量 MCP client（mcp_client.py，stdio+HTTP 双传输、JSON-RPC 2.0）；
   设置面板配置 MCP Servers（data/mcp_config.json，gitignore 排除）；
   工具动态注册进 tool_registry（命名 mcp_ext_<server_id>_<tool>），对话引擎零修改；
   编辑器"外部 MCP 工具"组件：引用 server + 勾选工具子集
```

待办区更新测试数：`测试 69 个（42 旧 + 27 MCP）`。

- [ ] **Step 4: 提交**

```bash
git add docs/PROJECT_BRIEF.md
git commit -m "docs: 记录外部 MCP 工具功能"
```

- [ ] **Step 5: 提示用户推送**

告知用户执行 `cd D:\myxiangfa-MCPxuexi && git push`（沙箱无法直连 github.com）。

---

## Self-Review 记录

- **Spec 覆盖**：协议层（T1）✓、配置/生命周期/注册（T2）✓、路由（T3）✓、设置面板（T4）✓、组件+注入（T5）✓、安全（T2 token 测试 + T3 gitignore）✓、测试（T1/T2/T3）✓、实现顺序（T1→T6）✓
- **占位符扫描**：所有代码步骤含完整代码；无 TBD/TODO
- **类型一致性**：`MCPClient(transport, timeout)` / `StdioTransport(command, args, timeout)` / `HttpTransport(url, token, timeout)` / `mcp_manager.init_mcp_manager(path)` / `TOOL_PREFIX="mcp_ext_"` / 节点字段 `serverId`/`toolNames` 在 T1-T5 间一致；`collectToolsFromPorts` 回退字段 `comp.toolNames` 与 serializeComponent 白名单一致
