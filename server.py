"""
Agent Editor V0.1 - Flask 后端
提供 Web 页面和 LLM API 代理（隐藏 API Key）
"""

import io
import json
import os
import sys
import tempfile
import threading
import time
import uuid
from collections import defaultdict
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_from_directory
from flask_compress import Compress

import requests

app = Flask(__name__)
Compress(app)

# 注册所有功能模块
from modules import register_all, tool_registry
from modules.config import get_config, has_api_key
from modules.utils import setup_logging, get_logger

register_all(app)

# ============================================================
# 日志
# ============================================================
setup_logging("wybzd")
logger = get_logger("wybzd")

# ============================================================
# 配置（从集中配置模块加载）
# ============================================================
_cfg = get_config()
API_BASE = _cfg["api_base"]
API_KEY = _cfg["api_key"]
MODEL = _cfg["model"]
MAX_TOKENS = _cfg["max_tokens"]
TEMPERATURE = _cfg["temperature"]
PORT = _cfg["port"]

# 复用 HTTP 连接池
http_session = requests.Session()
http_session.headers.update({"Content-Type": "application/json"})

# 聊天路由（SSE 流式对话）
from modules.chat_routes import register_chat_routes
register_chat_routes(app, http_session, _cfg)

# ============================================================
# 静态文件缓存（覆盖 debug 模式的 no-cache）
# ============================================================
STATIC_DIR = Path(__file__).parent / "static"


@app.route("/static/<path:filename>")
def static_files(filename):
    """自定义静态文件路由"""
    return send_from_directory(
        STATIC_DIR,
        filename,
        max_age=300,  # 5分钟缓存，开发阶段平衡性能与即时性
        conditional=True,
    )


@app.after_request
def _add_cache_headers(response):
    """为静态文件添加缓存头"""
    if request.path.startswith("/static/"):
        response.cache_control.max_age = 300
        response.cache_control.public = True
    return response


# ============================================================
# 请求频率限制
# ============================================================
_rate_limits = defaultdict(list)
_rate_lock = threading.Lock()
_RATE_WINDOW = 60
_RATE_MAX = 300
_last_cleanup = 0
_CLEANUP_INTERVAL = 300  # 每5分钟清理过期IP


@app.before_request
def rate_limit():
    """轻量级频率限制（静态文件、SSE 流、内部 API 除外）"""
    global _last_cleanup
    path = request.path
    if path.startswith("/static") or path.startswith("/api/chat") or path.startswith("/api/memory"):
        return
    ip = request.remote_addr or "127.0.0.1"
    now = time.time()

    with _rate_lock:
        # 清理当前 IP 的过期记录
        _rate_limits[ip] = [t for t in _rate_limits[ip] if now - t < _RATE_WINDOW]
        if len(_rate_limits[ip]) >= _RATE_MAX:
            return jsonify({"error": "请求过于频繁，请稍后重试"}), 429
        _rate_limits[ip].append(now)

        # 定期清理过期 IP 条目
        if now - _last_cleanup > _CLEANUP_INTERVAL:
            stale = [k for k, v in _rate_limits.items() if not v or now - v[-1] > _RATE_WINDOW]
            for k in stale:
                del _rate_limits[k]
            _last_cleanup = now


# ============================================================
# 路由
# ============================================================
@app.route("/")
def index():
    """管理后台"""
    return render_template("admin.html")


@app.route("/editor")
def editor_page():
    """Agent Editor"""
    return render_template("index.html")


@app.route("/chat")
def chat_page():
    """前端 AI 对话页面"""
    return render_template("chat.html")


@app.route("/api/health")
def health():
    """健康检查"""
    return jsonify({"status": "ok", "timestamp": time.time()})


@app.route("/api/config")
def get_api_config():
    """返回当前配置（不暴露完整 API Key）"""
    return jsonify({
        "model": MODEL,
        "api_base": API_BASE,
        "has_api_key": has_api_key(),
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
    })


