"""编排链：布局连线 → 可达工具 → OpenAI payload（后端单一来源）

Task 3 范围：复刻前端 buildChatPayload 的 LLM 直连工具组件 + mcp_external
动态工具 + system_prompt 注入。executor/sequential/agent 中介与技能/意图
检测等链路由 Task 4 补充（见 task-3-report.md 局限记录）。
Task 4 补充：I1 toolEnabled 门控 / I2 system_prompt 字段名（prompt 与
activePromptContent）兼容 / I3 mcp_external toolNames 子集过滤 + memory
对话历史收口（见 task-4-report.md）。
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
    """LLM 组件可达工具全名（含 mcp_external 动态注册名）

    Task 4 必补：
    - I1：target.toolEnabled === false 时跳过该组件（复刻前端 tgt.toolEnabled !== false 门控）
    - I3：mcp_external 的 toolNames 显式子集优先；null/缺省 = 注册表前缀全量
      （复刻前端 mcpExternalToolNames：comp.toolNames != null ? 子集 : mcpAllTools 快照）
    """
    tools = []
    for conn in layout.get("connections", []):
        if conn.get("sourceCompId") != comp_id:
            continue
        target = _find_comp(layout, conn.get("targetCompId"))
        if not target:
            continue
        # I1：工具组件开关（serializeComponent 序列化 toolEnabled；缺省视为开启）
        if target.get("toolEnabled") is False:
            continue
        ttype = target.get("type")
        if ttype == "mcp_external":
            # 动态工具：serverId 前缀 + tool_registry 已注册全名
            prefix = f"mcp_ext_{target.get('serverId')}_"
            raw_names = target.get("toolNames")
            if isinstance(raw_names, list):
                # I3：显式子集（comp.toolNames）→ 只注入子集内的工具
                for n in raw_names:
                    if n:
                        tools.append(f"{prefix}{n}")
            else:
                # null（=全部）：注册表前缀全量
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


def _find_connected_memory(layout, comp_id):
    """查找连接到 LLM 的 memory 组件（目标端口 llm-mem-in；兼容序列化 targetPort
    与测试/旧格式 targetPortId 两种键名），复刻前端 findConnectedMemory 直连分支。"""
    for conn in layout.get("connections", []):
        if conn.get("targetCompId") != comp_id:
            continue
        port = conn.get("targetPort") or conn.get("targetPortId")
        if port != "llm-mem-in":
            continue
        src = _find_comp(layout, conn.get("sourceCompId"))
        if src and src.get("type") == "memory":
            return src
    return None


def compose_messages(layout, comp_id, message):
    """构造 messages：对话历史（memory 组件 / LLM 组件自身）+ system_prompt 注入 + 用户消息

    Task 4 补充（后端编排收口，避免新格式丢多轮上下文）：
    - 历史：复刻前端 buildChatPayload 的 messages 组装（memory 连接优先，否则 LLM 自身
      messages）；前端发送前已把当前用户消息 push 进历史 → 末尾同一条去重。
    - I2：system_prompt 组件字段兼容 prompt（测试/骨架）与 activePromptContent（真实布局
      serializeComponent 写该字段），取非空者。
    """
    messages = []
    mem = _find_connected_memory(layout, comp_id)
    if mem:
        messages.extend(mem.get("messages") or [])
    else:
        llm_comp = _find_comp(layout, comp_id)
        if llm_comp:
            messages.extend(llm_comp.get("messages") or [])
    # 去重：前端发送前已把当前用户消息 push 进历史 → 去掉末尾同一条
    if (messages and messages[-1].get("role") == "user"
            and messages[-1].get("content") == message):
        messages = messages[:-1]
    # system_prompt 注入（I2：prompt / activePromptContent 兼容）
    sys_content = None
    for conn in layout.get("connections", []):
        if conn.get("sourceCompId") != comp_id:
            continue
        target = _find_comp(layout, conn.get("targetCompId"))
        if target and target.get("type") == "system_prompt":
            sys_content = target.get("prompt") or target.get("activePromptContent")
            break
    if sys_content:
        replaced = False
        for i, m in enumerate(messages):
            if m.get("role") == "system":
                messages[i] = {"role": "system", "content": sys_content}
                replaced = True
                break
        if not replaced:
            messages.insert(0, {"role": "system", "content": sys_content})
    messages.append({"role": "user", "content": message})
    return messages


def build_payload(layout, comp_id, message, llm_config=None):
    """构造 OpenAI payload（复刻前端 buildChatPayload 的 messages/tools 部分）"""
    cfg = llm_config or {}
    tools = resolve_tools(layout, comp_id)
    payload = {
        "model": cfg.get("model") or get_config()["model"],
        "messages": compose_messages(layout, comp_id, message),
        # llm_config 键兼容 camelCase（前端）与 snake_case（测试/外部调用方）
        "max_tokens": (cfg.get("maxTokens") or cfg.get("max_tokens")
                       or get_config()["max_tokens"]),
        "temperature": (cfg.get("temperature")
                        if cfg.get("temperature") is not None
                        else get_config()["temperature"]),
    }
    if tools:
        payload["tools"] = tool_registry.get_definitions_by_names(tools)
    return payload
