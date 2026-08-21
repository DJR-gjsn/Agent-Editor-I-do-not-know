"""编排链：布局连线 → 可达工具 → OpenAI payload（后端单一来源）

Task 3 范围：复刻前端 buildChatPayload 的 LLM 直连工具组件 + mcp_external
动态工具 + system_prompt 注入。executor/sequential/agent 中介与技能/意图
检测等链路由 Task 4 补充（见 task-3-report.md 局限记录）。
"""
from . import tool_registry
from .config import get_config
from .meta import _DATA

# 组件类型 → 内置工具名（单一来源：meta._DATA["tool_name_map"]，由 Task 1
# 从前端自动提取；此处不手写第二份映射，避免双源漂移。mcp_external 动态除外）
TOOL_NAME_MAP = dict(_DATA["tool_name_map"])
# 允许直接连 LLM 的工具组件类型（复刻前端 isToolComponent 集合）
TOOL_TYPES = set(TOOL_NAME_MAP.keys()) | {"mcp_external"}


def resolve_tools(layout, comp_id):
    """LLM 组件可达工具全名（含 mcp_external 动态注册名）"""
    tools = []
    for conn in layout.get("connections", []):
        if conn.get("sourceCompId") == comp_id:
            target = _find_comp(layout, conn.get("targetCompId"))
            if not target:
                continue
            ttype = target.get("type")
            if ttype == "mcp_external":
                # 动态工具：serverId 前缀 + tool_registry 已注册全名
                prefix = f"mcp_ext_{target.get('serverId')}_"
                for name in tool_registry.get_all_definitions():
                    fname = name["function"]["name"]
                    if fname.startswith(prefix):
                        tools.append(fname)
            elif ttype in TOOL_NAME_MAP:
                tools.extend(TOOL_NAME_MAP[ttype])
    return list(dict.fromkeys(tools))


def _find_comp(layout, comp_id):
    for c in layout.get("components", []):
        if c.get("id") == comp_id:
            return c
    return None


def compose_messages(layout, comp_id, message):
    """构造 messages：注入 system_prompt 组件内容"""
    messages = []
    for conn in layout.get("connections", []):
        if conn.get("sourceCompId") == comp_id:
            target = _find_comp(layout, conn.get("targetCompId"))
            if target and target.get("type") == "system_prompt" and target.get("prompt"):
                messages.append({"role": "system",
                                 "content": target["prompt"]})
                break
    messages.append({"role": "user", "content": message})
    return messages


def build_payload(layout, comp_id, message, llm_config=None):
    """构造 OpenAI payload（复刻前端 buildChatPayload 的 messages/tools 部分）"""
    cfg = llm_config or {}
    tools = resolve_tools(layout, comp_id)
    payload = {
        "model": cfg.get("model") or get_config()["model"],
        "messages": compose_messages(layout, comp_id, message),
        "max_tokens": cfg.get("maxTokens") or get_config()["max_tokens"],
        "temperature": cfg.get("temperature", get_config()["temperature"]),
    }
    if tools:
        payload["tools"] = tool_registry.get_definitions_by_names(tools)
    return payload
