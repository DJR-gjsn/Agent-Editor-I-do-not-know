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
        client = MCPClient(transport, timeout=2)
        with self.assertRaises(MCPError):
            client.initialize()
        client.close()


if __name__ == "__main__":
    unittest.main()
