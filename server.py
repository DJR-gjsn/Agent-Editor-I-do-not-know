"""
Agent编辑器V0.1 - Flask 后端
提供 Web 页面和 LLM API 代理（隐藏 API Key）
"""

import io
import json
import os
import sys
import tempfile
import threading
import time
import uuid
from collections import defaultdict
from pathlib import Path

from flask import Flask, Response, g, jsonify, render_template, request, stream_with_context, send_from_directory
from flask_compress import Compress

import requests

app = Flask(__name__)
Compress(app)

# 注册所有功能模块
from modules import register_all, tool_registry
from modules.config import get_config, has_api_key
from modules.llm_client import chat_with_tools
from modules.utils import make_sse_response, sse_event, sse_error, sse_done, setup_logging, get_logger

register_all(app)

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

    # 检测重复激活：同一技能只返回完整 prompt 一次
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

# ============================================================
# 日志
# ============================================================
setup_logging("wybzd")
logger = get_logger("wybzd")

# ============================================================
# 配置（从集中配置模块加载）
# ============================================================
_cfg = get_config()
API_BASE = _cfg["api_base"]
API_KEY = _cfg["api_key"]
MODEL = _cfg["model"]
MAX_TOKENS = _cfg["max_tokens"]
TEMPERATURE = _cfg["temperature"]
PORT = _cfg["port"]

# 复用 HTTP 连接池
http_session = requests.Session()
http_session.headers.update({"Content-Type": "application/json"})

# ============================================================
# 静态文件缓存（覆盖 debug 模式的 no-cache）
# ============================================================
STATIC_DIR = Path(__file__).parent / "static"


@app.route("/static/<path:filename>")
def static_files(filename):
    """自定义静态文件路由"""
    return send_from_directory(
        STATIC_DIR,
        filename,
        max_age=300,  # 5分钟缓存，开发阶段平衡性能与即时性
        conditional=True,
    )


@app.after_request
def _add_cache_headers(response):
    """为静态文件添加缓存头"""
    if request.path.startswith("/static/"):
        response.cache_control.max_age = 300
        response.cache_control.public = True
    return response


# ============================================================
# 请求频率限制
# ============================================================
_rate_limits = defaultdict(list)
_rate_lock = threading.Lock()
_RATE_WINDOW = 60
_RATE_MAX = 300
_last_cleanup = 0
_CLEANUP_INTERVAL = 300  # 每5分钟清理过期IP


@app.before_request
def rate_limit():
    """轻量级频率限制（静态文件、SSE 流、内部 API 除外）"""
    global _last_cleanup
    path = request.path
    if path.startswith("/static") or path.startswith("/api/chat") or path.startswith("/api/memory"):
        return
    ip = request.remote_addr or "127.0.0.1"
    now = time.time()

    with _rate_lock:
        # 清理当前 IP 的过期记录
        _rate_limits[ip] = [t for t in _rate_limits[ip] if now - t < _RATE_WINDOW]
        if len(_rate_limits[ip]) >= _RATE_MAX:
            return jsonify({"error": "请求过于频繁，请稍后重试"}), 429
        _rate_limits[ip].append(now)

        # 定期清理过期 IP 条目
        if now - _last_cleanup > _CLEANUP_INTERVAL:
            stale = [k for k, v in _rate_limits.items() if not v or now - v[-1] > _RATE_WINDOW]
            for k in stale:
                del _rate_limits[k]
            _last_cleanup = now


# ============================================================
# 辅助函数
# ============================================================
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


# ============================================================
# 路由
# ============================================================
@app.route("/")
def index():
    """管理后台"""
    return render_template("admin.html")


@app.route("/editor")
def editor_page():
    """Agent编辑器"""
    return render_template("index.html")


@app.route("/chat")
def chat_page():
    """前端 AI 对话页面"""
    return render_template("chat.html")


@app.route("/api/health")
def health():
    """健康检查"""
    return jsonify({"status": "ok", "timestamp": time.time()})


