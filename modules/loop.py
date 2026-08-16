"""
循环模块 — Plan ↔ Execute 循环控制器
管理 Plan → Executor → Reflect → Replan 的循环逻辑
"""

import json
import os
import time

from flask import jsonify, request

from .session_manager import TTLDict

# ============================================================
# 循环状态管理（TTL 字典：1小时过期，最多100个循环）
# ============================================================
_loop_states = TTLDict(max_size=100, ttl_seconds=3600)  # loop_id -> state dict


def create_loop(plan_id: str) -> str:
    """创建一个新的循环实例"""
    loop_id = f"loop_{int(time.time())}"
    _loop_states.set(loop_id, {
        "loop_id": loop_id,
        "plan_id": plan_id,
        "status": "idle",        # idle | running | paused | done
        "current_step": 0,
        "total_steps": 0,
        "iteration": 0,
        "max_iterations": 30,
        "results": [],
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    return loop_id


def get_loop(loop_id: str) -> dict:
    return _loop_states.get(loop_id)


def update_loop(loop_id: str, **kwargs):
    state = _loop_states.get(loop_id)
    if state:
        state.update(kwargs)


def should_continue(reflection: dict, iteration: int, max_iterations: int) -> dict:
    """
    根据 Plan 的反思结果判断是否继续循环。

    返回: {"continue": bool, "reason": str}
    """
    if iteration >= max_iterations:
        return {"continue": False, "reason": f"达到最大循环次数 ({max_iterations})"}

    if not reflection:
        return {"continue": False, "reason": "无反思结果"}

    completion = reflection.get("completion", "")
    need_replan = reflection.get("need_replan", False)
    issues = reflection.get("issues", [])

    # 已完成 → 停止
    if completion == "completed":
        return {"continue": False, "reason": "Plan 判断任务已完成"}

    # 需要重规划且有调整步骤 → 继续
    if need_replan and reflection.get("adjusted_steps"):
        return {"continue": True, "reason": "Plan 建议重规划，继续执行调整后的计划"}

    # 有问题但不需要重规划 → 继续尝试
    if issues and need_replan:
        return {"continue": True, "reason": f"存在 {len(issues)} 个问题，继续调整"}

    # 部分完成 → 继续
    if completion == "部分完成":
        return {"continue": True, "reason": "任务部分完成，继续执行剩余步骤"}

    # 默认：停止
    return {"continue": False, "reason": "Plan 未要求继续"}


# ============================================================
# Flask 路由
# ============================================================
def register_routes(app, http_session=None):
    @app.route("/api/loop/create", methods=["POST"])
    def loop_create():
        """创建循环实例"""
        data = request.get_json(force=True)
        plan_id = data.get("plan_id", "")
        max_iterations = int(data.get("max_iterations", 30))

        loop_id = create_loop(plan_id)
        update_loop(loop_id, max_iterations=max_iterations)

        state = _loop_states.get(loop_id)
        return jsonify({
            "success": True,
            "loop": state,
        })

    @app.route("/api/loop/<loop_id>", methods=["GET"])
    def loop_get(loop_id):
        """获取循环状态"""
        state = _loop_states.get(loop_id)
        if not state:
            return jsonify({"success": False, "error": "循环不存在"}), 404
        return jsonify({"success": True, "loop": state})

    @app.route("/api/loop/<loop_id>/check", methods=["POST"])
    def loop_check(loop_id):
        """
        检查是否应继续循环。
        请求体: {"reflection": {...}, "iteration": 3, "max_iterations": 10}
        响应: {"continue": true/false, "reason": "..."}
        """
        state = _loop_states.get(loop_id)
        if not state:
            return jsonify({"success": False, "error": "循环不存在"}), 404

        data = request.get_json(force=True)
        reflection = data.get("reflection", {})
        iteration = int(data.get("iteration", state.get("iteration", 0)))
        max_iter = int(data.get("max_iterations", state.get("max_iterations", 10)))

        decision = should_continue(reflection, iteration, max_iter)

        # 更新状态
        update_loop(loop_id, iteration=iteration)
        if not decision["continue"]:
            update_loop(loop_id, status="done")
        else:
            update_loop(loop_id, status="running")

        return jsonify({
            "success": True,
            "decision": decision,
            "loop": state,
        })

    @app.route("/api/loop/<loop_id>/update", methods=["POST"])
    def loop_update(loop_id):
        """更新循环状态"""
        state = _loop_states.get(loop_id)
        if not state:
            return jsonify({"success": False, "error": "循环不存在"}), 404

        data = request.get_json(force=True)
        allowed = ["status", "current_step", "total_steps", "iteration", "max_iterations"]
        for key in allowed:
            if key in data:
                state[key] = data[key]

        return jsonify({"success": True, "loop": state})
