"""
MCP Git 版本控制服务模块
提供 Git 仓库操作工具：状态、日志、差异、分支等
"""

import subprocess
import time
from pathlib import Path

from flask import jsonify, request

from . import tool_registry

# ============================================================
# 会话配置
# ============================================================
_connections = {}  # session_id -> {repo_path, connected, last_test}


def _get_conn(session_id: str) -> dict:
    if session_id not in _connections:
        _connections[session_id] = {
            "repo_path": "",
            "connected": False,
            "last_test": None,
        }
    return _connections[session_id]


def _run_git(repo_path: str, *args, timeout: int = 10) -> tuple[int, str, str]:
    """在指定仓库路径执行 git 命令，返回 (returncode, stdout, stderr)"""
    try:
        proc = subprocess.run(
            ["git", "-C", repo_path, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except FileNotFoundError:
        return -1, "", "Git 未安装或不在 PATH 中"
    except subprocess.TimeoutExpired:
        return -2, "", "命令执行超时"


# ============================================================
# 工具定义
# ============================================================
GIT_STATUS_DEF = {
    "name": "git_status",
    "description": (
        "获取 Git 仓库的当前状态，包括修改、新增、删除的文件列表。"
        "当用户询问 git 状态、改了哪些文件时使用。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "会话 ID",
            },
        },
        "required": [],
    },
}

GIT_LOG_DEF = {
    "name": "git_log",
    "description": (
        "获取 Git 仓库的提交历史。"
        "当用户询问最近提交、提交记录、谁改了什么时使用。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "count": {
                "type": "integer",
                "description": "显示最近几条提交，默认 10，最大 30",
                "default": 10,
            },
            "session_id": {
                "type": "string",
                "description": "会话 ID",
            },
        },
        "required": [],
    },
}

GIT_DIFF_DEF = {
    "name": "git_diff",
    "description": (
        "获取 Git 仓库中未暂存的变更内容。"
        "当用户询问具体改了哪些代码、查看差异时使用。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "file": {
                "type": "string",
                "description": "可选，限定查看某个文件的差异。不指定则显示所有文件。",
            },
            "staged": {
                "type": "boolean",
                "description": "是否查看暂存区差异（git diff --staged），默认 False 查看工作区差异",
                "default": False,
            },
            "session_id": {
                "type": "string",
                "description": "会话 ID",
            },
        },
        "required": [],
    },
}

GIT_BRANCH_DEF = {
    "name": "git_branch",
    "description": (
        "列出 Git 仓库的所有分支。"
        "当用户询问当前分支、有哪些分支时使用。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "会话 ID",
            },
        },
        "required": [],
    },
}


# ============================================================
# 执行器
# ============================================================
def _get_repo(session_id: str):
    conn = _get_conn(session_id)
    repo_path = conn.get("repo_path", "")
    if not repo_path:
        # 自动检测：从当前工作目录向上查找 .git 目录
        auto_path = _auto_detect_git_repo()
        if auto_path:
            conn["repo_path"] = auto_path
            conn["connected"] = True
            return str(auto_path), None
        return None, "❌ Git 仓库未配置且无法自动检测。请在 Git 服务面板中设置仓库路径。"
    p = Path(repo_path).expanduser().resolve()
    if not p.exists() or not (p / ".git").exists():
        return None, f"❌ 路径 '{repo_path}' 不是有效的 Git 仓库（无 .git 目录）。"
    return str(p), None


def _auto_detect_git_repo() -> Path | None:
    """从当前工作目录向上查找 .git 目录，自动检测 Git 仓库"""
    try:
        cwd = Path.cwd()
        for parent in [cwd] + list(cwd.parents):
            if (parent / ".git").exists():
                return parent
    except Exception:
        pass
    return None


def _exec_git_status(args: dict) -> str:
    session_id = args.get("session_id", "default")
    repo, err = _get_repo(session_id)
    if err:
        return err

    rc, out, err_out = _run_git(repo, "status", "--short")
    if rc != 0:
        return f"❌ git status 失败: {err_out or out}"

    if not out:
        return "✅ 工作区干净，没有未提交的更改。"

    lines = ["📋 Git 状态:"]
    status_map = {
        "M": "📝 修改", "A": "➕ 新增", "D": "🗑️ 删除",
        "R": "🔄 重命名", "C": "📋 复制", "??": "❓ 未跟踪",
    }
    for line in out.split("\n"):
        if len(line) >= 2:
            st = line[:2].strip()
            f = line[3:]
            icon = status_map.get(st, f"  [{st}]")
            lines.append(f"  {icon}: {f}")
    return "\n".join(lines)


