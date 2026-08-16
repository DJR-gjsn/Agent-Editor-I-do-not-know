"""
Agent 编排器模块 — Plan → Execute → Reflect 主循环
提供一个统一的 Agent 循环 API，整合规划、执行、反思三大阶段
"""
import json
import re
import time

import requests
from flask import request, jsonify

from . import tool_registry
from .config import get_config
from .utils import clean_json_response, make_sse_response, sse_event, sse_done


def register_routes(app, http_session=None):
    """注册 Agent 编排 API 路由"""
    if http_session is None:
        http_session = getattr(app, '_http_session', requests.Session())

    cfg = get_config()

    @app.route("/api/agent/run", methods=["POST"])
    def agent_run():
        """运行 Agent 主循环：Plan → Execute → Reflect → (Replan) → ..."""
        data = request.get_json(force=True)
        task = data.get("task", "")
        tools = data.get("tools", [])
        messages = data.get("messages", [])
        max_iterations = data.get("max_iterations", 30)
        api_base = data.get("api_base") or cfg["api_base"]
        api_key = data.get("api_key") or cfg["api_key"]
        model = data.get("model") or cfg["model"]

        if not task:
            return jsonify({"success": False, "error": "缺少任务描述 (task)"})

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

        def generate():
            iteration = 0
            current_plan = None
            step_results = {}

            # Phase 1: 规划
            yield sse_event({"phase": "planning", "message": "🧠 正在分析任务并制定计划..."})

            plan_prompt = f"""你是一个任务规划专家。请将以下任务分解为详细的执行步骤。

任务: {task}

可用的工具: {', '.join(tools) if tools else '无特殊工具'}

请返回 JSON 格式:
{{
    "title": "计划标题",
    "steps": [
        {{"title": "步骤名称", "description": "具体做什么", "suggested_tools": ["工具名"]}}
    ]
}}

要求:
- 步骤具体、可执行
- 每步写明需要用什么工具
- 3-7 个步骤
- 步骤之间有逻辑先后"""

            try:
                plan_resp = http_session.post(
                    f"{api_base}/chat/completions",
                    headers=headers,
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": "你是一个专业的工作流规划器。始终返回合法 JSON。"},
                            {"role": "user", "content": plan_prompt},
                        ],
                        "max_tokens": 1500,
                        "temperature": 0.3,
                        "response_format": {"type": "json_object"},
                    },
                    timeout=60,
                )

                if plan_resp.status_code == 200:
                    plan_body = plan_resp.json()
                    plan_content = plan_body["choices"][0]["message"]["content"]
                    try:
                        current_plan = json.loads(plan_content)
                    except json.JSONDecodeError:
                        try:
                            current_plan = json.loads(clean_json_response(plan_content))
                        except (json.JSONDecodeError, ValueError):
                            current_plan = {
                                "title": "自动计划",
                                "steps": [{"title": "执行任务", "description": task, "suggested_tools": tools}],
                            }

                    yield sse_event({"phase": "plan_ready", "plan": current_plan})
                else:
                    yield sse_event({"phase": "error", "message": f"规划失败: HTTP {plan_resp.status_code}"})
                    return
            except Exception as e:
                yield sse_event({"phase": "error", "message": f"规划阶段异常: {str(e)}"})
                return

            steps = current_plan.get("steps", [])

            # Phase 2: 执行循环
            while iteration < max_iterations:
                iteration += 1
                yield sse_event({"phase": "iteration", "iteration": iteration, "max": max_iterations})

                for i, step in enumerate(steps):
                    step_key = str(i)
                    yield sse_event({"phase": "step_start", "step_index": i, "step": step})

                    exec_prompt = f"""请执行以下步骤。你可以使用这些工具: {', '.join(tools) if tools else '无'}

步骤: {step.get('title', f'步骤{i+1}')}
描述: {step.get('description', '')}

如果需要调用工具，请说明要调用哪个工具和参数。如果不需要工具，直接给出结果。"""

                    try:
                        exec_resp = http_session.post(
                            f"{api_base}/chat/completions",
                            headers=headers,
                            json={
                                "model": model,
                                "messages": [
                                    {"role": "system", "content": "你是一个任务执行器。执行给定的步骤并返回结果。"},
                                    *[{"role": m["role"], "content": m["content"]} for m in messages[-6:]],
                                    {"role": "user", "content": exec_prompt},
                                ],
                                "max_tokens": 1000,
                                "temperature": 0.5,
                            },
                            timeout=60,
                        )

                        if exec_resp.status_code == 200:
                            exec_body = exec_resp.json()
                            output = exec_body["choices"][0]["message"]["content"]
                            step_results[step_key] = {"success": True, "output": output}
                            yield sse_event({
                                "phase": "step_done", "step_index": i,
                                "output": output[:500], "success": True,
                            })
                        else:
                            step_results[step_key] = {"success": False, "error": f"HTTP {exec_resp.status_code}"}
                            yield sse_event({
                                "phase": "step_error", "step_index": i,
                                "error": f"HTTP {exec_resp.status_code}",
                            })

                    except Exception as e:
                        step_results[step_key] = {"success": False, "error": str(e)}
                        yield sse_event({"phase": "step_error", "step_index": i, "error": str(e)})

                # Phase 3: 反思
                yield sse_event({"phase": "reflecting", "message": "🔄 反思评估中..."})

                success_count = sum(1 for r in step_results.values() if r.get("success"))
                total_steps = len(steps)
                ratio = success_count / total_steps if total_steps > 0 else 0

                if ratio >= 0.8:
                    yield sse_event({
                        "phase": "complete", "success_ratio": ratio, "results": step_results,
                    })
                    yield sse_done()
                    return

                if iteration < max_iterations:
                    yield sse_event({
                        "phase": "replan",
                        "message": f"完成度 {ratio:.0%}，继续优化...",
                        "iteration": iteration,
                    })
                    steps = [
                        step for i, step in enumerate(steps)
                        if not step_results.get(str(i), {}).get("success")
                    ]
                    if not steps:
                        yield sse_event({"phase": "complete", "results": step_results})
                        yield sse_done()
                        return

            yield sse_event({
                "phase": "max_iterations", "iteration": iteration, "results": step_results,
            })
            yield sse_done()

        return make_sse_response(generate())

    @app.route("/api/agent/status", methods=["GET"])
    def agent_status():
        """返回 Agent 系统状态"""
        return jsonify({
            "success": True,
            "available_tools": len(tool_registry.get_all_definitions()),
            "model": cfg["model"],
            "api_base": cfg["api_base"],
            "has_api_key": bool(cfg["api_key"] and cfg["api_key"] != "sk-your-api-key-here"),
        })
