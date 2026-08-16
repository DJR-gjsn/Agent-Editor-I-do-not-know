"""
执行器模块 — 步骤执行引擎
接收任务步骤列表，顺序执行每个步骤的工具调用，SSE 流式输出进度
可由 Plan 模块或 LLM 直接驱动
"""

import json
import time

import requests as _requests
from flask import jsonify, request

from . import tool_registry
from .config import get_config
from .llm_client import chat_with_tools_sync
from .utils import make_sse_response, sse_event, sse_done

# ============================================================
# 共享 HTTP session（由 register_routes 设置）
# ============================================================
_http_session = None


def _get_session():
    """获取共享 HTTP session，不再每次创建新的 Session 对象"""
    global _http_session
    if _http_session is not None:
        return _http_session
    # 仅首次创建，后续复用
    _http_session = _requests.Session()
    _http_session.headers.update({"Content-Type": "application/json"})
    return _http_session


# ============================================================
# 工具定义
# ============================================================
EXECUTOR_RUN_DEF = {
    "name": "executor_run",
    "description": (
        "按顺序执行一组任务步骤。每个步骤指定要调用的工具和参数。"
        "执行器将按顺序逐个执行，并报告每步的成功/失败状态。"
        "适合将复杂任务分解为多个工具调用后批量执行。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "步骤标题"},
                        "tool": {"type": "string", "description": "要调用的工具名称"},
                        "args": {"type": "object", "description": "传给工具的参数"},
                    },
                    "required": ["title", "tool"],
                },
                "description": "要执行的任务步骤列表",
            },
        },
        "required": ["steps"],
    },
}


# ============================================================
# 执行器核心
# ============================================================
def _execute_single_step(step: dict) -> dict:
    """执行单个步骤，返回结果"""
    title = step.get("title", "未命名步骤")
    tool_name = step.get("tool", "")
    tool_args = step.get("args", {})

    if not tool_name:
        return {"title": title, "success": False, "error": "未指定工具名称"}

    try:
        result = tool_registry.execute(tool_name, tool_args)
        if result.startswith("错误:") or result.startswith("工具执行错误:"):
            return {"title": title, "success": False, "tool": tool_name, "error": result}
        return {"title": title, "success": True, "tool": tool_name, "output": str(result)[:2000]}
    except Exception as e:
        return {"title": title, "success": False, "tool": tool_name, "error": str(e)}


def _execute_step_with_llm(step: dict, api_base: str, api_key: str, model: str) -> dict:
    """
    对于需要 LLM 参与的步骤，使用共享的 chat_with_tools_sync 完成。
    """
    title = step.get("title", "未命名步骤")
    description = step.get("description", title)
    tool_names = step.get("tools", [])
    instruction = step.get("instruction", description)

    if not tool_names:
        if step.get("tool"):
            return _execute_single_step(step)
        return {"title": title, "success": False, "error": "未指定工具"}

    system_prompt = (
        f"你正在执行任务的一个步骤。\n"
        f"步骤: {title}\n"
        f"说明: {instruction}\n\n"
        f"请使用可用工具完成此步骤，完成后用简洁的语言报告结果。"
    )

    result = chat_with_tools_sync(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"请执行: {instruction}"},
        ],
        tool_names=tool_names,
        http_session=_get_session(),
        api_base=api_base,
        api_key=api_key,
        model=model,
        max_tokens=2048,
        temperature=0.3,
        max_rounds=5,
    )

    if not result["success"]:
        return {"title": title, "success": False, "error": result.get("error", "未知错误")}

    return {
        "title": title,
        "success": True,
        "output": result["content"],
        "tool_results": [
            {"tool": tc["name"], "result": tc.get("result", "")[:500]}
            for tc in result.get("tool_calls_made", [])
        ],
    }


# ============================================================
# 注册工具
# ============================================================
def _exec_executor_run(args: dict) -> str:
    """AI 可调用的批量步骤执行器"""
    steps = args.get("steps", [])
    if not steps:
        return "错误: 步骤列表不能为空"

    results = [_execute_single_step(s) for s in steps]

    success_count = sum(1 for r in results if r.get("success"))
    fail_count = len(results) - success_count

    lines = [f"执行完成: {success_count}/{len(results)} 成功"]
    if fail_count > 0:
        lines.append(f"⚠️ {fail_count} 个步骤失败")

    for i, r in enumerate(results):
        icon = "✅" if r.get("success") else "❌"
        detail = r.get("output") or r.get("error", "")
        lines.append(f"  {icon} 步骤{i+1} [{r.get('title', '')}]: {detail[:120]}")

    return "\n".join(lines)


tool_registry.register("executor_run", EXECUTOR_RUN_DEF, _exec_executor_run)


