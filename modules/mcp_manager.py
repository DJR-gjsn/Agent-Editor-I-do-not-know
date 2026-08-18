"""
MCP server 管理：全局配置（data/mcp_config.json）+ 生命周期 + tool_registry 动态注册。

配置结构：
{"servers": [{"id": "git", "name": "...", "type": "stdio",
              "command": "npx", "args": [...], "enabled": true},
             {"id": "x", "name": "...", "type": "http",
              "url": "...", "token": "...", "enabled": true}]}
"""
import json
import os
import re
import threading

from flask import jsonify, request

from . import tool_registry
from .mcp_client import MCPClient, MCPError, HttpTransport, StdioTransport

TOOL_PREFIX = "mcp_ext_"
_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,32}$")

_DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "mcp_config.json")

_lock = threading.RLock()
_config_path = None
_servers = {}  # id -> {config, client, tools, connected, error, registered}


# ============================================================
# 配置读写（原子写）
# ============================================================
def _load_config() -> dict:
    path = _config_path
    if not path or not os.path.exists(path):
        return {"servers": []}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {"servers": []}
    except Exception:
        return {"servers": []}


def _save_config(data: dict):
    path = _config_path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ============================================================
# 连接与注册
# ============================================================
def _build_client(cfg):
    if cfg.get("type") == "http":
        return MCPClient(HttpTransport(cfg["url"], cfg.get("token")))
    return MCPClient(StdioTransport(cfg["command"], cfg.get("args", [])))


def _make_handler(client, tool_name):
    def handler(args):
        return client.call_tool(tool_name, args)
    return handler


def _register_tools(server_id, tools, client):
    registered = []
    for t in tools:
        name = t.get("name")
        if not name:
            continue
        full = f"{TOOL_PREFIX}{server_id}_{name}"
        definition = {
            "name": full,
            "description": t.get("description", ""),
            "parameters": t.get("inputSchema",
                                {"type": "object", "properties": {}}),
        }
        tool_registry.register(full, definition, _make_handler(client, name))
        registered.append(full)
    return registered


def _safe_close(client):
    """关闭 client（close 失败不阻塞注销/同步流程）"""
    if client is None:
        return
    try:
        client.close()
    except Exception:
        pass


def _unregister_tools(server_id):
    entry = _servers.get(server_id)
    for full in (entry or {}).get("registered", []):
        tool_registry.unregister(full)
    _safe_close((entry or {}).get("client"))


def _sync_one(cfg):
    server_id = cfg["id"]
    # 清理旧状态
    if server_id in _servers:
        _unregister_tools(server_id)
        _servers.pop(server_id, None)
    entry = {"config": cfg, "client": None, "tools": [],
             "connected": False, "error": None, "registered": []}
    if not cfg.get("enabled", True):
        _servers[server_id] = entry
        return entry
    client = None
    try:
        client = _build_client(cfg)
        client.initialize()
        tools = client.list_tools()
        registered = _register_tools(server_id, tools, client)
        entry.update(client=client, tools=tools, connected=True,
                     registered=registered)
    except MCPError as e:
        entry["error"] = str(e)
        _safe_close(client)
    _servers[server_id] = entry
    return entry


def load_and_sync():
    """从配置盘读全量并同步连接/注册；删除已不存在的 server"""
    with _lock:
        cfg = _load_config()
        ids = set()
        for s in cfg.get("servers", []):
            if not isinstance(s, dict) or not s.get("id"):
                continue
            ids.add(s["id"])
            _sync_one(s)
        for sid in list(_servers.keys()):
            if sid not in ids:
                _unregister_tools(sid)
                _servers.pop(sid, None)


def init_mcp_manager(path=None):
    """重定向配置路径并重新同步（测试/多实例用）。None 回退环境变量或默认路径。"""
    global _config_path
    with _lock:
        _config_path = path or os.environ.get("MCP_CONFIG_PATH") or _DEFAULT_CONFIG_PATH
    load_and_sync()


def _validate(cfg) -> str | None:
    """返回错误消息或 None"""
    if not isinstance(cfg, dict):
        return "配置必须是对象"
    if not cfg.get("id") or not _ID_RE.match(cfg["id"]):
        return "id 必填，且只能含字母/数字/下划线/连字符（≤32 字符）"
    if cfg.get("type") == "http":
        if not cfg.get("url"):
            return "HTTP 类型必须提供 url"
    elif cfg.get("type") == "stdio":
        if not cfg.get("command"):
            return "stdio 类型必须提供 command"
    else:
        return "type 必须是 stdio 或 http"
    return None


