"""
Embeddings 文本向量化模块
将文本转换为向量，用于语义搜索与相似度计算
支持单文本和批量输入
"""

import json
import time
from flask import jsonify, request

from .config import get_config


def register_routes(app, http_session=None):
    """注册路由，http_session 为可选的共享 HTTP 连接池"""
    import requests as _requests
    _send = http_session.post if http_session else _requests.post

    @app.route("/api/embeddings", methods=["POST"])
    def embeddings_generate():
        data = request.get_json(force=True)
        text = (data.get("text") or "").strip()
        batch = data.get("batch")  # 可选的批量输入

        if not text and not batch:
            return jsonify({"error": "text 或 batch 不能为空"}), 400
        if batch and not isinstance(batch, list):
            return jsonify({"error": "batch 必须是字符串数组"}), 400

        cfg = get_config()
        api_base = data.get("api_base") or cfg["api_base"]
        api_key = data.get("api_key") or cfg["api_key"]
        model = data.get("model") or "text-embedding-3-small"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

        # 单文本或批量
        input_data = batch if batch else text

        payload = {
            "model": model,
            "input": input_data,
        }

        t0 = time.time()

        try:
            resp = _send(
                f"{api_base}/embeddings",
                headers=headers,
                json=payload,
                timeout=60,
            )
            latency_ms = round((time.time() - t0) * 1000)

            if resp.status_code == 200:
                body = resp.json()
                items = body["data"]
                tokens_used = body.get("usage", {}).get("total_tokens", 0)

                if batch:
                    embeddings = [item["embedding"] for item in items]
                    return jsonify({
                        "success": True,
                        "count": len(embeddings),
                        "dimensions": len(embeddings[0]) if embeddings else 0,
                        "tokens_used": tokens_used,
                        "latency_ms": latency_ms,
                        "model": model,
                    })
                else:
                    embedding = items[0]["embedding"]
                    return jsonify({
                        "success": True,
                        "embedding": embedding,
                        "embedding_preview": embedding[:10],
                        "dimensions": len(embedding),
                        "tokens_used": tokens_used,
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
