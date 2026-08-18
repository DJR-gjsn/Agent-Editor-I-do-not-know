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
        if self._started:
            return  # 幂等：已启动则直接返回，避免双重 start 产生孤儿进程
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