@app.route("/api/config")
def get_api_config():
    """返回当前配置（不暴露完整 API Key）"""
    return jsonify({
        "model": MODEL,
        "api_base": API_BASE,
        "has_api_key": has_api_key(),
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
    })


@app.route("/api/chat", methods=["POST"])
def chat():
    """LLM 对话接口 — 真正的 SSE 流式返回 + Tool Call 自动循环"""
    data = request.get_json(force=True)
    messages = data.get("messages", [])
    model = data.get("model", MODEL)
    api_base = data.get("api_base") or API_BASE
    api_key = data.get("api_key") or API_KEY
    logger.info("收到请求: max_search_rounds=%s, max_tool_rounds=%s, tool_names=%s",
                data.get("max_search_rounds"), data.get("max_tool_rounds"), data.get("tool_names"))

    # 注入 system prompt + 当前日期 + session_id
    today_str = time.strftime("%Y年%m月%d日 %A")
    session_id = data.get("session_id", "default")
    date_hint = f"\n\n[当前日期: {today_str}]"
    session_hint = f"\n[session_id: {session_id}] — 调用任何 Office 工具时请使用此 session_id"
    # 使用请求中的 system_prompt，或回退到配置的默认值
    sys_prompt = data.get("system_prompt") or _cfg.get("system_prompt", "")
    # _inject_system_prompt 内部仅在需要时拷贝
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
        _activated_skills.clear()
        with _skills_cache_lock:
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
            max_tokens=data.get("max_tokens", MAX_TOKENS),
            temperature=data.get("temperature", TEMPERATURE),
            max_rounds=int(data.get("max_tool_rounds", 50)),
            stream=True,  # 真正的 SSE 流式传输
        )

        from modules.utils import with_heartbeat
        hb_events = with_heartbeat(events, idle_seconds=15)
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

    return make_sse_response(generate())


@app.route("/api/tools/definitions")
def tools_definitions():
    """返回 tool_registry 中所有已注册的工具定义（供前端连线时获取）"""
    return jsonify(tool_registry.get_all_definitions())


# ── 组件类型 → 后端源文件映射 ──
_COMPONENT_SOURCE_MAP = {
    "web_search": "modules/web_search.py",
    "calculator": "modules/calculator.py",
    "code_executor": "modules/code_executor.py",
    "text_tools": "modules/text_tools.py",
    "time_query": "modules/common_tools.py",
    "url_fetch": "modules/common_tools.py",
    "file_ops": "modules/file_search_tools.py",
    "json_query": "modules/common_tools.py",
    "vector_memory": "modules/embeddings.py",
    "vision": "modules/vision.py",
    "mcp_word": "modules/mcp_office.py",
    "mcp_excel": "modules/mcp_office.py",
    "mcp_ppt": "modules/mcp_office.py",
    "mcp_pdf": "modules/mcp_pdf.py",
    "mcp_weather": "modules/mcp_weather.py",
    "mcp_database": "modules/mcp_database.py",
    "mcp_git": "modules/mcp_git.py",
    "mcp_clipboard": "modules/mcp_clipboard.py",
    "mcp_encoding": "modules/mcp_encoding.py",
    "mcp_system": "modules/mcp_system.py",
    "mcp_email": "modules/mcp_email.py",
    "mcp_translate": "modules/mcp_translate.py",
    "mcp_calendar": "modules/mcp_calendar.py",
    "mcp_finance": "modules/mcp_finance.py",
    "mcp_geocode": "modules/mcp_geocode.py",
    "mcp_navigation": "modules/mcp_navigation.py",
    "memory": "modules/memory.py",
    "memory_summarizer": "modules/memory_summarizer.py",
    "plan": "modules/plan.py",
    "agent": "modules/agent.py",
    "executor": "modules/executor.py",
    "sequential_executor": "modules/sequential_executor.py",
    "reflection": "modules/reflection.py",
    "token_manager": "modules/token_manager.py",
    "working_memory": "modules/common_tools.py",
    "function_calling": "modules/function_calling.py",
    "json_mode": "modules/json_mode.py",
    "system_prompt": "server.py",
    "loop": "modules/loop.py",
    "conditional": "modules/common_tools.py",
    "skills_manager": "modules/skills_manager.py",
    "skill_auto_call": "server.py",
    "skill_document": "modules/mcp_skills.py",
    "skill_frontend": "modules/mcp_skills.py",
    "skill_uiux": "modules/mcp_skills.py",
    "skill_find": "modules/mcp_skills.py",
    "skill_creator": "modules/mcp_skills.py",
    "skill_super": "modules/mcp_skills.py",
    "skill_pua": "modules/mcp_skills.py",
}


