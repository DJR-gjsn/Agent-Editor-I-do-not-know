"""编排链测试：布局连线 → 工具注入 → payload"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules import orchestrator
from modules import tool_registry


def _layout(components, connections):
    return {"components": components, "connections": connections}


class TestOrchestrator(unittest.TestCase):
    def setUp(self):
        tool_registry.register("_orch_test_tool", {"name": "_orch_test_tool"},
                               lambda args: "ok")
        self.addCleanup(tool_registry.unregister, "_orch_test_tool")

    def test_direct_llm_tool_connection(self):
        # LLM 直连一个工具组件 → 工具注入
        layout = _layout(
            [{"id": "llm1", "type": "llm"},
             {"id": "tz", "type": "mcp_zip"}],
            [{"sourceCompId": "llm1", "sourcePortId": "llm-out",
              "targetCompId": "tz", "targetPortId": "in"}])
        tools = orchestrator.resolve_tools(layout, "llm1")
        self.assertIn("zip_create", tools)
        self.assertIn("zip_extract", tools)

    def test_mcp_external_dynamic_tool(self):
        # mcp_external 组件：工具名来自 tool_registry 动态注册
        tool_registry.register("mcp_ext_git_echo", {"name": "mcp_ext_git_echo"},
                               lambda args: "ok")
        self.addCleanup(tool_registry.unregister, "mcp_ext_git_echo")
        layout = _layout(
            [{"id": "llm1", "type": "llm"},
             {"id": "ext", "type": "mcp_external", "serverId": "git"}],
            [{"sourceCompId": "llm1", "sourcePortId": "llm-out",
              "targetCompId": "ext", "targetPortId": "mcp-ext-in"}])
        tools = orchestrator.resolve_tools(layout, "llm1")
        self.assertIn("mcp_ext_git_echo", tools)

    def test_build_payload_shape(self):
        layout = _layout(
            [{"id": "llm1", "type": "llm"},
             {"id": "tz", "type": "calculator"}],
            [{"sourceCompId": "llm1", "sourcePortId": "llm-out",
              "targetCompId": "tz", "targetPortId": "in"}])
        payload = orchestrator.build_payload(
            layout, "llm1", "1+1=?", {"apiBase": "http://x", "model": "m"})
        self.assertIn("messages", payload)
        self.assertIn("tools", payload)
        self.assertEqual(payload["messages"][-1]["content"], "1+1=?")

    def test_system_prompt_injection(self):
        layout = _layout(
            [{"id": "llm1", "type": "llm"},
             {"id": "sp", "type": "system_prompt", "prompt": "你是测试助手"}],
            [{"sourceCompId": "llm1", "sourcePortId": "llm-out",
              "targetCompId": "sp", "targetPortId": "in"}])
        messages = orchestrator.compose_messages(layout, "llm1", "hi")
        self.assertTrue(any("测试助手" in str(m.get("content", "")) for m in messages))


if __name__ == "__main__":
    unittest.main()
