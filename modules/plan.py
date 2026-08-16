"""
Plan 模块 — 任务规划与分步执行
提供计划生成、步骤管理、分步执行功能
"""

import json
import threading
import time

import requests as _requests
from flask import jsonify, request

from . import tool_registry
from .config import get_config
from .llm_client import chat_with_tools_sync
from .utils import clean_json_response, get_request_api_config, make_sse_response, sse_event, sse_done

# ============================================================
# 共享 HTTP session
# ============================================================
_http_session = None


def _get_session():
    if _http_session is not None:
        return _http_session
    s = _requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ============================================================
# 工具定义
# ============================================================
PLAN_GENERATE_DEF = {
    "name": "plan_generate",
    "description": (
        "根据任务描述生成分步执行计划。"
        "将复杂任务分解为可执行的步骤序列，每步包含标题、描述和所需工具。"
        "当用户需要规划复杂任务、分解多步骤操作时使用。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "要规划的任务描述"},
            "max_steps": {
                "type": "integer",
                "description": "最大步骤数，默认 7",
                "default": 7,
            },
        },
        "required": ["task"],
    },
}

PLAN_EXECUTE_DEF = {
    "name": "plan_execute_step",
    "description": (
        "执行计划中的指定步骤。传入步骤描述和可用工具，"
        "LLM 将根据步骤描述决定调用哪些工具来完成该步骤。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "step_title": {"type": "string", "description": "步骤标题"},
            "step_description": {"type": "string", "description": "步骤的详细描述"},
            "tools": {
                "type": "array",
                "items": {"type": "string"},
                "description": "该步骤可用的工具名称列表",
            },
        },
        "required": ["step_title", "step_description"],
    },
}


# ============================================================
# 计划管理（内存存储 + 线程安全 + 定期清理）
# ============================================================
_plans = {}
_plans_lock = threading.Lock()
_last_plans_cleanup = 0
_PLANS_MAX_AGE = 7200  # 2小时过期
_PLANS_CLEANUP_INTERVAL = 600  # 每10分钟清理一次


def _cleanup_old_plans():
    """清理过期计划"""
    global _last_plans_cleanup
    now = time.time()
    if now - _last_plans_cleanup < _PLANS_CLEANUP_INTERVAL:
        return
    with _plans_lock:
        expired = []
        for pid, plan in _plans.items():
            created = plan.get("created_at", "")
            try:
                t = time.mktime(time.strptime(created, "%Y-%m-%d %H:%M:%S"))
                if now - t > _PLANS_MAX_AGE:
                    expired.append(pid)
            except (ValueError, OverflowError):
                pass
        for pid in expired:
            del _plans[pid]
    _last_plans_cleanup = now


def _generate_plan(task: str, max_steps: int = 7,
                   api_base: str = None, api_key: str = None, model: str = None) -> dict:
    """调用 LLM 生成执行计划"""
    cfg = get_config()
    # 优先使用传入参数，其次使用请求级配置（线程本地 + Flask g 回退），最后使用全局默认值
    req_cfg = get_request_api_config()
    base = api_base or req_cfg.get("api_base") or cfg["api_base"]
    key = api_key or req_cfg.get("api_key") or cfg["api_key"]
    mdl = model or req_cfg.get("model") or cfg["model"]

    system_prompt = (
        "你是一个任务规划专家。根据用户的任务描述，生成一个分步执行计划。"
        "每步必须具体、可执行、有明确的预期产出。\n\n"
        "返回严格的 JSON 格式（不要包含 markdown 代码块标记）：\n"
        '{"title": "计划标题", "steps": ['
        '{"step": 1, "title": "步骤标题", "description": "详细描述", '
        '"expected_output": "预期产出", "suggested_tools": ["工具名"]}'
        ', ...]}'
    )

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
    }

    session = _get_session()

    try:
        resp = session.post(
            f"{base}/chat/completions",
            headers=headers,
            json={
                "model": mdl,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"任务: {task}\n最大步骤数: {max_steps}"},
                ],
                "max_tokens": 2048,
                "temperature": 0.3,
                "stream": False,
            },
            timeout=120,
        )
        if resp.status_code != 200:
            return {"error": f"API 返回 {resp.status_code}: {resp.text[:300]}"}

        body = resp.json()
        content = body.get("choices", [{}])[0].get("message", {}).get("content", "")

        try:
            plan = json.loads(content)
        except json.JSONDecodeError:
            try:
                plan = json.loads(clean_json_response(content))
            except (json.JSONDecodeError, ValueError) as e:
                return {"error": f"LLM 返回的不是有效 JSON: {content[:300]}"}

        return plan
    except _requests.exceptions.ConnectionError:
        return {"error": f"连接失败! 请检查 API 地址: {base}"}
    except _requests.exceptions.Timeout:
        return {"error": "请求超时，请重试"}
    except Exception as e:
        return {"error": str(e)}


