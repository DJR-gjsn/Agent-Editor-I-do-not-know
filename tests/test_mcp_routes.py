"""MCP 管理路由测试（Flask test client）"""
import os
import sys
import unittest
import uuid

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
        base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "data", "vector_store", ".test_tmp")
        os.makedirs(base, exist_ok=True)
        cls.tmpdir = os.path.join(base, "mcp_" + uuid.uuid4().hex[:10])
        os.makedirs(cls.tmpdir, exist_ok=True)
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

    def test_test_endpoint_uses_saved_config(self):
        # 先创建（body 含 command），test 用空 body 也应成功（合并已存配置）
        self.client.post("/api/mcp/servers", json=self._stdio_body("sv"))
        r = self.client.post("/api/mcp/servers/sv/test", json={})
        body = r.get_json()
        self.assertTrue(body["success"], body)
        self.assertEqual(body["tool_count"], 3)

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