# ============================================================
# LLM 决策 + 执行
# ============================================================
def _llm_decide_tools(step_title: str, step_description: str, available_tools: list,
                      api_base: str, api_key: str, model: str) -> dict:
    """让 LLM 决定：要完成这个步骤，应该调用哪些工具、传什么参数。"""
    system_prompt = (
        f"你是一个任务执行器。你的任务是完成下面描述的步骤。\n"
        f"你有以下工具可用。请根据步骤描述，决定需要调用哪些工具以及传什么参数。\n"
        f"调用完成后，用简洁的语言报告执行结果。"
    )

    result = chat_with_tools_sync(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"步骤: {step_title}\n描述: {step_description}\n\n请决定需要调用哪些工具来完成此步骤。"},
        ],
        tool_names=available_tools if available_tools else None,
        http_session=_get_session(),
        api_base=api_base,
        api_key=api_key,
        model=model,
        max_tokens=2048,
        temperature=0.3,
        max_rounds=5,
    )

    if not result["success"]:
        return {"success": False, "error": result.get("error", "未知错误")}

    return {
        "success": True,
        "step_title": step_title,
        "llm_decision": {
            "reasoning": result["content"],
            "tool_calls": [
                {"tool": tc["name"], "arguments": tc.get("arguments", "")}
                for tc in result.get("tool_calls_made", [])
            ],
        },
        "tool_results": [
            {"tool": tc["name"], "result": tc.get("result", "")[:500]}
            for tc in result.get("tool_calls_made", [])
        ],
        "summary": result["content"],
    }


# ============================================================
# Flask 路由
# ============================================================
def register_routes(app, http_session=None):
    global _http_session
    if http_session is not None:
        _http_session = http_session

    cfg = get_config()

    @app.route("/api/executor/decide-and-execute", methods=["POST"])
    def executor_decide_and_execute():
        """Plan → Executor → LLM 核心流程"""
        data = request.get_json(force=True)
        step = data.get("step", {})
        available_tools = data.get("tools", [])
        api_base = data.get("api_base") or cfg["api_base"]
        api_key = data.get("api_key") or cfg["api_key"]
        model = data.get("model") or cfg["model"]

        step_title = step.get("title", "未命名步骤")
        step_description = step.get("description", step.get("instruction", step_title))

        if not step_title:
            return jsonify({"success": False, "error": "步骤信息不能为空"}), 400

        t0 = time.time()
        result = _llm_decide_tools(
            step_title, step_description, available_tools,
            api_base, api_key, model
        )
        latency_ms = round((time.time() - t0) * 1000)
        result["latency_ms"] = latency_ms

        return jsonify(result)

    @app.route("/api/executor/run-simple", methods=["POST"])
    def executor_run_simple():
        """简单批量执行（不需要 LLM，直接调用工具）"""
        data = request.get_json(force=True)
        steps = data.get("steps", [])

        if not steps:
            return jsonify({"success": False, "error": "步骤列表不能为空"}), 400

        t0 = time.time()
        results = [_execute_single_step(s) for s in steps]
        latency_ms = round((time.time() - t0) * 1000)

        success_count = sum(1 for r in results if r.get("success"))
        return jsonify({
            "success": True,
            "total": len(steps),
            "success_count": success_count,
            "fail_count": len(steps) - success_count,
            "results": results,
            "latency_ms": latency_ms,
        })

    @app.route("/api/executor/run", methods=["POST"])
    def executor_run():
        """SSE 流式执行（需要 LLM 参与时使用）"""
        data = request.get_json(force=True)
        steps = data.get("steps", [])
        api_base = data.get("api_base") or cfg["api_base"]
        api_key = data.get("api_key") or cfg["api_key"]
        model = data.get("model") or cfg["model"]

        if not steps:
            return jsonify({"success": False, "error": "步骤列表不能为空"}), 400

        def generate():
            results = []
            for i, step in enumerate(steps):
                yield sse_event({
                    "type": "step_start", "step": i + 1,
                    "total": len(steps), "title": step.get("title", ""),
                })

                t0 = time.time()
                if step.get("tools"):
                    result = _execute_step_with_llm(step, api_base, api_key, model)
                else:
                    result = _execute_single_step(step)

                latency_ms = round((time.time() - t0) * 1000)
                result["latency_ms"] = latency_ms
                results.append(result)

                yield sse_event({
                    "type": "step_result", "step": i + 1, "result": result,
                })

            success_count = sum(1 for r in results if r.get("success"))
            yield sse_event({
                "type": "complete", "total": len(steps),
                "success_count": success_count,
                "fail_count": len(steps) - success_count,
            })
            yield sse_done()

        return make_sse_response(generate())
