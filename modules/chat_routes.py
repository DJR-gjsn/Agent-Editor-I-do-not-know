"""
聊天路由模块 — /api/chat SSE 流式接口
从 server.py 抽取，职责：LLM 对话 + 智能模式技能激活 + 工具调用循环
"""

import json
import logging
import threading
import time

from flask import g, request

from . import tool_registry
from .llm_client import chat_with_tools
from .utils import make_sse_response, sse_error, sse_done

# ============================================================
# 智能模式：use_skill 工具 — LLM 自主选择技能
# ============================================================
# 存储当前请求可用的技能数据（由 /api/chat 动态设置）
_smart_skills_cache = {}  # {skill_id: {"name": ..., "prompt": ..., "tools": [...]}}
_skills_cache_lock = threading.Lock()

USE_SKILL_DEFINITION = {
    "name": "use_skill",
    "description": (
        "激活一个专业技能，获取该技能的工作流程指导和推荐工具列表。"
        "适合文档处理、设计、搜索等复杂任务。简单问答无需调用。"
        "激活后的指导会告诉你正确的工具组合和使用顺序，提升输出质量。"
        "不确定是否该用时，优先激活——它能帮你避免遗漏关键步骤。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "skill_id": {
                "type": "string",
                "description": "要激活的技能 ID，务必根据用户任务选择合适的技能",
            },
        },
        "required": ["skill_id"],
    },
}

# 记录当前请求中已激活的技能（避免 LLM 对同一技能反复调用 use_skill）
_activated_skills = {}  # {skill_id: activation_count}

def _exec_use_skill(args: dict) -> str:
    """执行 use_skill 工具 — 返回技能 prompt 并引导后续操作"""
    skill_id = args.get("skill_id", "")
    if not skill_id:
        return "错误：请提供 skill_id 参数"
    with _skills_cache_lock:
        skill_data = _smart_skills_cache.get(skill_id)
        if not skill_data:
            available = ", ".join(_smart_skills_cache.keys()) if _smart_skills_cache else "（无）"
            return (
                f"❌ 技能 '{skill_id}' 不存在！\n"
                f"可用的技能（必须使用这些确切 ID）：{available}\n"
                f"请从上述列表中选择一个确切的 skill_id 重新调用 use_skill，不要自己编造 ID。"
            )

    # 检测重复激活：同一技能只返回完整 prompt 一次（加锁保证并发计数正确）
    with _skills_cache_lock:
        count = _activated_skills.get(skill_id, 0)
        _activated_skills[skill_id] = count + 1

    if count >= 1:
        # 已激活过：不再返回完整 prompt，强制 LLM 使用已有指导
        name = skill_data.get("name", skill_id)
        return (
            f"⚠️ 技能 '{name}' 已经激活过了！你已拥有该技能的全部指导。\n"
            f"请立即使用已获得的指导开始工作，不要再调用 use_skill。\n"
            f"按照之前返回的专业指导中的工作流程，使用推荐的工具完成任务。"
        )

    # 首次激活：返回完整 prompt
    tools_str = ", ".join(skill_data.get("tools", [])) if skill_data.get("tools") else "无"
    name = skill_data.get("name", skill_id)
    prompt = skill_data.get("prompt", "")
    result = (
        f"✅ 已激活技能：{name}\n\n"
        f"## 专业指导\n\n{prompt}\n\n"
        f"---\n"
        f"🔧 推荐使用的工具：{tools_str}\n\n"
        f"⚠️ 重要：请严格按照上述指导中的工作流程，使用指定的工具完成任务。"
        f"不要跳过任何步骤，不要再调用 use_skill（该技能已激活）。"
    )
    return result

tool_registry.register("use_skill", USE_SKILL_DEFINITION, _exec_use_skill)


def _inject_system_prompt(messages, system_prompt):
    """向消息列表注入或替换 system 消息。
    只在需要修改时才拷贝列表，避免无 system_prompt 时的无效拷贝。"""
    if not system_prompt:
        return messages  # 无需拷贝，直接返回
    result = list(messages)
    sys_msg = {"role": "system", "content": system_prompt}
    for i, m in enumerate(result):
        if m.get("role") == "system":
            result[i] = sys_msg
            return result
    result.insert(0, sys_msg)
    return result


def _append_sys_hints(messages, hint):
    """向现有 system 消息追加提示（日期/session 等）；无 system 消息则前置一条。

    Task 4 新格式专用：system 人设已由 orchestrator.compose_messages 注入
    messages[0]，这里只追加通用提示，不覆盖组件人设内容。"""
    result = list(messages)
    for i, m in enumerate(result):
        if m.get("role") == "system":
            result[i] = dict(m, content=str(m.get("content", "")) + hint)
            return result
    result.insert(0, {"role": "system", "content": hint})
    return result