@app.route("/api/tools/definitions")
def tools_definitions():
    """返回 tool_registry 中所有已注册的工具定义（供前端连线时获取）"""
    return jsonify(tool_registry.get_all_definitions())


# ── 组件类型 → 后端源文件映射 ──
_COMPONENT_SOURCE_MAP = {
    "web_search": "modules/web_search.py",
    "calculator": "modules/calculator.py",
    "code_executor": "modules/code_executor.py",
    "text_tools": "modules/text_tools.py",
    "time_query": "modules/common_tools.py",
    "url_fetch": "modules/common_tools.py",
    "file_ops": "modules/file_search_tools.py",
    "json_query": "modules/common_tools.py",
    "vector_memory": "modules/embeddings.py",
    "vision": "modules/vision.py",
    "mcp_word": "modules/mcp_office.py",
    "mcp_excel": "modules/mcp_office.py",
    "mcp_ppt": "modules/mcp_office.py",
    "mcp_pdf": "modules/mcp_pdf.py",
    "mcp_weather": "modules/mcp_weather.py",
    "mcp_database": "modules/mcp_database.py",
    "mcp_git": "modules/mcp_git.py",
    "mcp_clipboard": "modules/mcp_clipboard.py",
    "mcp_encoding": "modules/mcp_encoding.py",
    "mcp_system": "modules/mcp_system.py",
    "mcp_email": "modules/mcp_email.py",
    "mcp_translate": "modules/mcp_translate.py",
    "mcp_calendar": "modules/mcp_calendar.py",
    "mcp_finance": "modules/mcp_finance.py",
    "mcp_geocode": "modules/mcp_geocode.py",
    "mcp_navigation": "modules/mcp_navigation.py",
    "memory": "modules/memory.py",
    "memory_summarizer": "modules/memory_summarizer.py",
    "plan": "modules/plan.py",
    "agent": "modules/agent.py",
    "executor": "modules/executor.py",
    "sequential_executor": "modules/sequential_executor.py",
    "reflection": "modules/reflection.py",
    "token_manager": "modules/token_manager.py",
    "working_memory": "modules/common_tools.py",
    "function_calling": "modules/function_calling.py",
    "json_mode": "modules/json_mode.py",
    "system_prompt": "server.py",
    "loop": "modules/loop.py",
    "conditional": "modules/common_tools.py",
    "skills_manager": "modules/skills_manager.py",
    "skill_auto_call": "server.py",
    "skill_document": "modules/mcp_skills.py",
    "skill_frontend": "modules/mcp_skills.py",
    "skill_uiux": "modules/mcp_skills.py",
    "skill_find": "modules/mcp_skills.py",
    "skill_creator": "modules/mcp_skills.py",
    "skill_super": "modules/mcp_skills.py",
    "skill_pua": "modules/mcp_skills.py",
}


