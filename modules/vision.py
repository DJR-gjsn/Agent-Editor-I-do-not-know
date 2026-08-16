"""
Vision 多模态图片理解模块
接收 base64 图片 + 文本提示，调用多模态 API 进行分析
"""

import json
import time
from flask import Response, jsonify, request, stream_with_context

from .config import get_config
from .utils import make_sse_response


def register_routes(app, http_session=None):
    """注册路由，http_session 为可选的共享 HTTP 连接池"""
    import requests as _requests
    _send = http_session.post if http_session else _requests.post

    @app.route("/api/vision", methods=["POST"])
    def vision_analyze():
        data = request.get_json(force=True)
        image_b64 = (data.get("image") or "").strip()
        prompt = (data.get("prompt") or "请描述这张图片").strip()

        if not image_b64:
            return jsonify({"error": "image (base64) 不能为空"}), 400

        cfg = get_config()
        api_base = data.get("api_base") or cfg["api_base"]
        api_key = data.get("api_key") or cfg["api_key"]
        model = data.get("model") or "gpt-4o"

        # 确保 base64 有正确的 data URI 前缀
        if not image_b64.startswith("data:"):
            image_b64 = f"data:image/jpeg;base64,{image_b64}"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_b64}},
                    ],
                }
            ],
            "max_tokens": data.get("max_tokens", 1024),
            "stream": data.get("stream", False),
        }

        t0 = time.time()

        if payload["stream"]:
            def generate():
                resp = None
                try:
                    resp = _send(
                        f"{api_base}/chat/completions",
                        headers=headers,
                        json=payload,
                        stream=True,
                        timeout=120,
                    )
                    if resp.status_code != 200:
                        yield f"data: {json.dumps({'error': f'API 返回 {resp.status_code}'})}\n\n"
                        return
                    for line in resp.iter_lines(decode_unicode=True):
                        if not line:
                            continue
                        if line.startswith("data: "):
                            yield f"{line}\n\n"
                except Exception as e:
                    yield f"data: {json.dumps({'error': str(e)})}\n\n"
                finally:
                    if resp is not None:
                        resp.close()

            return make_sse_response(generate())

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
                content = body["choices"][0]["message"]["content"]
                return jsonify({
                    "success": True,
                    "content": content,
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