@app.route("/api/component-source/<comp_type>")
def component_source(comp_type):
    """返回组件对应的后端源文件代码（只读，供前端属性面板展示）"""
    rel_path = _COMPONENT_SOURCE_MAP.get(comp_type)
    if not rel_path:
        return jsonify({"error": f"未知组件类型: {comp_type}"}), 404
    file_path = Path(__file__).parent / rel_path
    if not file_path.exists():
        return jsonify({"error": f"源文件不存在: {rel_path}"}), 404
    try:
        code = file_path.read_text(encoding="utf-8", errors="replace")
        # 最多返回 300 行
        lines = code.split("\n")[:300]
        return jsonify({
            "component_type": comp_type,
            "source_file": rel_path,
            "code": "\n".join(lines),
            "total_lines": len(code.split("\n")),
            "truncated": len(code.split("\n")) > 300,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/verify", methods=["POST"])
def verify():
    """测试 API 连接 — 发送最小请求验证连通性"""
    data = request.get_json(force=True)
    api_base = data.get("api_base", API_BASE)
    api_key = data.get("api_key", API_KEY)
    model = data.get("model", MODEL)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "stream": False,
    }

    t0 = time.time()

    def _verify_result(success, error=None):
        latency_ms = round((time.time() - t0) * 1000)
        result = {
            "success": success,
            "latency_ms": latency_ms,
            "model": model,
            "api_base": api_base,
        }
        if error:
            result["error"] = error
        return jsonify(result)

    try:
        resp = http_session.post(
            f"{api_base}/chat/completions",
            headers=headers,
            json=payload,
            timeout=15,
        )

        if resp.status_code == 200:
            return _verify_result(True)
        else:
            error_body = resp.text[:300]
            return _verify_result(False, f"HTTP {resp.status_code}: {error_body}")

    except requests.exceptions.ConnectionError:
        return _verify_result(False, "连接失败，请检查 API 地址")
    except requests.exceptions.Timeout:
        return _verify_result(False, "连接超时（15秒），请检查网络或 API 地址")
    except Exception as e:
        return _verify_result(False, str(e))


# ============================================================
# 项目管理 API
# ============================================================
PROJECTS_DIR = Path(__file__).parent / "data" / "projects"


def _ensure_projects_dir():
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)


def _project_path(project_id):
    return PROJECTS_DIR / f"{project_id}.json"


def _read_project(project_id):
    path = _project_path(project_id)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _summarize_project(data):
    layout = data.get("layout", {})
    comps = layout.get("components", [])
    conns = layout.get("connections", [])
    return {
        "id": data["id"],
        "name": data.get("name", "未命名"),
        "componentCount": len(comps),
        "connectionCount": len(conns),
        "updatedAt": data.get("updatedAt", data.get("createdAt", "")),
    }


@app.route("/projects")
def projects_page():
    return render_template("projects.html")


