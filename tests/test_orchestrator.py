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


    # ── Task 5：中介链收口 — executor ──
    def test_executor_chain_injects_downstream_tools(self):
        # LLM → executor → 工具端口（exec-tool-N）连到的工具组件注入，按端口顺序
        layout = _layout(
            [{"id": "llm1", "type": "llm"},
             {"id": "exec", "type": "executor"},
             {"id": "calc", "type": "calculator"},
             {"id": "ws", "type": "web_search"}],
            [{"sourceCompId": "llm1", "sourcePortId": "llm-out",
              "targetCompId": "exec", "targetPortId": "exec-llm-in"},
             {"sourceCompId": "exec", "sourcePortId": "exec-tool-1",
              "targetCompId": "calc", "targetPortId": "in"},
             {"sourceCompId": "exec", "sourcePortId": "exec-tool-2",
              "targetCompId": "ws", "targetPortId": "in"}])
        tools = orchestrator.resolve_tools(layout, "llm1")
        self.assertEqual(tools, ["calculator", "web_search"])

    def test_executor_chain_mediator_tool_enabled_false(self):
        # 中介自身 toolEnabled === false → 整链不注入（前端 executor case 门控）
        layout = _layout(
            [{"id": "llm1", "type": "llm"},
             {"id": "exec", "type": "executor", "toolEnabled": False},
             {"id": "calc", "type": "calculator"}],
            [{"sourceCompId": "llm1", "sourcePortId": "llm-out",
              "targetCompId": "exec", "targetPortId": "exec-llm-in"},
             {"sourceCompId": "exec", "sourcePortId": "exec-tool-1",
              "targetCompId": "calc", "targetPortId": "in"}])
        self.assertEqual(orchestrator.resolve_tools(layout, "llm1"), [])

    def test_executor_chain_downstream_tool_enabled_false(self):
        # 下游工具组件 toolEnabled === false → 跳过（与直连路径同一门控规则）
        layout = _layout(
            [{"id": "llm1", "type": "llm"},
             {"id": "exec", "type": "executor"},
             {"id": "calc", "type": "calculator", "toolEnabled": False},
             {"id": "ws", "type": "web_search"}],
            [{"sourceCompId": "llm1", "sourcePortId": "llm-out",
              "targetCompId": "exec", "targetPortId": "exec-llm-in"},
             {"sourceCompId": "exec", "sourcePortId": "exec-tool-1",
              "targetCompId": "calc", "targetPortId": "in"},
             {"sourceCompId": "exec", "sourcePortId": "exec-tool-2",
              "targetCompId": "ws", "targetPortId": "in"}])
        tools = orchestrator.resolve_tools(layout, "llm1")
        self.assertEqual(tools, ["web_search"])

    def test_executor_chain_mcp_external_subset(self):
        # executor 下游 mcp_external：toolNames 显式子集 → 只注入子集动态全名
        tool_registry.register("mcp_ext_git_echo", {"name": "mcp_ext_git_echo"},
                               lambda args: "ok")
        tool_registry.register("mcp_ext_git_status", {"name": "mcp_ext_git_status"},
                               lambda args: "ok")
        self.addCleanup(tool_registry.unregister, "mcp_ext_git_echo")
        self.addCleanup(tool_registry.unregister, "mcp_ext_git_status")
        layout = _layout(
            [{"id": "llm1", "type": "llm"},
             {"id": "exec", "type": "executor"},
             {"id": "ext", "type": "mcp_external", "serverId": "git",
              "toolNames": ["echo"]}],
            [{"sourceCompId": "llm1", "sourcePortId": "llm-out",
              "targetCompId": "exec", "targetPortId": "exec-llm-in"},
             {"sourceCompId": "exec", "sourcePortId": "exec-tool-1",
              "targetCompId": "ext", "targetPortId": "mcp-ext-in"}])
        self.assertEqual(orchestrator.resolve_tools(layout, "llm1"),
                         ["mcp_ext_git_echo"])

    def test_executor_chain_dynamic_port_count(self):
        # execPortCount 决定端口数（前端可动态加端口）；超出计数的端口连线忽略
        layout = _layout(
            [{"id": "llm1", "type": "llm"},
             {"id": "exec", "type": "executor", "execPortCount": 2},
             {"id": "c1", "type": "calculator"},
             {"id": "c2", "type": "time_query"},
             {"id": "c3", "type": "web_search"}],
            [{"sourceCompId": "llm1", "sourcePortId": "llm-out",
              "targetCompId": "exec", "targetPortId": "exec-llm-in"},
             {"sourceCompId": "exec", "sourcePortId": "exec-tool-1",
              "targetCompId": "c1", "targetPortId": "in"},
             {"sourceCompId": "exec", "sourcePortId": "exec-tool-2",
              "targetCompId": "c2", "targetPortId": "in"},
             {"sourceCompId": "exec", "sourcePortId": "exec-tool-3",
              "targetCompId": "c3", "targetPortId": "in"}])
        tools = orchestrator.resolve_tools(layout, "llm1")
        self.assertEqual(tools, ["calculator", "get_current_time"])

    def test_executor_chain_dedup(self):
        # 两个端口连同一工具组件 → 去重一次（前端 collectExecutorToolNames Set）
        layout = _layout(
            [{"id": "llm1", "type": "llm"},
             {"id": "exec", "type": "executor"},
             {"id": "calc", "type": "calculator"}],
            [{"sourceCompId": "llm1", "sourcePortId": "llm-out",
              "targetCompId": "exec", "targetPortId": "exec-llm-in"},
             {"sourceCompId": "exec", "sourcePortId": "exec-tool-1",
              "targetCompId": "calc", "targetPortId": "in"},
             {"sourceCompId": "exec", "sourcePortId": "exec-tool-2",
              "targetCompId": "calc", "targetPortId": "in"}])
        self.assertEqual(orchestrator.resolve_tools(layout, "llm1"),
                         ["calculator"])

    # ── Task 5：中介链收口 — sequential_executor ──
    def test_sequential_chain_ordered_steps(self):
        # 步骤端口顺序即收集顺序（seq-step-1..5）；file_ops 展开多工具
        layout = _layout(
            [{"id": "llm1", "type": "llm"},
             {"id": "seq", "type": "sequential_executor"},
             {"id": "ws", "type": "web_search"},
             {"id": "fo", "type": "file_ops"}],
            [{"sourceCompId": "llm1", "sourcePortId": "llm-out",
              "targetCompId": "seq", "targetPortId": "seq-in"},
             {"sourceCompId": "seq", "sourcePortId": "seq-step-1",
              "targetCompId": "ws", "targetPortId": "in"},
             {"sourceCompId": "seq", "sourcePortId": "seq-step-2",
              "targetCompId": "fo", "targetPortId": "in"}])
        tools = orchestrator.resolve_tools(layout, "llm1")
        self.assertEqual(tools, ["web_search", "file_read", "file_write",
                                 "glob_search", "grep_search", "file_edit"])

    def test_sequential_chain_no_mediator_gate(self):
        # 前端 sequential_executor case 无 toolEnabled 门控（与 executor/agent 不对称）
        # → 中介 toolEnabled=false 仍注入下游工具
        layout = _layout(
            [{"id": "llm1", "type": "llm"},
             {"id": "seq", "type": "sequential_executor", "toolEnabled": False},
             {"id": "ws", "type": "web_search"}],
            [{"sourceCompId": "llm1", "sourcePortId": "llm-out",
              "targetCompId": "seq", "targetPortId": "seq-in"},
             {"sourceCompId": "seq", "sourcePortId": "seq-step-1",
              "targetCompId": "ws", "targetPortId": "in"}])
        self.assertEqual(orchestrator.resolve_tools(layout, "llm1"),
                         ["web_search"])

    def test_sequential_chain_replaces_direct_tools(self):
        # 有序工具覆盖当前列表（前端 toolNames.length=0; push(...seqNames)）：
        # 直连 calculator 先收集，sequential 后出现 → 被替换
        layout = _layout(
            [{"id": "llm1", "type": "llm"},
             {"id": "calc", "type": "calculator"},
             {"id": "seq", "type": "sequential_executor"},
             {"id": "ws", "type": "web_search"}],
            [{"sourceCompId": "llm1", "sourcePortId": "llm-out",
              "targetCompId": "calc", "targetPortId": "in"},
             {"sourceCompId": "llm1", "sourcePortId": "llm-out",
              "targetCompId": "seq", "targetPortId": "seq-in"},
             {"sourceCompId": "seq", "sourcePortId": "seq-step-1",
              "targetCompId": "ws", "targetPortId": "in"}])
        self.assertEqual(orchestrator.resolve_tools(layout, "llm1"),
                         ["web_search"])

    # ── Task 5：中介链收口 — agent ──
    def test_agent_chain_injects_downstream_tools(self):
        # LLM → agent → agent-tool-N 端口连到的工具注入（端口顺序、去重追加）
        layout = _layout(
            [{"id": "llm1", "type": "llm"},
             {"id": "ag", "type": "agent"},
             {"id": "calc", "type": "calculator"},
             {"id": "tq", "type": "time_query"},
             {"id": "calc2", "type": "calculator"}],
            [{"sourceCompId": "llm1", "sourcePortId": "llm-out",
              "targetCompId": "ag", "targetPortId": "agent-llm-in"},
             {"sourceCompId": "ag", "sourcePortId": "agent-tool-1",
              "targetCompId": "calc", "targetPortId": "in"},
             {"sourceCompId": "ag", "sourcePortId": "agent-tool-2",
              "targetCompId": "tq", "targetPortId": "in"},
             {"sourceCompId": "ag", "sourcePortId": "agent-tool-3",
              "targetCompId": "calc2", "targetPortId": "in"}])
        tools = orchestrator.resolve_tools(layout, "llm1")
        self.assertEqual(tools, ["calculator", "get_current_time"])

    def test_agent_chain_mediator_tool_enabled_false(self):
        # 中介自身 toolEnabled === false → 整链不注入（前端 agent case 门控）
        layout = _layout(
            [{"id": "llm1", "type": "llm"},
             {"id": "ag", "type": "agent", "toolEnabled": False},
             {"id": "ws", "type": "web_search"}],
            [{"sourceCompId": "llm1", "sourcePortId": "llm-out",
              "targetCompId": "ag", "targetPortId": "agent-llm-in"},
             {"sourceCompId": "ag", "sourcePortId": "agent-tool-1",
              "targetCompId": "ws", "targetPortId": "in"}])
        self.assertEqual(orchestrator.resolve_tools(layout, "llm1"), [])

    # ── Task 5：新格式连线键（前端 buildLayoutData 序列化写 sourcePort/targetPort）──
    def test_mediator_chain_new_format_port_keys(self):
        # 新格式布局（sourcePort 键，编辑器内嵌对话实际发送格式）也能解析中介链
        layout = _layout(
            [{"id": "llm1", "type": "llm"},
             {"id": "exec", "type": "executor"},
             {"id": "calc", "type": "calculator"}],
            [{"sourceCompId": "llm1", "sourcePort": "llm-out",
              "targetCompId": "exec", "targetPort": "exec-llm-in"},
             {"sourceCompId": "exec", "sourcePort": "exec-tool-1",
              "targetCompId": "calc", "targetPort": "in"}])
        self.assertEqual(orchestrator.resolve_tools(layout, "llm1"),
                         ["calculator"])

    # ── 重构遗漏修复：json_mode response_format / function_calling 自定义 tools ──
    def test_json_mode_response_format(self):
        layout = _layout(
            [{"id": "llm1", "type": "llm"},
             {"id": "jm", "type": "json_mode",
              "jsonSchema": {"type": "object",
                             "properties": {"answer": {"type": "string"}}}}],
            [{"sourceCompId": "llm1", "sourcePortId": "llm-out",
              "targetCompId": "jm", "targetPortId": "in"}])
        payload = orchestrator.build_payload(layout, "llm1", "hi", {})
        rf = payload.get("response_format")
        self.assertIsNotNone(rf)
        self.assertEqual(rf["type"], "json_schema")
        self.assertEqual(rf["json_schema"]["schema"]["properties"]["answer"]["type"], "string")

    def test_function_calling_custom_tools(self):
        layout = _layout(
            [{"id": "llm1", "type": "llm"},
             {"id": "fc", "type": "function_calling",
              "tools": [{"name": "my_custom_tool", "description": "自定义",
                         "parameters": {"type": "object", "properties": {}}}]},
             {"id": "tt", "type": "text_tools"}],  # text_analyze/text_format 在 meta 映射中
            [{"sourceCompId": "llm1", "sourcePortId": "llm-out",
              "targetCompId": "fc", "targetPortId": "in"},
             {"sourceCompId": "llm1", "sourcePortId": "llm-out",
              "targetCompId": "tt", "targetPortId": "in"}])
        # 注册内置工具（text_analyze），验证内置 + 自定义合并
        from modules import tool_registry as _tr
        _tr.register("text_analyze", {"name": "text_analyze"}, lambda a: "ok")
        self.addCleanup(_tr.unregister, "text_analyze")
        payload = orchestrator.build_payload(layout, "llm1", "hi", {})
        names = [t["function"]["name"] for t in payload.get("tools", [])]
        self.assertIn("text_analyze", names)     # 内置工具保留
        self.assertIn("my_custom_tool", names)   # 自定义工具并入

    def test_no_json_schema_no_response_format(self):
        layout = _layout(
            [{"id": "llm1", "type": "llm"},
             {"id": "jm", "type": "json_mode"}],
            [{"sourceCompId": "llm1", "sourcePortId": "llm-out",
              "targetCompId": "jm", "targetPortId": "in"}])
        payload = orchestrator.build_payload(layout, "llm1", "hi", {})
        self.assertNotIn("response_format", payload)


if __name__ == "__main__":
    unittest.main()
