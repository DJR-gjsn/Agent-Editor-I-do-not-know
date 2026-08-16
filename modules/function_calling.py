"""
Function Calling 工具管理模块
注册 / 列表 / 删除工具 JSON Schema 定义
"""

import threading
import time
from flask import jsonify, request

_store = {}
_lock = threading.Lock()


def register_routes(app):
    @app.route("/api/functions", methods=["GET"])
    def fc_list():
        with _lock:
            items = list(_store.values())
            items.sort(key=lambda x: x["created_at"], reverse=True)
            return jsonify(items)

    @app.route("/api/functions", methods=["POST"])
    def fc_create():
        data = request.get_json(force=True)
        name = (data.get("name") or "").strip()
        description = (data.get("description") or "").strip()
        parameters = data.get("parameters")

        if not name:
            return jsonify({"error": "name 不能为空"}), 400
        if not description:
            return jsonify({"error": "description 不能为空"}), 400
        if not parameters:
            return jsonify({"error": "parameters (JSON Schema) 不能为空"}), 400

        # 基本校验：必须包含 type: object
        if not isinstance(parameters, dict) or parameters.get("type") != "object":
            return jsonify({"error": "parameters 必须是合法的 JSON Schema，且 type 为 object"}), 400

        with _lock:
            if name in _store:
                return jsonify({"error": f"工具 '{name}' 已存在"}), 409
            item = {
                "name": name,
                "description": description,
                "parameters": parameters,
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            _store[name] = item
            return jsonify(item), 201

    @app.route("/api/functions/<name>", methods=["DELETE"])
    def fc_delete(name):
        with _lock:
            if name not in _store:
                return jsonify({"error": "未找到"}), 404
            del _store[name]
            return jsonify({"deleted": name})