logger = logging.getLogger("wybzd")

# 运行时配置（get_config() 结果），由 register_chat_routes 注入
_cfg = {}


def register_chat_routes(app, http_session, cfg):
    """注册 /api/chat 路由。http_session: 共享 HTTP Session；cfg: get_config() 结果"""
    global _cfg
    _cfg = cfg

    @app.route("/api/chat", methods=["POST"])
    def chat():
        """LLM 对话接口 — 真正的 SSE 流式返回 + Tool Call 自动循环

        Task 4 双格式（阶段2核心）：
        - 新格式：layout/comp_id/message/llm_config → orchestrator 后端编排
          （build_payload → 转换进既有 chat_with_tools 流；SSE 事件流与旧格式完全一致）
        - 旧格式：messages/tools 直接透传（过渡兼容，chat.js 独立对话页等仍使用）
        """
        data = request.get_json(force=True, silent=True) or {}
        # ── 格式分发：新格式 → orchestrator 后端编排 ──
        if data.get("layout") is not None and data.get("comp_id"):
            from . import orchestrator
            llm_cfg = data.get("llm_config") or {}
            payload = orchestrator.build_payload(
                data["layout"], data["comp_id"],
                data.get("message", ""), llm_cfg)
            # OpenAI payload → 既有 chat_with_tools 流参数
            # （llm_config 键 camelCase（前端）/ snake_case（测试）统一为 snake_case）
            data["messages"] = payload["messages"]
            data["model"] = payload["model"]
            data["max_tokens"] = payload["max_tokens"]
            data["temperature"] = payload["temperature"]
            data["tools"] = payload.get("tools")
            data["tool_names"] = None
            data["api_base"] = (llm_cfg.get("apiBase") or llm_cfg.get("api_base")
                                or _cfg["api_base"])
            data["api_key"] = (llm_cfg.get("apiKey") or llm_cfg.get("api_key")
                               or _cfg["api_key"])
            data["max_tool_rounds"] = (llm_cfg.get("maxToolRounds")
                                       or llm_cfg.get("max_tool_rounds")
                                       or data.get("max_tool_rounds") or 50)
            # 组件配置：搜索轮数上限 / 单次结果条数（由 Web Search 组件面板确定）
            data["max_search_rounds"] = (llm_cfg.get("maxSearchRounds")
                                         or llm_cfg.get("max_search_rounds")
                                         or data.get("max_search_rounds") or 10)
            data["max_results"] = (llm_cfg.get("maxResults")
                                   or llm_cfg.get("max_results")
                                   or data.get("max_results"))
            # compose_messages 已把 system 消息放 messages[0]（组件人设）
            # → 标记避免默认 system_prompt 覆盖组件内容
            if (payload["messages"]
                    and payload["messages"][0].get("role") == "system"):
                data["_sys_prompt_injected"] = True
        # 旧格式：messages/tools 直接透传（过渡兼容，无需转换）
        messages = data.get("messages", [])
        model = data.get("model", _cfg["model"])
        api_base = data.get("api_base") or _cfg["api_base"]
        api_key = data.get("api_key") or _cfg["api_key"]
        logger.info("收到请求: max_search_rounds=%s, max_tool_rounds=%s, tool_names=%s",
                    data.get("max_search_rounds"), data.get("max_tool_rounds"), data.get("tool_names"))

        # 注入 system prompt + 当前日期 + session_id
        today_str = time.strftime("%Y年%m月%d日 %A")
        session_id = data.get("session_id", "default")
        date_hint = f"\n\n[当前日期: {today_str}]"
        session_hint = f"\n[session_id: {session_id}] — 调用任何 Office 工具时请使用此 session_id"
        sys_prompt = data.get("system_prompt") or _cfg.get("system_prompt", "")
        # 组件配置提示：Web Search 组件面板设置的单次结果条数（max_results）
        max_results = data.get("max_results")
        if max_results:
            date_hint += (f"\n[搜索设置: 调用 web_search 工具时请将 max_results 设为 {max_results}"
                          f"（默认 {max_results} 条结果）]")
        if data.get("_sys_prompt_injected"):
            # 新格式：system 消息已由 orchestrator 注入（组件人设）→ 只追加日期/session 提示
            final_messages = _append_sys_hints(messages, date_hint + session_hint)
        else:
            # 旧格式：默认 system_prompt 注入（_inject_system_prompt 内部仅在需要时拷贝）
            final_messages = _inject_system_prompt(
                messages,
                sys_prompt + date_hint + session_hint,
            )

        # 消息长度检查
        total_len = sum(len(str(m.get("content", ""))) for m in final_messages)
        if total_len > 100000:
            def _too_large():
                yield sse_error("消息总长度超过限制，请精简对话")
            return make_sse_response(_too_large())

        # === 智能模式：填充技能缓存 + 注入 use_skill 工具 ===
        smart_mode = data.get("smart_mode", False)
        if smart_mode:
            available_skills = data.get("available_skills", [])
            with _skills_cache_lock:
                _activated_skills.clear()
                _smart_skills_cache.clear()
                for sk in available_skills:
                    sid = sk.get("id", "")
                    if sid:
                        # 从 mcp_skills 模块读取 prompt
                        try:
                            from modules.mcp_skills import SKILLS
                            skill_data = SKILLS.get(sid, {})
                            prompt = skill_data.get("system_prompt", "")
                        except Exception:
                            prompt = ""
                        _smart_skills_cache[sid] = {
                            "name": sk.get("name", sid),
                            "prompt": prompt,
                            "tools": [],
                        }
                logger.info("智能模式: 可用技能=%s", list(_smart_skills_cache.keys()))
            # 注入智能模式提示
            skill_names = [s.get("name", s.get("id", "")) for s in available_skills]
            skill_list_str = "\n".join(
                f"  - {s.get('id', '')}: {s.get('name', '')}"
                for s in available_skills
            )
            smart_hint = (
                f"\n\n## 🤖 智能模式 — 按需使用技能\n\n"
                f"你拥有以下专业技能，**在需要时**可调用 use_skill 激活：\n\n"
                f"{skill_list_str}\n\n"
                f"## 何时使用技能\n"
                f"- 任务涉及文档创建/编辑/转换/导出 PDF → use_skill(\"document\")\n"
                f"- 任务涉及前端设计/网页/UI/UX → use_skill(\"frontend-design\") 或 use_skill(\"ui-ux-pro-max\")\n"
                f"- 任务涉及搜索或查找资源 → use_skill(\"find-skills\")\n"
                f"- 任务涉及创建 Skill 文件 → use_skill(\"skill-creator\")\n"
                f"- 需要高级技巧或最佳实践 → use_skill(\"superpowers\")\n"
                f"- 沟通/说服/话术类任务 → use_skill(\"pua\")\n\n"
                f"## 何时不用技能\n"
                f"- 简单问答、闲聊、通用知识询问 → 直接回复，无需技能\n"
                f"- 纯工具操作（如单次搜索、简单计算）→ 直接用工具即可\n\n"
                f"技能激活后会返回专业指导，告诉你该用什么工具、按什么流程操作。不确定时优先激活。"
            )
            sys_prompt = sys_prompt + smart_hint

        # === 收集 tools ===
        tools = data.get("tools")
        tool_names = data.get("tool_names")
        if not tools and tool_names:
            tools = tool_registry.get_definitions_by_names(tool_names)
            logger.info("tool_names from request: %s, matched: %d", tool_names, len(tools))
        # 智能模式下确保 use_skill 工具可用（带 enum 约束避免 LLM 编造 skill_id）
        if smart_mode:
            if tools is None:
                tools = []
            has_use_skill = any(t.get("function", {}).get("name") == "use_skill" for t in tools)
            if not has_use_skill:
                # 动态构建 use_skill 定义，包含准确的 skill_id 枚举
                with _skills_cache_lock:
                    skill_ids = list(_smart_skills_cache.keys()) if _smart_skills_cache else [s.get("id", "") for s in available_skills]
                use_skill_dynamic = {
                    "name": "use_skill",
                    "description": (
                        "激活一个专业技能，获取该技能的工作流程指导和推荐工具列表。"
                        "适合文档处理、设计、搜索等复杂任务。简单问答无需调用。"
                        "可用技能: " + ", ".join(skill_ids) + "。"
                        "你必须使用下面 enum 中列出的确切 skill_id 值，不要自己编造。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "skill_id": {
                                "type": "string",
                                "description": "要激活的技能 ID。必须从可用技能列表中选择，使用 enum 中列出的确切值。",
                                "enum": skill_ids,
                            },
                        },
                        "required": ["skill_id"],
                    },
                }
                tools.append({"type": "function", "function": use_skill_dynamic})

        # 检测 Office 工具存在
        office_tools_present = any(
            t["function"]["name"].startswith(("excel_", "word_", "ppt_"))
            for t in (tools or [])
        )

        def generate():
            # 将当前请求的 API 配置注入 Flask g，供 plan/executor 等工具在执行时读取
            g._api_config = {
                "api_base": api_base,
                "api_key": api_key,
                "model": model,
            }
            search_count = 0
            SEARCH_HARD_LIMIT = data.get("max_search_rounds", 10)
            SEARCH_SOFT_BRAKE = max(1, SEARCH_HARD_LIMIT - 2)   # 提前 2 轮提醒
            logger.info("搜索限制: 硬上限=%d, 软提醒=%d (来自请求 max_search_rounds=%s)", SEARCH_HARD_LIMIT, SEARCH_SOFT_BRAKE, data.get("max_search_rounds", "未传"))

            events = chat_with_tools(
                final_messages,
                tools=tools,
                http_session=http_session,
                api_base=api_base,
                api_key=api_key,
                model=model,
                max_tokens=data.get("max_tokens", _cfg["max_tokens"]),
                temperature=data.get("temperature", _cfg["temperature"]),
                max_rounds=int(data.get("max_tool_rounds", 50)),
                stream=True,  # 真正的 SSE 流式传输
            )

            from modules.utils import with_heartbeat
            hb_events = with_heartbeat(events, idle_seconds=15)
            try:
                for hb_kind, hb_payload in hb_events:
                    if hb_kind == "heartbeat":
                        yield ": keep-alive\n\n"
                        continue
                    event = hb_payload
                    etype = event["type"]

                    if etype == "reasoning":
                        # 思考过程（DeepSeek Reasoner 等推理模型）
                        yield f"data: {json.dumps({'choices': [{'delta': {'reasoning_content': event['content']}}]})}\n\n"

                    elif etype == "content":
                        yield f"data: {json.dumps({'choices': [{'delta': {'content': event['content']}}]})}\n\n"

                    elif etype == "tool_call":
                        # 流式模式单个 tool_call
                        if "name" in event:
                            logger.info("LLM tool call: %s(%s)", event["name"], event.get("arguments", "")[:100])
                            yield f"data: {json.dumps({'tool_calls': [{'id': event.get('id', ''), 'name': event['name'], 'arguments': event.get('arguments', '')}]})}\n\n"
                        # 非流式模式批量 tool_calls
                        elif "calls" in event:
                            for tc in event["calls"]:
                                logger.info("LLM tool call: %s(%s)", tc["name"], tc.get("arguments", "")[:100])
                            yield f"data: {json.dumps({'tool_calls': [{'id': tc.get('id', ''), 'name': tc['name'], 'arguments': tc['arguments']} for tc in event['calls']]})}\n\n"

                    elif etype == "tool_result":
                        result = event["result"]
                        # ── 搜索刹车（硬限制） ──
                        if event["name"] == "web_search":
                            search_count += 1
                            if search_count > SEARCH_HARD_LIMIT:
                                # 硬刹车：告知用户 + 拒绝 LLM
                                yield f"data: {json.dumps({'choices': [{'delta': {'content': f'\\n\\n⛔ 搜索次数已达上限（{SEARCH_HARD_LIMIT}次），不再执行新的搜索。请基于已有信息回复。\\n\\n'}}]})}\n\n"
                                result = (
                                    f"⛔ 搜索已被系统强制拒绝（第{search_count}次搜索，上限{SEARCH_HARD_LIMIT}次）。\n"
                                    f"你已经进行了 {search_count} 次搜索，已达上限。\n"
                                    f"请立即停止调用 web_search，直接基于已有的搜索结果生成最终回复。\n"
                                    f"不要再尝试任何搜索，否则对话将被强制终止。"
                                )
                            elif office_tools_present and search_count >= SEARCH_SOFT_BRAKE:
                                # 软刹车：提醒即将达到上限（不强制推 Office 工具）
                                result = result + (
                                    f"\n\n⚠️ 提醒（第{search_count}次搜索，上限{SEARCH_HARD_LIMIT}次）：\n"
                                    f"搜索次数即将达到上限！请基于已有信息继续工作，\n"
                                    f"必要时可使用可用工具生成最终交付物。"
                                )
                        logger.info("tool result: %s -> %s", event["name"], result[:100])
                        yield f"data: {json.dumps({'tool_result': {'name': event['name'], 'result': result[:8000]}})}\n\n"

                    elif etype == "error":
                        logger.error("chat error: %s", event["error"])
                        yield sse_error(event["error"])
                        return

                    elif etype == "done":
                        yield sse_done()
                        return
            finally:
                hb_events.close()

        return make_sse_response(generate())

    return app
