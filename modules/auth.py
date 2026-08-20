"""
用户认证：注册/登录/登出/会话 + 用户设置（/api/settings）
- 服务端会话：session_id 存 sessions 表，HttpOnly Cookie 传递
- 密码：werkzeug pbkdf2 哈希，绝不存明文
- 会话 7 天，滑动续期，过期惰性删除
"""
import json
import re
import uuid
from datetime import datetime, timedelta

from flask import jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from . import db

SESSION_TTL_DAYS = 7
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,32}$")


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ============================================================
# 业务函数（供路由与测试直接调用）
# ============================================================
def register(username, password):
    username = (username or "").strip()
    if not USERNAME_RE.match(username):
        return {"success": False, "error": "用户名须为 3-32 位字母/数字/下划线"}
    if not password or len(password) < 6:
        return {"success": False, "error": "密码至少 6 位"}
    if db.query_one("SELECT id FROM users WHERE username = ?", (username,)):
        return {"success": False, "error": "用户名已存在"}
    try:
        uid = db.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, generate_password_hash(password, method="pbkdf2:sha256")))
    except Exception:
        return {"success": False, "error": "用户名已存在"}
    return {"success": True, "user": {"id": uid, "username": username}}


def login(username, password):
    username = (username or "").strip()
    user = db.query_one(
        "SELECT id, username, password_hash FROM users WHERE username = ?",
        (username,))
    if not user or not check_password_hash(user["password_hash"], password or ""):
        return {"success": False, "error": "用户名或密码错误"}
    session_id = uuid.uuid4().hex
    expires = (datetime.now() + timedelta(days=SESSION_TTL_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    ua = (request.user_agent.string[:200] if request.user_agent else "") if request else ""
    ip = (request.remote_addr or "") if request else ""
    db.execute(
        "INSERT INTO sessions (id, user_id, expires_at, user_agent, ip) VALUES (?, ?, ?, ?, ?)",
        (session_id, user["id"], expires, ua, ip))
    return {"success": True, "session_id": session_id,
            "user": {"id": user["id"], "username": user["username"]}}


def logout(session_id):
    if session_id:
        db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))


def get_current_user():
    """从请求 Cookie 解析当前用户；过期/无效返回 None；有效则滑动续期"""
    sid = request.cookies.get("session_id")
    if not sid:
        return None
    row = db.query_one(
        "SELECT s.user_id, u.username, s.expires_at "
        "FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.id = ?",
        (sid,))
    if not row:
        return None
    expires = datetime.strptime(row["expires_at"], "%Y-%m-%d %H:%M:%S")
    if expires < datetime.now():
        db.execute("DELETE FROM sessions WHERE id = ?", (sid,))
        return None
    # 滑动续期：距过期不足一半时续期
    if expires < datetime.now() + timedelta(days=SESSION_TTL_DAYS // 2):
        new_exp = (datetime.now() + timedelta(days=SESSION_TTL_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
        db.execute("UPDATE sessions SET expires_at = ? WHERE id = ?", (new_exp, sid))
    return {"id": row["user_id"], "username": row["username"]}


def current_user_id():
    user = get_current_user()
    return user["id"] if user else None


# ============================================================
# Flask 路由
# ============================================================
def register_routes(app):
    @app.route("/api/auth/register", methods=["POST"])
    def auth_register():
        data = request.get_json(force=True, silent=True) or {}
        result = register(data.get("username", ""), data.get("password", ""))
        status = 201 if result["success"] else 400
        return jsonify(result), status

    @app.route("/api/auth/login", methods=["POST"])
    def auth_login():
        data = request.get_json(force=True, silent=True) or {}
        result = login(data.get("username", ""), data.get("password", ""))
        if not result["success"]:
            return jsonify(result), 401
        resp = jsonify(result)
        resp.set_cookie("session_id", result["session_id"],
                        max_age=SESSION_TTL_DAYS * 86400,
                        httponly=True, samesite="Lax")
        return resp

    @app.route("/api/auth/logout", methods=["POST"])
    def auth_logout():
        logout(request.cookies.get("session_id"))
        resp = jsonify({"success": True})
        resp.delete_cookie("session_id")
        return resp

    @app.route("/api/auth/me", methods=["GET"])
    def auth_me():
        user = get_current_user()
        if not user:
            return jsonify({"success": False, "error": "未登录"}), 401
        return jsonify({"success": True, "user": user})

    @app.route("/api/settings", methods=["GET"])
    def settings_get():
        uid = current_user_id()
        if not uid:
            return jsonify({"success": False, "error": "未登录"}), 401
        rows = db.query("SELECT key, value FROM user_settings WHERE user_id = ?", (uid,))
        settings = {}
        for r in rows:
            try:
                settings[r["key"]] = json.loads(r["value"])
            except (json.JSONDecodeError, TypeError):
                settings[r["key"]] = r["value"]
        return jsonify({"success": True, "settings": settings})

    @app.route("/api/settings/<key>", methods=["PUT"])
    def settings_put(key):
        uid = current_user_id()
        if not uid:
            return jsonify({"success": False, "error": "未登录"}), 401
        data = request.get_json(force=True, silent=True) or {}
        if "value" not in data:
            return jsonify({"success": False, "error": "缺少 value"}), 400
        db.execute(
            "INSERT INTO user_settings (user_id, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value, "
            "updated_at = datetime('now')",
            (uid, key, json.dumps(data["value"], ensure_ascii=False)))
        return jsonify({"success": True})

    @app.route("/api/settings/<key>", methods=["DELETE"])
    def settings_delete(key):
        uid = current_user_id()
        if not uid:
            return jsonify({"success": False, "error": "未登录"}), 401
        db.execute("DELETE FROM user_settings WHERE user_id = ? AND key = ?",
                   (uid, key))
        return jsonify({"success": True})