def _execute_step(step_title: str, step_description: str, tools: list = None,
                  api_base: str = None, api_key: str = None, model: str = None) -> dict:
    """执行单个计划步骤"""
    cfg = get_config()
    req_cfg = get_request_api_config()
    base = api_base or req_cfg.get("api_base") or cfg["api_base"]
    key = api_key or req_cfg.get("api_key") or cfg["api_key"]
    mdl = model or req_cfg.get("model") or cfg["model"]

    system_prompt = (
        f"你正在执行计划中的一个步骤。\n"
        f"步骤: {step_title}\n"
        f"描述: {step_description}\n\n"
        f"请根据步骤描述，使用可用工具完成该步骤的任务。"
        f"完成后，用简洁的语言总结你完成了什么。"
    )

    result = chat_with_tools_sync(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"请执行步骤: {step_title}\n{step_description}"},
        ],
        tool_names=tools or None,
        http_session=_get_session(),
        api_base=base,
        api_key=key,
        model=mdl,
        max_tokens=2048,
        temperature=0.5,
        max_rounds=20,
    )

    if not result["success"]:
        return {"error": result.get("error", "未知错误")}

    return {
        "success": True,
        "step_title": step_title,
        "output": result["content"],
        "tool_results": [
            {"tool": tc["name"], "args": tc.get("arguments", ""), "result": tc.get("result", "")[:500]}
            for tc in result.get("tool_calls_made", [])
        ],
    }