@app.route("/api/component-source/<comp_type>")
def component_source(comp_type):
    """返回组件对应的后端源文件代码（只读，供前端属性面板展示）"""
    rel_path = _COMPONENT_SOURCE_MAP.get(comp_type)
    if not rel_path:
        return jsonify({"error": f"未知组件类型: {comp_type}"}), 404
    file_path = Path(__file__).parent / rel_path
    if not file_path.exists():
        return jsonify({"error": f"源文件不存在: {rel_path}"}), 404
    try:
        code = file_path.read_text(encoding="utf-8", errors="replace")
        # 最多返回 300 行
        lines = code.split("\n")[:300]
        return jsonify({
            "component_type": comp_type,
            "source_file": rel_path,
            "code": "\n".join(lines),
            "total_lines": len(code.split("\n")),
            "truncated": len(code.split("\n")) > 300,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/verify", methods=["POST"])
def verify():
    """测试 API 连接 — 发送最小请求验证连通性"""
    data = request.get_json(force=True)
    api_base = data.get("api_base", API_BASE)
    api_key = data.get("api_key", API_KEY)
    model = data.get("model", MODEL)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "stream": False,
    }

    t0 = time.time()

    def _verify_result(success, error=None):
        latency_ms = round((time.time() - t0) * 1000)
        result = {
            "success": success,
            "latency_ms": latency_ms,
            "model": model,
            "api_base": api_base,
        }
        if error:
            result["error"] = error
        return jsonify(result)

    try:
        resp = http_session.post(
            f"{api_base}/chat/completions",
            headers=headers,
            json=payload,
            timeout=15,
        )

        if resp.status_code == 200:
            return _verify_result(True)
        else:
            error_body = resp.text[:300]
            return _verify_result(False, f"HTTP {resp.status_code}: {error_body}")

    except requests.exceptions.ConnectionError:
        return _verify_result(False, "连接失败，请检查 API 地址")
    except requests.exceptions.Timeout:
        return _verify_result(False, "连接超时（15秒），请检查网络或 API 地址")
    except Exception as e:
        return _verify_result(False, str(e))


# ============================================================
# 项目管理 API
# ============================================================
PROJECTS_DIR = Path(__file__).parent / "data" / "projects"


def _ensure_projects_dir():
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)


def _project_path(project_id):
    return PROJECTS_DIR / f"{project_id}.json"


def _read_project(project_id):
    path = _project_path(project_id)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _summarize_project(data):
    layout = data.get("layout", {})
    comps = layout.get("components", [])
    conns = layout.get("connections", [])
    return {
        "id": data["id"],
        "name": data.get("name", "未命名"),
        "componentCount": len(comps),
        "connectionCount": len(conns),
        "updatedAt": data.get("updatedAt", data.get("createdAt", "")),
    }


@app.route("/projects")
def projects_page():
    return render_template("projects.html")


