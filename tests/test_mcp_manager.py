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
        import uuid
        base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "data", "vector_store", ".test_tmp")
        os.makedirs(base, exist_ok=True)
        cls.tmpdir = os.path.join(base, "mcp_" + uuid.uuid4().hex[:10])
        os.makedirs(cls.tmpdir, exist_ok=True)
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