# ============================================================
# 注册工具
# ============================================================
def _exec_plan_generate(args: dict) -> str:
    """AI 可调用的计划生成器"""
    task = args.get("task", "")
    max_steps = int(args.get("max_steps", 7))
    if not task:
        return "错误: 任务描述不能为空"

    result = _generate_plan(task, max_steps)
    if "error" in result:
        return f"计划生成失败: {result['error']}"

    plan_id = f"plan_{int(time.time())}"
    result["plan_id"] = plan_id
    result["task"] = task
    result["created_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    result["status"] = "created"
    with _plans_lock:
        _plans[plan_id] = result

    steps_text = "\n".join(
        f"  {s['step']}. [{s.get('title', '')}] {s.get('description', '')[:80]}"
        for s in result.get("steps", [])
    )
    return f"✅ 计划已生成 (ID: {plan_id})\n📋 {result.get('title', '计划')}\n\n步骤:\n{steps_text}"


def _exec_plan_execute(args: dict) -> str:
    """AI 可调用的步骤执行器"""
    step_title = args.get("step_title", "")
    step_description = args.get("step_description", "")
    tools = args.get("tools", [])
    if not step_title:
        return "错误: 步骤标题不能为空"

    result = _execute_step(step_title, step_description, tools)
    if "error" in result:
        return f"步骤执行失败: {result['error']}"

    tool_info = ""
    if result.get("tool_results"):
        tool_info = "\n\n🔧 使用的工具:\n" + "\n".join(
            f"  - {tr['tool']}: {tr['result'][:100]}" for tr in result["tool_results"]
        )

    return f"✅ 步骤完成: {result['step_title']}\n\n📝 输出:\n{result['output']}{tool_info}"


tool_registry.register("plan_generate", PLAN_GENERATE_DEF, _exec_plan_generate)
tool_registry.register("plan_execute_step", PLAN_EXECUTE_DEF, _exec_plan_execute)


# ============================================================
# Flask 路由
# ============================================================
def register_routes(app, http_session=None):
    global _http_session
    if http_session is not None:
        _http_session = http_session

    cfg = get_config()

    @app.route("/api/plan/generate", methods=["POST"])
    def plan_generate():
        """生成任务执行计划"""
        data = request.get_json(force=True)
        task = (data.get("task") or "").strip()
        max_steps = int(data.get("max_steps", 7))
        api_base = data.get("api_base") or cfg["api_base"]
        api_key = data.get("api_key") or cfg["api_key"]
        model = data.get("model") or cfg["model"]

        if not task:
            return jsonify({"success": False, "error": "任务描述不能为空"}), 400

        t0 = time.time()
        result = _generate_plan(task, max_steps, api_base, api_key, model)
        latency_ms = round((time.time() - t0) * 1000)

        if "error" in result:
            return jsonify({"success": False, "error": result["error"], "latency_ms": latency_ms}), 400

        plan_id = f"plan_{int(time.time())}"
        result["plan_id"] = plan_id
        result["task"] = task
        result["created_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        result["status"] = "created"
        result["current_step"] = 0
        with _plans_lock:
            _plans[plan_id] = result

        return jsonify({"success": True, "plan": result, "latency_ms": latency_ms})

    @app.route("/api/plan/<plan_id>", methods=["GET"])
    def plan_get(plan_id):
        """获取计划详情"""
        _cleanup_old_plans()  # 定期清理过期计划
        plan = _plans.get(plan_id)
        if not plan:
            return jsonify({"success": False, "error": "计划不存在"}), 404
        return jsonify({"success": True, "plan": plan})

    @app.route("/api/plan/<plan_id>/execute/<int:step_index>", methods=["POST"])
    def plan_execute_step(plan_id, step_index):
        """执行计划中的指定步骤"""
        plan = _plans.get(plan_id)
        if not plan:
            return jsonify({"success": False, "error": "计划不存在"}), 404

        steps = plan.get("steps", [])
        step = steps[step_index]
        data = request.get_json(force=True) or {}
        api_base = data.get("api_base") or cfg["api_base"]
        api_key = data.get("api_key") or cfg["api_key"]
        model = data.get("model") or cfg["model"]
        tools = data.get("tools") or step.get("suggested_tools", [])

        t0 = time.time()
        result = _execute_step(
            step.get("title", f"步骤 {step_index + 1}"),
            step.get("description", ""),
            tools, api_base, api_key, model,
        )
        latency_ms = round((time.time() - t0) * 1000)

        if "error" in result:
            return jsonify({"success": False, "error": result["error"], "latency_ms": latency_ms}), 400

        with _plans_lock:
            plan["current_step"] = step_index + 1
            if "step_results" not in plan:
                plan["step_results"] = {}
            plan["step_results"][str(step_index)] = result
            if step_index + 1 >= len(steps):
                plan["status"] = "completed"
            _plans[plan_id] = plan
        return jsonify({"success": True, "result": result, "plan": plan, "latency_ms": latency_ms})

    @app.route("/api/plan/<plan_id>/execute-all", methods=["POST"])
    def plan_execute_all(plan_id):
        """顺序执行计划中的所有步骤（SSE 流式）"""
        with _plans_lock:
            plan = _plans.get(plan_id)
        if not plan:
            return jsonify({"success": False, "error": "计划不存在"}), 404

        steps = plan.get("steps", [])
        data = request.get_json(force=True) or {}
        api_base = data.get("api_base") or cfg["api_base"]
        api_key = data.get("api_key") or cfg["api_key"]
        model = data.get("model") or cfg["model"]

        def generate():
            with _plans_lock:
                plan["status"] = "running"
                plan["step_results"] = {}

            for i, step in enumerate(steps):
                tools = step.get("suggested_tools", [])
                yield sse_event({
                    "type": "step_start", "step": i + 1,
                    "total": len(steps), "title": step.get("title", ""),
                })

                t0 = time.time()
                result = _execute_step(
                    step.get("title", f"步骤 {i + 1}"),
                    step.get("description", ""),
                    tools, api_base, api_key, model,
                )
                latency_ms = round((time.time() - t0) * 1000)

                if "error" in result:
                    yield sse_event({"type": "step_error", "step": i + 1, "error": result["error"]})
                    with _plans_lock:
                        plan["status"] = "failed"
                    return

                with _plans_lock:
                    plan["step_results"][str(i)] = result
                    plan["current_step"] = i + 1

                yield sse_event({
                    "type": "step_complete", "step": i + 1,
                    "output": result.get("output", ""),
                    "tool_results": result.get("tool_results", []),
                    "latency_ms": latency_ms,
                })

            with _plans_lock:
                plan["status"] = "completed"
            yield sse_event({"type": "plan_complete"})
            yield sse_done()

        return make_sse_response(generate())

    @app.route("/api/plan/<plan_id>/reflect", methods=["POST"])
    def plan_reflect(plan_id):
        """反思执行结果，分析完成情况，给出调整建议"""
        with _plans_lock:
            plan = _plans.get(plan_id)
        if not plan:
            return jsonify({"success": False, "error": "计划不存在"}), 404

        data = request.get_json(force=True) or {}
        api_base = data.get("api_base") or cfg["api_base"]
        api_key = data.get("api_key") or cfg["api_key"]
        model = data.get("model") or cfg["model"]

        steps = plan.get("steps", [])
        step_results = plan.get("step_results", {})
        task = plan.get("task", "")

        executed_summary = []
        for i, step in enumerate(steps):
            result = step_results.get(str(i))
            if result:
                status = "✅ 成功" if result.get("success") else "❌ 失败"
                executed_summary.append(
                    f"步骤{i+1} [{step.get('title', '')}]: {status}\n"
                    f"  输出: {(result.get('output') or result.get('error', ''))[:200]}"
                )
            else:
                executed_summary.append(f"步骤{i+1} [{step.get('title', '')}]: ⚠️ 未执行")

        summary_text = "\n".join(executed_summary)

        system_prompt = (
            "你是一个 Agent 反思与规划专家。根据任务执行结果，分析哪些步骤完成了、哪些有问题、"
            "是否需要调整计划。\n\n"
            "返回严格的 JSON 格式（不要包含 markdown 代码块标记）：\n"
            "{\n"
            '  "analysis": "整体分析（1-2句话）",\n'
            '  "completion": "已完成/部分完成/失败",\n'
            '  "issues": ["问题1", "问题2"],\n'
            '  "need_replan": true/false,\n'
            '  "suggestion": "下一步建议",\n'
            '  "adjusted_steps": []\n'
            "}"
        )

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

        try:
            session = _get_session()
            resp = session.post(
                f"{api_base}/chat/completions",
                headers=headers,
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": (
                            f"原始任务: {task}\n\n"
                            f"原计划步骤:\n"
                            + "\n".join(f"  {s.get('step', i+1)}. {s.get('title', '')}: {s.get('description', '')}"
                                       for i, s in enumerate(steps))
                            + f"\n\n执行结果:\n{summary_text}\n\n"
                            f"请分析执行情况，判断是否需要重规划。"
                        )},
                    ],
                    "max_tokens": 2048,
                    "temperature": 0.3,
                    "stream": False,
                },
                timeout=120,
            )

            if resp.status_code != 200:
                return jsonify({"success": False, "error": f"API {resp.status_code}: {resp.text[:300]}"}), 400

            body = resp.json()
            content = body.get("choices", [{}])[0].get("message", {}).get("content", "")

            try:
                reflection = json.loads(content)
            except json.JSONDecodeError:
                try:
                    reflection = json.loads(clean_json_response(content))
                except (json.JSONDecodeError, ValueError):
                    return jsonify({"success": False, "error": f"反思结果不是有效 JSON: {content[:300]}"}), 400

            with _plans_lock:
                plan["reflection"] = reflection
                if reflection.get("need_replan") and reflection.get("adjusted_steps"):
                    new_plan_id = f"plan_{int(time.time())}"
                    new_plan = {
                        "plan_id": new_plan_id,
                        "title": f"{plan.get('title', '计划')} (调整)",
                        "task": task,
                        "steps": reflection["adjusted_steps"],
                        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "status": "created",
                        "current_step": 0,
                        "parent_plan_id": plan_id,
                    }
                    _plans[new_plan_id] = new_plan
                    reflection["new_plan_id"] = new_plan_id

            return jsonify({"success": True, "reflection": reflection, "plan": plan})

        except _requests.exceptions.ConnectionError:
            return jsonify({"success": False, "error": f"连接失败: {api_base}"}), 400
        except _requests.exceptions.Timeout:
            return jsonify({"success": False, "error": "请求超时"}), 400
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 400

    @app.route("/api/plans", methods=["GET"])
    def plan_list():
        """列出所有计划"""
        with _plans_lock:
            plans_list = [
                {
                    "plan_id": pid,
                    "title": p.get("title", ""),
                    "task": p.get("task", ""),
                    "status": p.get("status", ""),
                    "steps_count": len(p.get("steps", [])),
                    "current_step": p.get("current_step", 0),
                    "created_at": p.get("created_at", ""),
                }
                for pid, p in _plans.items()
            ]
        return jsonify({"success": True, "plans": plans_list})
