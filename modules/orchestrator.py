"""编排链：布局连线 → 可达工具 → OpenAI payload（后端单一来源）

Task 3 范围：复刻前端 buildChatPayload 的 LLM 直连工具组件 + mcp_external
动态工具 + system_prompt 注入。executor/sequential/agent 中介与技能/意图
检测等链路由 Task 4 补充（见 task-3-report.md 局限记录）。
Task 4 补充：I1 toolEnabled 门控 / I2 system_prompt 字段名（prompt 与
activePromptContent）兼容 / I3 mcp_external toolNames 子集过滤 + memory
对话历史收口（见 task-4-report.md）。
Task 5 补充：中介链收口 — resolve_tools 支持 executor / sequential_executor /
agent 三种中介链（复刻前端 buildChatPayload 的 mediator case 语义），使新格式
对话对中介链下游工具正确注入（见 followup-orchestrator-report.md）。
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
    """LLM 组件可达工具全名（LLM 直连 + executor/sequential_executor/agent 中介链）

    Task 5 中介链收口（复刻前端 buildChatPayload 的 mediator case 语义）：
    - executor：门控中介自身 toolEnabled；exec-tool-1..N（N=execPortCount||5，前端
      可动态加端口）按端口序收集下游工具，去重追加（前端 collectExecutorToolNames
      的 Set 去重 + 仅追加不在列表中的）
    - sequential_executor：中介自身无 toolEnabled 门控（前端该 case 无门控，保留
      不对称）；seq-step-1..5 按步骤序收集，有序工具整体替换当前列表
      （前端 toolNames.length=0; push(...seqNames)）
    - agent：门控中介自身 toolEnabled；agent-tool-1..5 按端口序收集，去重追加
    下游工具组件统一走 _component_tool_names（toolEnabled 门控 / mcp_external
    动态全名 / meta TOOL_NAME_MAP），与直连路径同一提取规则。
    """
    tools = []
    for conn in layout.get("connections", []):
        if conn.get("sourceCompId") != comp_id:
            continue
        target = _find_comp(layout, conn.get("targetCompId"))
        if not target:
            continue
        ttype = target.get("type")
        if ttype == "sequential_executor":
            names = _collect_mediator_tools(layout, target)
            if names:
                tools = names  # 有序工具覆盖当前列表（前端 replace 语义）
        elif ttype in ("executor", "agent"):
            # 中介自身 toolEnabled === false → 整链跳过（前端这两个 case 有门控）
            if target.get("toolEnabled") is False:
                continue
            for n in _collect_mediator_tools(layout, target):
                if n not in tools:
                    tools.append(n)
        else:
            # 直连工具 / mcp_external（既有规则，Task 4 保持）
            tools.extend(_component_tool_names(target))
    return list(dict.fromkeys(tools))


def _component_tool_names(comp):
    """单个组件 → 工具名列表（直连路径与中介链共用同一提取规则）

    - toolEnabled === false → []（复刻前端 tgt.toolEnabled !== false 门控）
    - mcp_external → 动态注册全名（toolNames 显式子集优先；null/缺省 = 注册表
      前缀全量，复刻前端 mcpExternalToolNames）
    - 其余 → meta TOOL_NAME_MAP（单一来源，不手写第二份映射）
    """
    if comp.get("toolEnabled") is False:
        return []
    ttype = comp.get("type")
    if ttype == "mcp_external":
        prefix = f"mcp_ext_{comp.get('serverId')}_"
        raw_names = comp.get("toolNames")
        if isinstance(raw_names, list):
            return [f"{prefix}{n}" for n in raw_names if n]
        return [d["function"]["name"] for d in tool_registry.get_all_definitions()
                if d["function"]["name"].startswith(prefix)]
    return list(TOOL_NAME_MAP.get(ttype, []))


def _conn_source_port(conn):
    """连线源端口：新格式布局（前端 buildLayoutData/serializeConnections）写
    sourcePort；测试/旧格式写 sourcePortId —— 双键兼容（同 _find_connected_memory）。"""
    return conn.get("sourcePort") or conn.get("sourcePortId")


def _find_conn_from(layout, comp_id, port_id):
    """源组件+源端口的第一条连线（复刻前端 STATE.connections.find 语义）"""
    for conn in layout.get("connections", []):
        if (conn.get("sourceCompId") == comp_id
                and _conn_source_port(conn) == port_id):
            return conn
    return None


def _mediator_port_ids(mediator):
    """中介组件工具端口 id 列表（端口顺序即收集顺序）

    单一来源：meta._DATA["component_defs"][type].ports.outputs（前端旧实现
    collectExecutorToolNames / collectSequentialTools / collectAgentToolNames
    硬编码同名单）：
    - executor：exec-tool-1..N，N = execPortCount || meta outputs 数（前端
      renderExecutorPanel 可动态加端口，serializeComponent 写 execPortCount）
    - sequential_executor：seq-step-1..5（meta outputs，固定）
    - agent：agent-tool-1..5（meta outputs，固定）
    """
    ttype = mediator.get("type")
    outputs = (_DATA["component_defs"].get(ttype, {})
               .get("ports", {}).get("outputs", []))
    if ttype == "executor":
        count = mediator.get("execPortCount") or len(outputs) or 5
        return [f"exec-tool-{i}" for i in range(1, count + 1)]
    return [p.get("id") for p in outputs if p.get("id")]


def _collect_mediator_tools(layout, mediator):
    """收集中介组件工具端口连到的下游工具名（单层，复刻前端 collect*
    系列函数）

    - 端口按定义顺序遍历（executor 按 execPortCount 动态扩展）
    - 每端口取第一条连线（前端 STATE.connections.find）
    - 下游目标复用直接路径同一提取规则 _component_tool_names
    - 返回收集顺序列表（去重/替换由 resolve_tools 按前端语义处理）
    """
    names = []
    for port_id in _mediator_port_ids(mediator):
        conn = _find_conn_from(layout, mediator.get("id"), port_id)
        if not conn:
            continue
        target = _find_comp(layout, conn.get("targetCompId"))
        if target:
            names.extend(_component_tool_names(target))
    return names


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