def _exec_git_log(args: dict) -> str:
    session_id = args.get("session_id", "default")
    count = min(int(args.get("count", 10)), 30)
    repo, err = _get_repo(session_id)
    if err:
        return err

    rc, out, err_out = _run_git(
        repo, "log", f"-{count}", "--oneline", "--decorate", "--format=%h | %ad | %s (%an)",
        "--date=format:%Y-%m-%d %H:%M",
    )
    if rc != 0:
        return f"❌ git log 失败: {err_out or out}"

    if not out:
        return "📋 暂无提交记录。"

    lines = [f"📋 最近 {count} 条提交:"]
    for line in out.split("\n"):
        lines.append(f"  {line}")
    return "\n".join(lines)


def _exec_git_diff(args: dict) -> str:
    session_id = args.get("session_id", "default")
    filename = (args.get("file") or "").strip()
    staged = bool(args.get("staged", False))
    repo, err = _get_repo(session_id)
    if err:
        return err

    cmd = ["diff"]
    if staged:
        cmd.append("--staged")
    if filename:
        cmd.append("--")
        cmd.append(filename)

    rc, out, err_out = _run_git(repo, *cmd)
    if rc != 0:
        return f"❌ git diff 失败: {err_out or out}"

    if not out:
        return "✅ 没有差异（工作区与 HEAD 一致）。"

    # 截断过长的 diff
    if len(out) > 3000:
        out = out[:3000] + "\n\n... [diff 截断，原文共 {} 字符]".format(len(out))

    return f"📝 Git Diff:\n```diff\n{out}\n```"


def _exec_git_branch(args: dict) -> str:
    session_id = args.get("session_id", "default")
    repo, err = _get_repo(session_id)
    if err:
        return err

    rc, out, err_out = _run_git(repo, "branch", "--all")
    if rc != 0:
        return f"❌ git branch 失败: {err_out or out}"

    if not out:
        return "📋 暂无分支。"

    lines = ["🌿 Git 分支:"]
    for line in out.split("\n"):
        stripped = line.strip()
        if stripped.startswith("*"):
            lines.append(f"  ⭐ {stripped[1:].strip()} (当前)")
        else:
            lines.append(f"  {stripped}")
    return "\n".join(lines)


# ============================================================
# 注册工具
# ============================================================
_tool_list = [
    (GIT_STATUS_DEF, _exec_git_status),
    (GIT_LOG_DEF, _exec_git_log),
    (GIT_DIFF_DEF, _exec_git_diff),
    (GIT_BRANCH_DEF, _exec_git_branch),
]

for tool_def, executor in _tool_list:
    tool_registry.register(tool_def["name"], tool_def, executor)


# ============================================================
# Flask 路由
# ============================================================
def register_routes(app, http_session=None):
    @app.route("/api/git/test-connection", methods=["POST"])
    def git_test_connection():
        """测试 Git 仓库连接"""
        data = request.get_json(force=True)
        repo_path = (data.get("repo_path") or "").strip()
        session_id = data.get("session_id", "default")

        if not repo_path:
            return jsonify({"success": False, "error": "请填入 Git 仓库路径"}), 400

        conn = _get_conn(session_id)
        conn["repo_path"] = repo_path

        t0 = time.time()

        # 检查 git 是否可用
        try:
            subprocess.run(["git", "--version"], capture_output=True, text=True, timeout=5)
        except FileNotFoundError:
            return jsonify({"success": False, "error": "Git 未安装或不在系统 PATH 中。请安装 Git: https://git-scm.com"})
        except Exception:
            return jsonify({"success": False, "error": "Git 命令异常"})

        p = Path(repo_path).expanduser().resolve()

        if not p.exists():
            conn["connected"] = False
            return jsonify({"success": False, "error": f"路径不存在: {p}"})

        if not (p / ".git").exists():
            conn["connected"] = False
            return jsonify({"success": False, "error": f"不是 Git 仓库（无 .git 目录）: {p}\n提示: 使用 git init 或 git clone 创建仓库。"})

        # 尝试 git status
        rc, out, err_out = _run_git(str(p), "status", "--short")
        latency_ms = round((time.time() - t0) * 1000)

        if rc == 0:
            changed = len([l for l in out.split("\n") if l.strip()]) if out else 0

            # 获取当前分支
            rc2, branch, _ = _run_git(str(p), "branch", "--show-current")
            branch_name = branch.strip() if rc2 == 0 and branch else "?"

            conn["connected"] = True
            conn["last_test"] = time.time()

            return jsonify({
                "success": True,
                "message": f"连接成功！当前分支: {branch_name}，{changed} 个文件有变更",
                "branch": branch_name,
                "changed_files": changed,
                "repo_path": str(p),
                "latency_ms": latency_ms,
            })
        else:
            conn["connected"] = False
            return jsonify({
                "success": False,
                "error": f"Git 命令执行失败: {err_out or out}",
                "latency_ms": latency_ms,
            })

    @app.route("/api/git/config", methods=["GET"])
    def git_get_config():
        """获取当前 Git 服务配置"""
        session_id = request.args.get("session_id", "default")
        conn = _get_conn(session_id)
        return jsonify({
            "repo_path": conn.get("repo_path", ""),
            "connected": conn.get("connected", False),
            "last_test": conn.get("last_test"),
        })