@app.route("/api/projects", methods=["GET"])
def api_list_projects():
    _ensure_projects_dir()
    projects = []
    for path in sorted(PROJECTS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        data = _read_project(path.stem)
        if data:
            projects.append(_summarize_project(data))
    return jsonify(projects)


# 布局合并保护字段：传入为空时保留服务器已有值，防止自动保存意外清空对话历史
_PROTECTED_LAYOUT_FIELDS = (
    "messages", "searchHistory", "calcHistory", "codeHistory", "textHistory",
    "planHistory", "reflHistory", "agentLog", "loopLog",
    "execLastResult", "currentPlan", "wmStore", "vectorDocs",
)


def _merge_layout(incoming: dict, existing: dict) -> dict:
    """合并布局：拓扑以传入为准，但对话/历史类字段在传入为空时保留已有值。

    根因：编辑器自动保存（saveLayout → POST /api/projects）整体替换 layout，
    若某次保存携带空 messages，会把项目里存储的对话历史静默抹掉。
    此函数按组件 id 合并，仅保护"历史类"字段，位置/连线/API 设置等以传入为准。
    """
    if not isinstance(incoming, dict):
        return existing if isinstance(existing, dict) else incoming
    result = json.loads(json.dumps(incoming))  # 深拷贝，避免修改调用方数据
    existing_comps = {}
    if isinstance(existing, dict):
        for c in existing.get("components", []):
            if isinstance(c, dict) and "id" in c:
                existing_comps[c["id"]] = c
    merged_comps = []
    for comp in result.get("components", []):
        if isinstance(comp, dict) and comp.get("id") in existing_comps:
            old = existing_comps[comp["id"]]
            for field in _PROTECTED_LAYOUT_FIELDS:
                if field in old and not comp.get(field):
                    comp[field] = old[field]
        merged_comps.append(comp)
    result["components"] = merged_comps
    return result


@app.route("/api/projects", methods=["POST"])
def api_create_or_update_project():
    """创建新项目或更新已有项目"""
    _ensure_projects_dir()
    body = request.get_json(force=True)
    project_id = body.get("id")

    if project_id:
        existing = _read_project(project_id)
        if not existing:
            return jsonify({"error": "项目不存在"}), 404
        existing["name"] = body.get("name", existing.get("name", "未命名"))
        existing["layout"] = _merge_layout(body.get("layout", {}), existing.get("layout", {}))
        existing["updatedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
        data = existing
    else:
        project_id = "proj_" + uuid.uuid4().hex[:10]
        data = {
            "id": project_id,
            "name": body.get("name", "未命名"),
            "layout": body.get("layout", {}),
            "createdAt": time.strftime("%Y-%m-%d %H:%M:%S"),
            "updatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    with open(_project_path(project_id), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return jsonify({"id": project_id, "name": data["name"]})


@app.route("/api/projects/<project_id>", methods=["GET"])
def api_get_project(project_id):
    data = _read_project(project_id)
    if not data:
        return jsonify({"error": "项目不存在"}), 404
    return jsonify(data)


@app.route("/api/projects/<project_id>", methods=["DELETE"])
def api_delete_project(project_id):
    path = _project_path(project_id)
    if path.exists():
        path.unlink()
    return jsonify({"ok": True})


# ============================================================
# 统一生成文件列表 API（聚合所有 workspace）
# ============================================================
# 简易 TTL 缓存：避免前端轮询时重复扫描文件系统
_files_cache = {"data": None, "ts": 0}
_FILES_CACHE_TTL = 5  # 秒

_WORKSPACE_DIRS = {
    "office": Path(tempfile.gettempdir()) / "mcp_office_workspace",
    "pdf": Path(tempfile.gettempdir()) / "mcp_pdf_output",
    "common": Path(tempfile.gettempdir()) / "common_tools_workspace",
    "qrcode": Path(tempfile.gettempdir()) / "mcp_qrcodes",
}

_FILE_TYPE_MAP = {
    ".docx": "word", ".xlsx": "excel", ".pptx": "ppt",
    ".pdf": "pdf", ".png": "image", ".jpg": "image", ".jpeg": "image",
    ".txt": "text", ".md": "markdown", ".json": "json", ".csv": "csv",
    ".py": "code", ".js": "code", ".html": "html", ".css": "css",
}


@app.route("/api/chat/generated-files/<session_id>", methods=["GET", "DELETE"])
def chat_generated_files(session_id):
    """聚合扫描所有 workspace，或清空所有临时文件"""
    # DELETE：清空所有 workspace 中的临时文件
    if request.method == "DELETE":
        deleted = 0
        for ws_key, ws_path in _WORKSPACE_DIRS.items():
            if not ws_path.exists():
                continue
            if ws_key == "office":
                for sd in ws_path.iterdir():
                    if sd.is_dir():
                        for f in sd.iterdir():
                            if f.is_file():
                                try:
                                    f.unlink()
                                    deleted += 1
                                except OSError:
                                    pass
            else:
                for f in ws_path.iterdir():
                    if f.is_file():
                        try:
                            f.unlink()
                            deleted += 1
                        except OSError:
                            pass
        logger.info("cleared %d generated files across all workspaces", deleted)
        # 失效文件列表缓存
        _files_cache["data"] = None
        return jsonify({"success": True, "deleted": deleted})

    # GET：返回文件列表（带短期缓存避免轮询重复扫描）
    now = time.time()
    if _files_cache["data"] is not None and (now - _files_cache["ts"]) < _FILES_CACHE_TTL:
        return jsonify(_files_cache["data"])

    files = []
    seen_names = set()

    for ws_key, ws_path in _WORKSPACE_DIRS.items():
        if not ws_path.exists():
            continue

        if ws_key == "office":
            # Office workspace: 扫描所有 session 子目录（确保不漏掉任何文件）
            scan_dirs = []
            if ws_path.exists():
                # 优先扫描指定 session
                for sid in [session_id, "default"]:
                    sd = ws_path / sid
                    if sd.exists():
                        scan_dirs.append(sd)
                # 兜底：扫描所有其他 session 子目录
                for sd in sorted(ws_path.iterdir()):
                    if sd.is_dir() and sd not in scan_dirs:
                        scan_dirs.append(sd)
        else:
            scan_dirs = [ws_path] if ws_path.exists() else []

        for scan_dir in scan_dirs:
            if not scan_dir or not scan_dir.exists():
                continue

            for f in scan_dir.iterdir():
                if not f.is_file():
                    continue
                # 去重（同一文件可能出现在多个 session 目录）
                if f.name in seen_names:
                    continue
                seen_names.add(f.name)
                ext = f.suffix.lower()
                file_type = _FILE_TYPE_MAP.get(ext, "other")
                try:
                    stat = f.stat()
                    # 记录 session 子目录（用于下载时定位文件）
                    sub_session = scan_dir.name if ws_key == "office" else ""
                    files.append({
                        "name": f.name,
                        "size": stat.st_size,
                        "size_display": _format_file_size(stat.st_size),
                        "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
                        "type": file_type,
                        "workspace": ws_key,
                        "ext": ext,
                        "sub_session": sub_session,  # Office 文件的 session 子目录名
                    })
                except OSError:
                    pass

    # 按修改时间倒序
    files.sort(key=lambda f: f["modified"], reverse=True)

    # 类型优先级排序：Office > PDF > 图片 > 其他
    type_order = {"word": 1, "excel": 1, "ppt": 1, "pdf": 2, "image": 3, "csv": 4, "json": 4, "text": 5, "code": 5, "other": 6}
    files.sort(key=lambda f: (type_order.get(f["type"], 6), f["modified"]), reverse=False)

    result = {
        "files": files,
        "count": len(files),
        "session_id": session_id,
        "workspaces": {k: str(v) for k, v in _WORKSPACE_DIRS.items()},
    }
    # 更新缓存
    _files_cache["data"] = result
    _files_cache["ts"] = now
    return jsonify(result)


def _format_file_size(size: int) -> str:
    """格式化文件大小"""
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.0f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


# ============================================================
# 存储路径配置 API（前后端同步）
# ============================================================
STORAGE_CONFIG_FILE = Path(__file__).parent / "data" / "storage_config.json"


def _read_storage_config() -> dict:
    """读取存储配置"""
    if STORAGE_CONFIG_FILE.exists():
        try:
            return json.loads(STORAGE_CONFIG_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"path": "", "name": "", "updatedAt": ""}


def _write_storage_config(cfg: dict):
    """写入存储配置"""
    STORAGE_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    STORAGE_CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


@app.route("/api/config/storage-path", methods=["GET", "POST"])
def config_storage_path():
    """获取或更新存储路径配置（前后端同步）"""
    if request.method == "GET":
        return jsonify(_read_storage_config())

    data = request.get_json(force=True)
    cfg = _read_storage_config()
    if "path" in data:
        cfg["path"] = data["path"]
    if "name" in data:
        cfg["name"] = data["name"]
    cfg["updatedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _write_storage_config(cfg)
    logger.info("storage path updated: %s", cfg.get("name", cfg.get("path", "")))
    return jsonify({"success": True, "config": cfg})


# ============================================================
# 启动
# ============================================================
if __name__ == "__main__":
    # 设置 stdout 编码避免 Windows GBK 乱码
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    # 环境判断：FLASK_ENV=production 时使用生产模式
    is_debug = os.getenv("FLASK_ENV", "").lower() != "production"

    logger.info("=" * 50)
    logger.info("  Agent Editor V0.1")
    logger.info("  LLM Model: %s", MODEL)
    logger.info("  URL: http://localhost:%d", PORT)
    logger.info("  Mode: %s", "debug" if is_debug else "production")
    logger.info("=" * 50)

    app.run(host="0.0.0.0", port=PORT, debug=is_debug)