@app.route("/api/projects", methods=["GET"])
def api_list_projects():
    _ensure_projects_dir()
    projects = []
    for path in sorted(PROJECTS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        data = _read_project(path.stem)
        if data:
            projects.append(_summarize_project(data))
    return jsonify(projects)


@app.route("/api/projects", methods=["POST"])
def api_create_or_update_project():
    """创建新项目或更新已有项目"""
    _ensure_projects_dir()
    body = request.get_json(force=True)
    project_id = body.get("id")

    if project_id:
        existing = _read_project(project_id)
        if not existing:
            return jsonify({"error": "项目不存在"}), 404
        existing["name"] = body.get("name", existing.get("name", "未命名"))
        existing["layout"] = body.get("layout", existing.get("layout", {}))
        existing["updatedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
        data = existing
    else:
        project_id = "proj_" + uuid.uuid4().hex[:10]
        data = {
            "id": project_id,
            "name": body.get("name", "未命名"),
            "layout": body.get("layout", {}),
            "createdAt": time.strftime("%Y-%m-%d %H:%M:%S"),
            "updatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    with open(_project_path(project_id), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return jsonify({"id": project_id, "name": data["name"]})


@app.route("/api/projects/<project_id>", methods=["GET"])
def api_get_project(project_id):
    data = _read_project(project_id)
    if not data:
        return jsonify({"error": "项目不存在"}), 404
    return jsonify(data)


@app.route("/api/projects/<project_id>", methods=["DELETE"])
def api_delete_project(project_id):
    path = _project_path(project_id)
    if path.exists():
        path.unlink()
    return jsonify({"ok": True})


# ============================================================
# 统一生成文件列表 API（聚合所有 workspace）
# ============================================================
# 简易 TTL 缓存：避免前端轮询时重复扫描文件系统
_files_cache = {"data": None, "ts": 0}
_FILES_CACHE_TTL = 5  # 秒

_WORKSPACE_DIRS = {
    "office": Path(tempfile.gettempdir()) / "mcp_office_workspace",
    "pdf": Path(tempfile.gettempdir()) / "mcp_pdf_output",
    "common": Path(tempfile.gettempdir()) / "common_tools_workspace",
    "qrcode": Path(tempfile.gettempdir()) / "mcp_qrcodes",
}

_FILE_TYPE_MAP = {
    ".docx": "word", ".xlsx": "excel", ".pptx": "ppt",
    ".pdf": "pdf", ".png": "image", ".jpg": "image", ".jpeg": "image",
    ".txt": "text", ".md": "markdown", ".json": "json", ".csv": "csv",
    ".py": "code", ".js": "code", ".html": "html", ".css": "css",
}


@app.route("/api/chat/generated-files/<session_id>", methods=["GET", "DELETE"])
def chat_generated_files(session_id):
    """聚合扫描所有 workspace，或清空所有临时文件"""
    # DELETE：清空所有 workspace 中的临时文件
    if request.method == "DELETE":
        deleted = 0
        for ws_key, ws_path in _WORKSPACE_DIRS.items():
            if not ws_path.exists():
                continue
            if ws_key == "office":
                for sd in ws_path.iterdir():
                    if sd.is_dir():
                        for f in sd.iterdir():
                            if f.is_file():
                                try:
                                    f.unlink()
                                    deleted += 1
                                except OSError:
                                    pass
            else:
                for f in ws_path.iterdir():
                    if f.is_file():
                        try:
                            f.unlink()
                            deleted += 1
                        except OSError:
                            pass
        logger.info("cleared %d generated files across all workspaces", deleted)
        # 失效文件列表缓存
        _files_cache["data"] = None
        return jsonify({"success": True, "deleted": deleted})

    # GET：返回文件列表（带短期缓存避免轮询重复扫描）
    now = time.time()
    if _files_cache["data"] is not None and (now - _files_cache["ts"]) < _FILES_CACHE_TTL:
        return jsonify(_files_cache["data"])

    files = []
    seen_names = set()

    for ws_key, ws_path in _WORKSPACE_DIRS.items():
        if not ws_path.exists():
            continue

        if ws_key == "office":
            # Office workspace: 扫描所有 session 子目录（确保不漏掉任何文件）
            scan_dirs = []
            if ws_path.exists():
                # 优先扫描指定 session
                for sid in [session_id, "default"]:
                    sd = ws_path / sid
                    if sd.exists():
                        scan_dirs.append(sd)
                # 兜底：扫描所有其他 session 子目录
                for sd in sorted(ws_path.iterdir()):
                    if sd.is_dir() and sd not in scan_dirs:
                        scan_dirs.append(sd)
        else:
            scan_dirs = [ws_path] if ws_path.exists() else []

        for scan_dir in scan_dirs:
            if not scan_dir or not scan_dir.exists():
                continue

            for f in scan_dir.iterdir():
                if not f.is_file():
                    continue
                # 去重（同一文件可能出现在多个 session 目录）
                if f.name in seen_names:
                    continue
                seen_names.add(f.name)
                ext = f.suffix.lower()
                file_type = _FILE_TYPE_MAP.get(ext, "other")
                try:
                    stat = f.stat()
                    # 记录 session 子目录（用于下载时定位文件）
                    sub_session = scan_dir.name if ws_key == "office" else ""
                    files.append({
                        "name": f.name,
                        "size": stat.st_size,
                        "size_display": _format_file_size(stat.st_size),
                        "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
                        "type": file_type,
                        "workspace": ws_key,
                        "ext": ext,
                        "sub_session": sub_session,  # Office 文件的 session 子目录名
                    })
                except OSError:
                    pass

    # 按修改时间倒序
    files.sort(key=lambda f: f["modified"], reverse=True)

    # 类型优先级排序：Office > PDF > 图片 > 其他
    type_order = {"word": 1, "excel": 1, "ppt": 1, "pdf": 2, "image": 3, "csv": 4, "json": 4, "text": 5, "code": 5, "other": 6}
    files.sort(key=lambda f: (type_order.get(f["type"], 6), f["modified"]), reverse=False)

    result = {
        "files": files,
        "count": len(files),
        "session_id": session_id,
        "workspaces": {k: str(v) for k, v in _WORKSPACE_DIRS.items()},
    }
    # 更新缓存
    _files_cache["data"] = result
    _files_cache["ts"] = now
    return jsonify(result)


def _format_file_size(size: int) -> str:
    """格式化文件大小"""
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.0f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


# ============================================================
# 存储路径配置 API（前后端同步）
# ============================================================
STORAGE_CONFIG_FILE = Path(__file__).parent / "data" / "storage_config.json"


def _read_storage_config() -> dict:
    """读取存储配置"""
    if STORAGE_CONFIG_FILE.exists():
        try:
            return json.loads(STORAGE_CONFIG_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"path": "", "name": "", "updatedAt": ""}


def _write_storage_config(cfg: dict):
    """写入存储配置"""
    STORAGE_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    STORAGE_CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


@app.route("/api/config/storage-path", methods=["GET", "POST"])
def config_storage_path():
    """获取或更新存储路径配置（前后端同步）"""
    if request.method == "GET":
        return jsonify(_read_storage_config())

    data = request.get_json(force=True)
    cfg = _read_storage_config()
    if "path" in data:
        cfg["path"] = data["path"]
    if "name" in data:
        cfg["name"] = data["name"]
    cfg["updatedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _write_storage_config(cfg)
    logger.info("storage path updated: %s", cfg.get("name", cfg.get("path", "")))
    return jsonify({"success": True, "config": cfg})


# ============================================================
# 启动
# ============================================================
if __name__ == "__main__":
    # 设置 stdout 编码避免 Windows GBK 乱码
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    # 环境判断：FLASK_ENV=production 时使用生产模式
    is_debug = os.getenv("FLASK_ENV", "").lower() != "production"

    logger.info("=" * 50)
    logger.info("  Agent编辑器 V0.1")
    logger.info("  LLM Model: %s", MODEL)
    logger.info("  URL: http://localhost:%d", PORT)
    logger.info("  Mode: %s", "debug" if is_debug else "production")
    logger.info("=" * 50)

    app.run(host="0.0.0.0", port=PORT, debug=is_debug)
