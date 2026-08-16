"""
JSON Mode 结构化输出模块
强制 AI 按指定 JSON Schema 返回结构化数据
"""

import json
import time
from flask import jsonify, request

from .config import get_config


def register_routes(app, http_session=None):
    """注册路由，http_session 为可选的共享 HTTP 连接池"""
    import requests as _requests
    _send = http_session.post if http_session else _requests.post

    @app.route("/api/json-mode", methods=["POST"])
    def json_mode_generate():
        data = request.get_json(force=True)
        messages = data.get("messages", [])
        json_schema = data.get("json_schema")

        if not messages:
            return jsonify({"error": "messages 不能为空"}), 400
        if not json_schema:
            return jsonify({"error": "json_schema 不能为空"}), 400
        if not isinstance(json_schema, dict):
            return jsonify({"error": "json_schema 必须是一个 JSON 对象"}), 400
        if json_schema.get("type") != "object":
            return jsonify({"error": "json_schema 必须 type=object"}), 400

        cfg = get_config()
        api_base = data.get("api_base") or cfg["api_base"]
        api_key = data.get("api_key") or cfg["api_key"]
        model = data.get("model") or "gpt-4o"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": data.get("max_tokens", 2048),
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "response",
                    "strict": True,
                    "schema": json_schema,
                },
            },
        }

        t0 = time.time()

        try:
            resp = _send(
                f"{api_base}/chat/completions",
                headers=headers,
                json=payload,
                timeout=120,
            )
            latency_ms = round((time.time() - t0) * 1000)

            if resp.status_code == 200:
                body = resp.json()
                content_text = body["choices"][0]["message"]["content"]
                # 尝试解析返回的 JSON
                try:
                    parsed = json.loads(content_text)
                    return jsonify({
                        "success": True,
                        "content": content_text,
                        "parsed": parsed,
                        "latency_ms": latency_ms,
                        "model": model,
                    })
                except json.JSONDecodeError:
                    return jsonify({
                        "success": True,
                        "content": content_text,
                        "parsed": None,
                        "warning": "返回内容不是合法 JSON",
                        "latency_ms": latency_ms,
                        "model": model,
                    })
            else:
                return jsonify({
                    "success": False,
                    "error": f"HTTP {resp.status_code}: {resp.text[:300]}",
                    "latency_ms": latency_ms,
                })
        except Exception as e:
            latency_ms = round((time.time() - t0) * 1000)
            return jsonify({"success": False, "error": str(e), "latency_ms": latency_ms})
