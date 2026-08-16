"""
记忆总结 — 通过 AI 压缩/总结对话历史
- 作为 tool_registry 工具注册，供 LLM 在对话中调用
- 提供 /api/memory/summarize 端点，供前端直接调用
"""

import json
import re
import time

import requests
from flask import jsonify, request

from . import tool_registry

MEMORY_SUMMARIZE_DEFINITION = {
    "name": "memory_summarize",
    "description": (
        "压缩和总结对话历史记忆。"
        "将冗长的对话历史提炼为简洁的摘要，保留关键信息、决策和上下文。"
        "当对话历史过长时使用此工具压缩记忆，为后续对话释放 token 空间。"
        "输入包含要总结的消息列表和最大摘要长度。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "messages_json": {
                "type": "string",
                "description": "需要总结的消息列表的 JSON 字符串，格式为 [{\"role\":\"user/assistant\",\"content\":\"...\"}]",
            },
            "max_summary_length": {
                "type": "integer",
                "description": "摘要的最大字符数，默认 500",
                "default": 500,
            },
        },
        "required": ["messages_json"],
    },
}


def execute_memory_summarize(args: dict) -> str:
    """
    执行记忆总结。
    这个工具本身不直接调用 LLM，而是返回一个精心设计的提示词，
    告诉 LLM 如何总结这些消息。LLM 会在下一轮对话中执行实际的总结。
    """
    try:
        import json as _json
        messages_json = args.get("messages_json", "[]")
        max_length = args.get("max_summary_length", 500)

        # 解析消息
        messages = _json.loads(messages_json) if isinstance(messages_json, str) else messages_json
        if not isinstance(messages, list) or len(messages) == 0:
            return "❌ 错误：没有可总结的消息。"

        msg_count = len(messages)
        total_chars = sum(len(str(m.get("content", ""))) for m in messages)

        # 构建总结指令
        prompt = (
            f"📝 记忆总结任务\n"
            f"━━━━━━━━━━━━━━━\n"
            f"待总结消息：{msg_count} 条（共约 {total_chars} 字符）\n"
            f"目标长度：不超过 {max_length} 字符\n\n"
            f"请你在本轮回复中完成以下总结任务：\n"
            f"1. 提取对话中的关键信息和重要决策\n"
            f"2. 保留上下文脉络（谁说了什么、为什么）\n"
            f"3. 去掉重复和无关的内容\n"
            f"4. 将总结控制在 {max_length} 字符以内\n\n"
            f"⚠️ 重要：由于这个总结将替代原有的对话历史，请确保总结\n"
            f"包含了后续对话可能需要的所有关键信息。\n\n"
            f"--- 原始对话历史 ---\n"
        )

        for i, m in enumerate(messages):
            role = m.get("role", "unknown")
            content = str(m.get("content", ""))
            # 截断过长消息
            if len(content) > 2000:
                content = content[:2000] + "...（截断）"
            prompt += f"\n[{role.upper()}]: {content}\n"

        prompt += "\n--- 请开始你的总结 ---"

        return prompt

    except Exception as e:
        return f"❌ 记忆总结失败: {str(e)}"


# 注册工具
tool_registry.register("memory_summarize", MEMORY_SUMMARIZE_DEFINITION, execute_memory_summarize)


def register_routes(app):
    """注册记忆总结 API 路由"""
    from modules.config import get_config
    from modules.llm_client import chat_with_tools_sync

    @app.route("/api/memory/summarize", methods=["POST"])
    def api_memory_summarize():
        """使用 AI 总结对话历史"""
        cfg = get_config()
        data = request.get_json(force=True)

        messages = data.get("messages", [])
        model = data.get("model") or cfg.get("model", "gpt-4o-mini")
        api_base = data.get("api_base") or cfg.get("api_base")
        api_key = data.get("api_key") or cfg.get("api_key")
        max_keep = int(data.get("max_keep", 4))

        if not messages or len(messages) <= max_keep:
            return jsonify({
                "success": True,
                "summary": None,
                "message": f"消息数量不足（当前 {len(messages)} 条，需超过 {max_keep} 条）"
            })

        to_summarize = messages[:-max_keep]
        to_keep = messages[-max_keep:]

        # 构建文本供 AI 总结
        conversation_text = ""
        for m in to_summarize:
            role = m.get("role", "user")
            content = m.get("content", "")
            if isinstance(content, str):
                conversation_text += f"[{role}]: {content[:500]}\n"

        prompt = (
            "请将以下对话历史压缩为结构化摘要。输出纯 JSON（无 markdown 代码块标记）：\n"
            '{"summary":"简洁摘要（200字以内）","key_topics":["关键主题1","关键主题2"],"unfinished":"未完成的任务（无则留空）"}\n\n'
            "要求：\n"
            "1. 保留用户的所有需求和问题\n"
            "2. 保留 AI 执行的重要操作和结论\n"
            "3. 标记所有未完成的任务\n"
            "4. summary 字段控制在 200 字以内\n\n"
            "对话历史：\n" + conversation_text
        )

        try:
            result = chat_with_tools_sync(
                [
                    {"role": "system", "content": "你是一个对话摘要助手。将长对话压缩为简洁的结构化 JSON 摘要。只输出 JSON，不要任何解释文字。"},
                    {"role": "user", "content": prompt},
                ],
                http_session=app._http_session,
                api_base=api_base,
                api_key=api_key,
                model=model,
                max_tokens=800,
                temperature=0.3,
                stream=False,
            )

            if not result.get("success"):
                return jsonify({"success": False, "error": result.get("error", "总结请求失败")})

            content = result.get("content", "")

            # 解析 JSON
            try:
                json_match = re.search(r'\{[\s\S]*\}', content)
                if json_match:
                    summary_data = json.loads(json_match.group())
                else:
                    summary_data = {"summary": content[:500]}
            except json.JSONDecodeError:
                summary_data = {"summary": content[:500]}

            summary_data["summarized_at"] = time.time()
            summary_data["original_count"] = len(to_summarize)
            summary_data["kept_count"] = len(to_keep)

            return jsonify({
                "success": True,
                "summary": summary_data,
                "kept_messages": to_keep,
            })

        except Exception as e:
            return jsonify({"success": False, "error": str(e)})
