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

    # ── Task 4 必补：I1 toolEnabled 门控 ──
    def test_tool_enabled_false_skips_component(self):
        # toolEnabled === false → 不注入该组件工具（前端 tgt.toolEnabled !== false 门控）
        layout = _layout(
            [{"id": "llm1", "type": "llm"},
             {"id": "calc", "type": "calculator", "toolEnabled": False}],
            [{"sourceCompId": "llm1", "sourcePortId": "llm-out",
              "targetCompId": "calc", "targetPortId": "in"}])
        self.assertEqual(orchestrator.resolve_tools(layout, "llm1"), [])

    def test_tool_enabled_true_or_absent_injects(self):
        # toolEnabled 未设置（默认开启）与显式 true 都注入
        layout = _layout(
            [{"id": "llm1", "type": "llm"},
             {"id": "c1", "type": "calculator"},
             {"id": "c2", "type": "time_query", "toolEnabled": True}],
            [{"sourceCompId": "llm1", "sourcePortId": "llm-out",
              "targetCompId": "c1", "targetPortId": "in"},
             {"sourceCompId": "llm1", "sourcePortId": "llm-out",
              "targetCompId": "c2", "targetPortId": "in"}])
        tools = orchestrator.resolve_tools(layout, "llm1")
        self.assertIn("calculator", tools)
        self.assertIn("get_current_time", tools)

    # ── Task 4 必补：I2 system_prompt 字段名兼容（真实布局 serializeComponent 写 activePromptContent）──
    def test_system_prompt_active_prompt_content_field(self):
        layout = _layout(
            [{"id": "llm1", "type": "llm"},
             {"id": "sp", "type": "system_prompt",
              "activePromptContent": "你是人设字段版助手"}],
            [{"sourceCompId": "llm1", "sourcePortId": "llm-out",
              "targetCompId": "sp", "targetPortId": "in"}])
        messages = orchestrator.compose_messages(layout, "llm1", "hi")
        self.assertTrue(any("人设字段版助手" in str(m.get("content", "")) for m in messages))

    # ── Task 4 必补：I3 mcp_external toolNames 显式子集（null=全部）──
    def test_mcp_external_tool_names_subset(self):
        tool_registry.register("mcp_ext_git_echo", {"name": "mcp_ext_git_echo"},
                               lambda args: "ok")
        tool_registry.register("mcp_ext_git_status", {"name": "mcp_ext_git_status"},
                               lambda args: "ok")
        self.addCleanup(tool_registry.unregister, "mcp_ext_git_echo")
        self.addCleanup(tool_registry.unregister, "mcp_ext_git_status")
        layout = _layout(
            [{"id": "llm1", "type": "llm"},
             {"id": "ext", "type": "mcp_external", "serverId": "git",
              "toolNames": ["echo"]}],
            [{"sourceCompId": "llm1", "sourcePortId": "llm-out",
              "targetCompId": "ext", "targetPortId": "mcp-ext-in"}])
        tools = orchestrator.resolve_tools(layout, "llm1")
        self.assertEqual(tools, ["mcp_ext_git_echo"])

    def test_mcp_external_tool_names_null_means_all(self):
        tool_registry.register("mcp_ext_git_echo", {"name": "mcp_ext_git_echo"},
                               lambda args: "ok")
        tool_registry.register("mcp_ext_git_status", {"name": "mcp_ext_git_status"},
                               lambda args: "ok")
        self.addCleanup(tool_registry.unregister, "mcp_ext_git_echo")
        self.addCleanup(tool_registry.unregister, "mcp_ext_git_status")
        layout = _layout(
            [{"id": "llm1", "type": "llm"},
             {"id": "ext", "type": "mcp_external", "serverId": "git",
              "toolNames": None}],
            [{"sourceCompId": "llm1", "sourcePortId": "llm-out",
              "targetCompId": "ext", "targetPortId": "mcp-ext-in"}])
        tools = orchestrator.resolve_tools(layout, "llm1")
        self.assertIn("mcp_ext_git_echo", tools)
        self.assertIn("mcp_ext_git_status", tools)

    # ── 记忆历史：memory 组件连接 → 对话历史进入 messages（复刻前端 buildChatPayload）──
    def test_memory_history_injected(self):
        layout = _layout(
            [{"id": "llm1", "type": "llm"},
             {"id": "mem", "type": "memory",
              "messages": [{"role": "user", "content": "上一轮问题"},
                           {"role": "assistant", "content": "上一轮回答"}]}],
            [{"sourceCompId": "mem", "sourcePortId": "mem-out",
              "targetCompId": "llm1", "targetPortId": "llm-mem-in"}])
        messages = orchestrator.compose_messages(layout, "llm1", "新问题")
        contents = [m.get("content", "") for m in messages]
        self.assertIn("上一轮问题", contents)
        self.assertIn("上一轮回答", contents)
        # 最新用户消息在末尾
        self.assertEqual(messages[-1]["content"], "新问题")

    def test_memory_history_dedup_current_user_message(self):
        # 前端发送前已把当前用户消息 push 进 memory.messages → 末尾同一条不重复
        layout = _layout(
            [{"id": "llm1", "type": "llm"},
             {"id": "mem", "type": "memory",
              "messages": [{"role": "user", "content": "hi"}]}],
            [{"sourceCompId": "mem", "sourcePortId": "mem-out",
              "targetCompId": "llm1", "targetPortId": "llm-mem-in"}])
        messages = orchestrator.compose_messages(layout, "llm1", "hi")
        users = [m for m in messages if m.get("role") == "user"]
        self.assertEqual(len(users), 1)
        self.assertEqual(users[0]["content"], "hi")


if __name__ == "__main__":
    unittest.main()
