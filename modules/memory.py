"""
Memory 记忆模块 — 对话历史后端持久化
提供会话记忆的保存、加载、列表和清理 API

特性:
- 按项目隔离：每个 project_id 拥有独立的记忆空间
- 持久保存：记忆永久保留，不会被自动清理
- 手动清空：只有用户点击清空才会删除记忆
- 存储方式: JSON 文件 (data/memories/<project_id>/)
"""

import json
import os
import time
import uuid
from pathlib import Path

from flask import request, jsonify

# 数据目录
BASE_DIR = Path(__file__).parent.parent / "data" / "memories"


def _ensure_dir(project_id: str = None):
    """确保项目记忆目录存在"""
    if project_id:
        (BASE_DIR / project_id).mkdir(parents=True, exist_ok=True)
    else:
        BASE_DIR.mkdir(parents=True, exist_ok=True)


def _get_session_path(project_id: str, session_id: str) -> Path:
    """获取项目内会话文件路径"""
    return BASE_DIR / project_id / f"{session_id}.json"


def _load_session(project_id: str, session_id: str) -> dict:
    """加载项目内会话数据，不存在则返回空"""
    path = _get_session_path(project_id, session_id)
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return _new_session(project_id, session_id)


def _save_session(project_id: str, session_id: str, data: dict):
    """保存项目内会话数据到文件（原子写入）"""
    _ensure_dir(project_id)
    data["project_id"] = project_id
    data["updated_at"] = time.time()
    path = _get_session_path(project_id, session_id)
    # 原子写入：先写临时文件，再替换
    tmp_path = path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp_path.replace(path)


def _new_session(project_id: str, session_id: str) -> dict:
    """创建新会话结构"""
    return {
        "project_id": project_id,
        "session_id": session_id,
        "title": "",
        "messages": [],
        "created_at": time.time(),
        "updated_at": time.time(),
        "message_count": 0,
    }


def _list_sessions(project_id: str) -> list:
    """列出指定项目下所有会话"""
    project_dir = BASE_DIR / project_id
    if not project_dir.exists():
        return []
    sessions = []
    for path in sorted(project_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            sessions.append({
                "session_id": data.get("session_id", path.stem),
                "project_id": project_id,
                "title": data.get("title", "未命名会话"),
                "message_count": data.get("message_count", len(data.get("messages", []))),
                "created_at": data.get("created_at", 0),
                "updated_at": data.get("updated_at", 0),
                "preview": _get_preview(data.get("messages", [])),
            })
        except (json.JSONDecodeError, OSError):
            pass
    return sessions


def _get_preview(messages: list) -> str:
    """获取会话预览文本"""
    for m in reversed(messages):
        content = m.get("content", "")
        if isinstance(content, str) and content.strip():
            return content[:80] + ("…" if len(content) > 80 else "")
    return ""


def _auto_title(messages: list) -> str:
    """从第一条用户消息自动生成标题"""
    for m in messages:
        if m.get("role") == "user":
            content = m.get("content", "")
            if isinstance(content, str):
                return content[:30] + ("…" if len(content) > 30 else "")
    return "新对话"


def _clear_project_memories(project_id: str):
    """清空指定项目的所有记忆文件（含项目子目录 + 根目录旧格式孤儿文件）"""
    deleted = 0

    # 1. 清空项目子目录
    project_dir = BASE_DIR / project_id
    if project_dir.exists():
        for path in project_dir.glob("*.json"):
            try:
                path.unlink()
                deleted += 1
            except OSError:
                pass

    # 2. 清空根目录下的旧格式孤儿文件（不在任何项目子目录中的 .json）
    for path in BASE_DIR.glob("*.json"):
        if not path.is_file():
            continue
        try:
            path.unlink()
            deleted += 1
        except OSError:
            pass

    return deleted


def register_routes(app):
    """注册记忆管理 API 路由"""

    @app.route("/api/memory/sessions", methods=["GET"])
    def memory_list_sessions():
        """列出指定项目的所有已保存会话"""
        project_id = request.args.get("project_id", "default")
        try:
            sessions = _list_sessions(project_id)
            return jsonify({"success": True, "sessions": sessions, "project_id": project_id})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)})

    @app.route("/api/memory/save", methods=["POST"])
    def memory_save():
        """保存或更新项目内会话记忆"""
        data = request.get_json(force=True)
        project_id = data.get("project_id", "default")
        session_id = data.get("session_id")
        messages = data.get("messages", [])
        title = data.get("title", "")

        if not session_id:
            session_id = str(uuid.uuid4())[:8]

        # 加载现有会话或创建新的
        session = _load_session(project_id, session_id)

        if messages:
            session["messages"] = messages
            session["message_count"] = len(messages)

        if title:
            session["title"] = title
        elif not session.get("title") and messages:
            session["title"] = _auto_title(messages)

        _save_session(project_id, session_id, session)

        return jsonify({
            "success": True,
            "session_id": session_id,
            "project_id": project_id,
            "message_count": session["message_count"],
            "title": session["title"],
        })

    @app.route("/api/memory/load/<session_id>", methods=["GET"])
    def memory_load(session_id):
        """加载指定项目内会话的完整记忆"""
        project_id = request.args.get("project_id", "default")
        try:
            session = _load_session(project_id, session_id)
            return jsonify({
                "success": True,
                "session": session,
            })
        except Exception as e:
            return jsonify({"success": False, "error": str(e)})

    @app.route("/api/memory/delete/<session_id>", methods=["DELETE"])
    def memory_delete(session_id):
        """删除项目内指定会话"""
        project_id = request.args.get("project_id", "default")
        path = _get_session_path(project_id, session_id)
        if path.exists():
            try:
                path.unlink()
                return jsonify({"success": True, "message": "会话已删除"})
            except OSError as e:
                return jsonify({"success": False, "error": str(e)})
        return jsonify({"success": False, "error": "会话不存在"})

    @app.route("/api/memory/append", methods=["POST"])
    def memory_append():
        """追加一条消息到项目内会话（增量同步）"""
        data = request.get_json(force=True)
        project_id = data.get("project_id", "default")
        session_id = data.get("session_id")
        message = data.get("message")  # {role, content}

        if not session_id or not message:
            return jsonify({"success": False, "error": "缺少 session_id 或 message"})

        session = _load_session(project_id, session_id)
        session["messages"].append(message)
        session["message_count"] = len(session["messages"])

        if not session.get("title"):
            session["title"] = _auto_title(session["messages"])

        _save_session(project_id, session_id, session)

        return jsonify({
            "success": True,
            "message_count": session["message_count"],
        })

    @app.route("/api/memory/clear-project/<project_id>", methods=["DELETE"])
    def memory_clear_project(project_id):
        """清空指定项目的所有记忆（用户点击清空时调用）"""
        try:
            deleted = _clear_project_memories(project_id)
            return jsonify({
                "success": True,
                "message": f"已清空项目记忆",
                "deleted": deleted,
            })
        except Exception as e:
            return jsonify({"success": False, "error": str(e)})
