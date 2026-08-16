"""
顺序执行模块 — Sequential Executor
约束 LLM 按指定顺序调用工具，确保工具调用遵循预设的流程
"""

import json

from flask import jsonify, request

# ============================================================
# 顺序约束管理（内存存储）
# ============================================================
_sequences = {}  # sequence_id -> sequence config


def build_sequential_constraint(ordered_tools: list, strict: bool = True) -> str:
    """
    根据有序工具列表生成顺序约束的 system prompt 片段。

    - ordered_tools: 按执行顺序排列的工具名称列表
    - strict: True = 必须严格按顺序，False = 建议按顺序

    返回一段可注入 system prompt 的文本。
    """
    if not ordered_tools:
        return ""

    tool_sequence = " → ".join(ordered_tools)

    if strict:
        constraint = (
            f"\n\n## ⚠️ 顺序执行约束（必须严格遵守）\n"
            f"你必须严格按照以下顺序调用工具，**不得跳过或打乱顺序**：\n\n"
            f"**执行顺序**: {tool_sequence}\n\n"
            f"规则:\n"
            f"1. 只能从序列中的第一个工具开始调用\n"
            f"2. 每个工具调用完成后，才能调用序列中的下一个工具\n"
            f"3. 不能同时调用多个工具（禁止并行 tool calls）\n"
            f"4. 不能跳过序列中的任何工具\n"
            f"5. 如果某个工具执行失败，停止执行并报告错误\n"
            f"6. 所有工具调用完成后，总结执行结果\n\n"
            f"当前可用的工具及顺序:\n"
        )
        for i, name in enumerate(ordered_tools, 1):
            constraint += f"  {i}. `{name}`\n"
    else:
        constraint = (
            f"\n\n## 📋 建议执行顺序\n"
            f"建议按以下顺序调用工具: {tool_sequence}\n"
            f"尽量遵循此顺序，但可根据实际情况灵活调整。\n"
        )

    return constraint


def build_sequential_tools_prompt(ordered_tools: list) -> str:
    """
    生成一个简短的顺序提示，适用于发送给 LLM 的系统提示。

    与 build_sequential_constraint 不同，这个更简洁，
    适合作为日常 system prompt 的一部分。
    """
    if not ordered_tools:
        return ""

    steps = "\n".join(f"  第{i}步: 调用 `{name}`" for i, name in enumerate(ordered_tools, 1))
    return (
        f"\n\n[顺序执行模式]\n"
        f"你已接入顺序执行器，工具调用必须按以下步骤依次执行：\n"
        f"{steps}\n"
        f"每步完成后再进行下一步，不要跳过或并行调用。"
    )


# ============================================================
# Flask 路由
# ============================================================
def register_routes(app, http_session=None):
    @app.route("/api/sequential/build-prompt", methods=["POST"])
    def sequential_build_prompt():
        """
        根据有序工具列表生成顺序约束 system prompt。
        请求体: {"tools": ["tool_a", "tool_b", "tool_c"], "strict": true}
        响应: {"success": true, "constraint": "...", "tools_prompt": "..."}
        """
        data = request.get_json(force=True)
        tools = data.get("tools", [])
        strict = data.get("strict", True)

        if not tools:
            return jsonify({"success": False, "error": "工具列表不能为空"}), 400

        constraint = build_sequential_constraint(tools, strict)
        tools_prompt = build_sequential_tools_prompt(tools)

        return jsonify({
            "success": True,
            "constraint": constraint,
            "tools_prompt": tools_prompt,
            "ordered_tools": tools,
            "strict": strict,
        })

    @app.route("/api/sequential/validate", methods=["POST"])
    def sequential_validate():
        """
        验证工具调用是否遵循指定顺序。
        请求体: {"expected_order": ["a", "b", "c"], "actual_calls": ["a", "b"]}
        响应: {"valid": true/false, "violation": "..."}
        """
        data = request.get_json(force=True)
        expected = data.get("expected_order", [])
        actual = data.get("actual_calls", [])

        if not expected:
            return jsonify({"valid": True, "message": "无顺序约束"})

        # 检查 actual 是否按 expected 的顺序
        expected_idx = 0
        violations = []

        for call in actual:
            if expected_idx >= len(expected):
                violations.append(f"额外调用 '{call}'（序列已结束）")
                continue
            if call == expected[expected_idx]:
                expected_idx += 1
            else:
                # 检查是否在序列中但顺序不对
                if call in expected:
                    pos = expected.index(call)
                    if pos < expected_idx:
                        violations.append(f"'{call}' 已被跳过，不能回退调用")
                    else:
                        violations.append(f"'{call}' 调用顺序错误，期望 '{expected[expected_idx]}'，跳过了 {pos - expected_idx} 个工具")
                else:
                    violations.append(f"'{call}' 不在预期序列中")

        return jsonify({
            "valid": len(violations) == 0,
            "violations": violations,
            "progress": f"{expected_idx}/{len(expected)}",
            "remaining": expected[expected_idx:] if expected_idx < len(expected) else [],
        })