def add_server(cfg) -> dict:
    with _lock:
        err = _validate(cfg)
        if err:
            return {"success": False, "error": err}
        server_id = cfg["id"]
        if server_id in _servers:
            return {"success": False, "error": f"server id '{server_id}' 已存在"}
        data = _load_config()
        if any(s.get("id") == server_id for s in data.get("servers", [])):
            return {"success": False, "error": f"server id '{server_id}' 已存在"}
        data.setdefault("servers", []).append(cfg)
        _save_config(data)
        _sync_one(cfg)
        entry = _servers.get(server_id, {})
        if entry.get("error"):
            return {"success": False, "error": entry["error"],
                    "saved": True, "connected": False}
        return {"success": True, "connected": True,
                "tool_count": len(entry.get("tools", []))}


def update_server(server_id, cfg) -> dict:
    with _lock:
        if server_id not in _servers:
            return {"success": False, "error": f"server '{server_id}' 不存在"}
        if cfg.get("id") and cfg["id"] != server_id:
            return {"success": False, "error": "id 不可变更"}
        merged = dict(_servers[server_id]["config"])
        merged.update(cfg)
        merged["id"] = server_id
        err = _validate(merged)
        if err:
            return {"success": False, "error": err}
        data = _load_config()
        for i, s in enumerate(data.get("servers", [])):
            if s.get("id") == server_id:
                data["servers"][i] = merged
                break
        _save_config(data)
        _sync_one(merged)
        entry = _servers.get(server_id, {})
        if entry.get("error"):
            return {"success": False, "error": entry["error"],
                    "saved": True, "connected": False}
        return {"success": True, "connected": True,
                "tool_count": len(entry.get("tools", []))}


def remove_server(server_id) -> dict:
    with _lock:
        if server_id not in _servers:
            return {"success": False, "error": f"server '{server_id}' 不存在"}
        _unregister_tools(server_id)
        _servers.pop(server_id, None)
        data = _load_config()
        data["servers"] = [s for s in data.get("servers", [])
                           if s.get("id") != server_id]
        _save_config(data)
        return {"success": True}


def test_server(cfg) -> dict:
    """测试连接：initialize + list_tools，不注册不保存"""
    err = _validate(cfg)
    if err:
        return {"success": False, "error": err}
    client = _build_client(cfg)
    try:
        client.initialize()
        tools = client.list_tools()
        return {"success": True, "tool_count": len(tools),
                "tools": tools}
    except MCPError as e:
        return {"success": False, "error": str(e)}
    finally:
        client.close()


def get_status() -> list:
    with _lock:
        out = []
        for sid, e in _servers.items():
            cfg = e["config"]
            out.append({
                "id": sid,
                "name": cfg.get("name", sid),
                "type": cfg.get("type"),
                "enabled": cfg.get("enabled", True),
                "connected": e["connected"],
                "error": e["error"],
                "tool_count": len(e["tools"]),
                "tools": [t.get("name") for t in e["tools"]],
            })
        return out


def get_server_tools(server_id):
    with _lock:
        entry = _servers.get(server_id)
        return list(entry["tools"]) if entry else []


# ============================================================
# Flask 路由
# ============================================================
def register_routes(app):
    @app.route("/api/mcp/servers", methods=["GET"])
    def mcp_list():
        return jsonify({"success": True, "servers": get_status()})

    @app.route("/api/mcp/servers", methods=["POST"])
    def mcp_create():
        cfg = request.get_json(force=True, silent=True) or {}
        return jsonify(add_server(cfg))

    @app.route("/api/mcp/servers/<server_id>", methods=["PUT"])
    def mcp_update(server_id):
        cfg = request.get_json(force=True, silent=True) or {}
        return jsonify(update_server(server_id, cfg))

    @app.route("/api/mcp/servers/<server_id>", methods=["DELETE"])
    def mcp_delete(server_id):
        return jsonify(remove_server(server_id))

    @app.route("/api/mcp/servers/<server_id>/test", methods=["POST"])
    def mcp_test(server_id):
        cfg = request.get_json(force=True, silent=True) or {}
        cfg["id"] = cfg.get("id", server_id)
        return jsonify(test_server(cfg))

    @app.route("/api/mcp/servers/<server_id>/tools", methods=["GET"])
    def mcp_tools(server_id):
        tools = get_server_tools(server_id)
        if not any(s["id"] == server_id for s in get_status()):
            return jsonify({"success": False, "error": "server 不存在"})
        return jsonify({"success": True, "tools": tools})
