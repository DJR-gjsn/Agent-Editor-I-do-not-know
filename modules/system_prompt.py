"""
System Prompt 管理模块
CRUD 系统提示词，为 AI 提供角色与行为约束
"""

import threading
import time
from flask import jsonify, request

_store = {}
_lock = threading.Lock()
_next_id = 1


def register_routes(app):
    @app.route("/api/system-prompt", methods=["GET"])
    def sp_list():
        with _lock:
            items = [
                {
                    "id": v["id"],
                    "name": v["name"],
                    "created_at": v["created_at"],
                    "updated_at": v["updated_at"],
                    "content_preview": v["content"][:80] + ("..." if len(v["content"]) > 80 else ""),
                }
                for v in _store.values()
            ]
            # 按更新时间倒序
            items.sort(key=lambda x: x["updated_at"], reverse=True)
            return jsonify(items)

    @app.route("/api/system-prompt", methods=["POST"])
    def sp_create():
        global _next_id
        data = request.get_json(force=True)
        name = (data.get("name") or "").strip()
        content = (data.get("content") or "").strip()
        if not name:
            return jsonify({"error": "name 不能为空"}), 400
        if not content:
            return jsonify({"error": "content 不能为空"}), 400

        with _lock:
            sid = str(_next_id)
            _next_id += 1
            now = time.strftime("%Y-%m-%d %H:%M:%S")
            item = {"id": sid, "name": name, "content": content, "created_at": now, "updated_at": now}
            _store[sid] = item
            return jsonify(item), 201

    @app.route("/api/system-prompt/<sid>", methods=["GET"])
    def sp_get(sid):
        with _lock:
            item = _store.get(sid)
            if not item:
                return jsonify({"error": "未找到"}), 404
            return jsonify(item)

    @app.route("/api/system-prompt/<sid>", methods=["PUT"])
    def sp_update(sid):
        data = request.get_json(force=True)
        with _lock:
            item = _store.get(sid)
            if not item:
                return jsonify({"error": "未找到"}), 404
            if "name" in data:
                item["name"] = (data["name"] or "").strip()
            if "content" in data:
                item["content"] = (data["content"] or "").strip()
            item["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            return jsonify(item)

    @app.route("/api/system-prompt/<sid>", methods=["DELETE"])
    def sp_delete(sid):
        with _lock:
            if sid not in _store:
                return jsonify({"error": "未找到"}), 404
            del _store[sid]
            return jsonify({"deleted": sid})
