"""
Reflection 反思模块 — Agent 自我评估与修正
调用 LLM 评估执行结果，判断任务是否完成，给出下一步建议
"""
import json
import time
import requests
from flask import request, jsonify

from .config import get_config
from .utils import clean_json_response


def register_routes(app, http_session=None):
    """注册反思评估 API 路由"""
    if http_session is None:
        http_session = getattr(app, '_http_session', requests.Session())

    cfg = get_config()
    API_BASE = cfg["api_base"]
    API_KEY = cfg["api_key"]
    MODEL = cfg["model"]

    REFLECTION_SYSTEM_PROMPT = """你是一个任务执行质量评估专家。你需要评估 Agent 执行的结果并判断任务是否完成。

请分析以下内容并返回 JSON：
{
    "completion": "completed | partial | failed",
    "analysis": "对执行结果的简要分析",
    "issues": ["发现的问题1", "问题2"],
    "suggestion": "如果未完成，下一步应该怎么做",
    "need_replan": true/false,
    "adjusted_steps": ["调整后的步骤1", "步骤2"]
}

评估标准：
- completed: 任务目标已完全达成
- partial: 部分完成，还需要继续
- failed: 执行失败，需要重新规划
"""

    @app.route("/api/reflection/evaluate", methods=["POST"])
    def reflect_evaluate():
        """评估执行结果，判断任务完成度"""
        data = request.get_json(force=True)
        task = data.get("task", "")
        plan_steps = data.get("plan_steps", [])
        step_results = data.get("step_results", {})
        api_base = data.get("api_base") or API_BASE
        api_key = data.get("api_key") or API_KEY
        model = data.get("model") or MODEL
        extra_context = data.get("extra_context", "")

        # 构建评估上下文
        steps_desc = []
        for i, step in enumerate(plan_steps):
            result = step_results.get(str(i), {})
            status = "✅" if result.get("success") else "❌"
            output = result.get("output", result.get("error", "无输出"))
            steps_desc.append(
                f"{status} 步骤{i+1}「{step.get('title', f'步骤{i+1}')}」: "
                f"{str(output)[:300]}"
            )

        evaluation_prompt = f"""## 原始任务
{task}

## 执行计划与结果
{chr(10).join(steps_desc)}

{extra_context}

请评估以上执行结果，判断任务是否完成。"""

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": REFLECTION_SYSTEM_PROMPT},
                {"role": "user", "content": evaluation_prompt},
            ],
            "max_tokens": 1024,
            "temperature": 0.3,
            "response_format": {"type": "json_object"},
        }

        t0 = time.time()
        try:
            resp = http_session.post(
                f"{api_base}/chat/completions",
                headers=headers,
                json=payload,
                timeout=60,
            )

            if resp.status_code != 200:
                return jsonify({
                    "success": False,
                    "error": f"API 返回 {resp.status_code}: {resp.text[:300]}",
                })

            body = resp.json()
            content = body["choices"][0]["message"]["content"]

            try:
                evaluation = json.loads(content)
            except json.JSONDecodeError:
                try:
                    evaluation = json.loads(clean_json_response(content))
                except (json.JSONDecodeError, ValueError):
                    evaluation = {
                        "completion": "partial",
                        "analysis": content[:500],
                        "issues": [],
                        "suggestion": "请人工检查结果",
                        "need_replan": False,
                        "adjusted_steps": [],
                    }

            latency_ms = round((time.time() - t0) * 1000)

            return jsonify({
                "success": True,
                "evaluation": evaluation,
                "raw_response": content,
                "latency_ms": latency_ms,
            })

        except requests.exceptions.ConnectionError:
            return jsonify({"success": False, "error": "连接失败，请检查 API 地址"})
        except requests.exceptions.Timeout:
            return jsonify({"success": False, "error": "评估请求超时"})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)})

    @app.route("/api/reflection/quick-check", methods=["POST"])
    def reflect_quick_check():
        """快速检查：只用规则判断，不调 LLM，用于简单场景"""
        data = request.get_json(force=True)
        step_results = data.get("step_results", {})
        threshold = data.get("success_threshold", 0.5)

        if not step_results:
            return jsonify({
                "success": True,
                "completion": "partial",
                "analysis": "还没有执行任何步骤",
                "need_continue": True,
            })

        total = len(step_results)
        success_count = sum(
            1 for r in step_results.values()
            if isinstance(r, dict) and r.get("success")
        )

        ratio = success_count / total if total > 0 else 0

        if ratio >= threshold:
            completion = "completed"
            need_continue = False
            analysis = f"{success_count}/{total} 步骤成功（{ratio:.0%}），达到阈值"
        elif ratio > 0:
            completion = "partial"
            need_continue = True
            analysis = f"{success_count}/{total} 步骤成功（{ratio:.0%}），建议继续执行"
        else:
            completion = "failed"
            need_continue = True
            analysis = f"所有步骤失败，需要重新规划"

        return jsonify({
            "success": True,
            "completion": completion,
            "analysis": analysis,
            "success_ratio": round(ratio, 2),
            "need_continue": need_continue,
        })
