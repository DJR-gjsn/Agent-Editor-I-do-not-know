"""
File Search Tools 文件搜索与编辑模块 — glob / grep / edit
提供给 LLM 在工作区中搜索文件和编辑文件的能力
"""

import re
import tempfile
import time
from pathlib import Path

from flask import jsonify, request

from . import tool_registry
from .utils import WORKSPACE, format_file_size as _format_size, safe_path as _safe_path


# ============================================================
# 1. glob_search — 文件模式匹配
# ============================================================
GLOB_SEARCH_DEF = {
    "name": "glob_search",
    "description": (
        "在工作区中按 glob 模式搜索匹配的文件。"
        "支持通配符：* 匹配任意字符、** 递归匹配子目录、? 匹配单个字符。"
        "例如: '*.py' 搜索所有 Python 文件，'**/*.json' 递归搜索所有 JSON 文件。"
        "返回文件路径、大小和修改时间。用于在保存文件后查找、列出某类文件等场景。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob 匹配模式，如 '*.txt'、'**/*.py'、'data*.json'",
            },
            "max_results": {
                "type": "integer",
                "description": "最大返回数量，默认 30",
                "default": 30,
            },
        },
        "required": ["pattern"],
    },
}


def _exec_glob_search(args: dict) -> str:
    """执行 glob 文件搜索（跨所有工作区）"""
    pattern = (args.get("pattern") or "").strip()
    max_results = min(int(args.get("max_results", 30)), 100)

    if not pattern:
        return "错误: pattern 不能为空"

    # 安全检查：防止 pattern 试图逃离工作区
    if pattern.startswith("/") or pattern.startswith("\\") or ".." in pattern:
        return "错误: pattern 不能包含绝对路径或上级目录引用"

    # 跨所有工作区搜索
    _ALL_WORKSPACES = [
        WORKSPACE,                                                      # common_tools_workspace
        Path(tempfile.gettempdir()) / "mcp_office_workspace",           # Word/Excel/PPT
        Path(tempfile.gettempdir()) / "mcp_pdf_output",                 # PDF
        Path(tempfile.gettempdir()) / "mcp_qrcodes",                    # 二维码
    ]

    matches = []
    for ws in _ALL_WORKSPACES:
        if not ws.exists():
            continue
        try:
            # 对 office workspace，还需递归搜索子目录（按 session 分目录）
            for p in ws.rglob(pattern):
                if p.is_file() and p not in matches:
                    matches.append(p)
        except Exception:
            continue

    if not matches:
        ws_paths = "\n".join(f"  - {ws}" for ws in _ALL_WORKSPACES if ws.exists())
        return f"未找到匹配 '{pattern}' 的文件。\n已搜索的工作区:\n{ws_paths}\n提示: 使用 file_write 先创建文件，或用 '**/*' 列出所有文件。"

    # 只返回文件，排除目录
    files = [m for m in matches if m.is_file()]
    dirs = [m for m in matches if m.is_dir()]

    lines = [f"🔍 搜索 '{pattern}' 的结果:"]
    lines.append(f"📁 工作区: {WORKSPACE}")
    lines.append(f"📄 文件: {len(files)} 个 | 📂 目录: {len(dirs)} 个")

    if dirs and len(dirs) <= 10:
        lines.append("\n📂 匹配的目录:")
        for d in sorted(dirs)[:10]:
            rel = d.relative_to(WORKSPACE)
            lines.append(f"  - {rel}/")

    if files:
        lines.append(f"\n📄 匹配的文件 (显示前 {min(len(files), max_results)} 个):")
        for f in sorted(files, key=lambda x: x.stat().st_mtime, reverse=True)[:max_results]:
            rel = f.relative_to(WORKSPACE)
            size = f.stat().st_size
            mtime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(f.stat().st_mtime))
            size_str = _format_size(size)
            lines.append(f"  - {rel}  [{size_str}]  {mtime}")

        if len(files) > max_results:
            lines.append(f"  ... 还有 {len(files) - max_results} 个文件未显示")

    return "\n".join(lines)


# ============================================================
# 2. grep_search — 文件内容搜索
# ============================================================
GREP_SEARCH_DEF = {
    "name": "grep_search",
    "description": (
        "在工作区文件中搜索匹配指定模式的内容行。"
        "支持正则表达式（默认）和纯文本匹配。"
        "可以指定搜索路径为单个文件或子目录，不指定则搜索整个工作区。"
        "返回匹配的文件路径、行号和行内容。"
        "适合查找代码片段、配置项、日志关键字等。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "搜索模式，支持正则表达式。例如 'TODO'、'import\\s+os'、'def\\s+\\w+'",
            },
            "path": {
                "type": "string",
                "description": "搜索路径（相对于工作区），可以是文件名或子目录。不指定则搜索整个工作区。例如 'src/' 或 'config.json'",
            },
            "max_results": {
                "type": "integer",
                "description": "最大返回的匹配行数，默认 30",
                "default": 30,
            },
            "case_sensitive": {
                "type": "boolean",
                "description": "是否区分大小写，默认 True",
                "default": True,
            },
            "use_regex": {
                "type": "boolean",
                "description": "是否使用正则表达式，默认 True。设为 False 则进行纯文本匹配",
                "default": True,
            },
        },
        "required": ["pattern"],
    },
}


def _exec_grep_search(args: dict) -> str:
    """执行文件内容搜索"""
    pattern = (args.get("pattern") or "").strip()
    search_path = (args.get("path") or "").strip()
    max_results = min(int(args.get("max_results", 30)), 100)
    case_sensitive = bool(args.get("case_sensitive", True))
    use_regex = bool(args.get("use_regex", True))

    if not pattern:
        return "错误: pattern 不能为空"

    # 确定搜索范围
    if search_path:
        try:
            target = _safe_path(search_path)
            if not target.exists():
                return f"错误: 路径 '{search_path}' 不存在。使用 glob_search 查看工作区文件。"
        except ValueError as e:
            return f"错误: {e}"
    else:
        target = WORKSPACE

    # 收集要搜索的文件（排除二进制和过大文件）
    if target.is_file():
        files = [target]
    else:
        files = []
        for f in target.rglob("*"):
            if f.is_file() and f.stat().st_size < 1_000_000:  # 跳过 > 1MB 的文件
                # 跳过常见的二进制文件
                if f.suffix.lower() in {".pyc", ".pyo", ".pyd", ".so", ".dll", ".exe",
                                         ".zip", ".tar", ".gz", ".7z", ".rar",
                                         ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico",
                                         ".mp3", ".mp4", ".avi", ".mov", ".wav",
                                         ".ttf", ".otf", ".woff", ".woff2",
                                         ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"}:
                    continue
                files.append(f)

    if not files:
        return f"工作区没有可搜索的文本文件。\n路径: {target}"

    # 编译搜索模式
    try:
        flags = 0 if case_sensitive else re.IGNORECASE
        if use_regex:
            compiled = re.compile(pattern, flags)
        else:
            compiled = re.compile(re.escape(pattern), flags)
    except re.error as e:
        return f"错误: 正则表达式无效 - {str(e)}"

    # 搜索
    matches = []
    searched_count = 0

    for f in sorted(files):
        if len(matches) >= max_results:
            break
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
            searched_count += 1
            for i, line in enumerate(content.splitlines(), 1):
                if compiled.search(line):
                    rel = f.relative_to(WORKSPACE)
                    matches.append({
                        "file": str(rel),
                        "line": i,
                        "content": line.strip()[:200],
                    })
                    if len(matches) >= max_results:
                        break
        except Exception:
            continue

    if not matches:
        return (
            f"未找到匹配 '{pattern}' 的内容。\n"
            f"搜索范围: {target.relative_to(WORKSPACE) if target != WORKSPACE else '整个工作区'}\n"
            f"已搜索: {searched_count} 个文件"
        )

    # 按文件分组输出
    by_file = {}
    for m in matches:
        by_file.setdefault(m["file"], []).append(m)

    lines = [f"🔍 搜索 '{pattern}' 的结果 ({len(matches)} 条匹配，{len(by_file)} 个文件):"]
    for filename, file_matches in by_file.items():
        lines.append(f"\n📄 {filename}:")
        for m in file_matches[:10]:  # 每个文件最多显示 10 条
            lines.append(f"  L{m['line']:4d}: {m['content']}")
        if len(file_matches) > 10:
            lines.append(f"  ... 还有 {len(file_matches) - 10} 条匹配")

    if len(matches) >= max_results:
        lines.append(f"\n⚠️ 结果已截断（达到上限 {max_results} 条），请缩小搜索范围。")

    return "\n".join(lines)


# ============================================================
# 3. file_edit — 精确字符串替换
# ============================================================
FILE_EDIT_DEF = {
    "name": "file_edit",
    "description": (
        "对工作区中的文件执行精确的字符串替换。"
        "old_string 必须在文件中精确匹配（包含所有空白字符），且只出现一次。"
        "如果 old_string 出现多次或不出现，编辑会失败并给出提示。"
        "适合对文件进行局部修改，无需重写整个文件。"
        "⚠️ old_string 和 new_string 必须不同。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "工作区中的文件名，如 'config.json'、'src/main.py'",
            },
            "old_string": {
                "type": "string",
                "description": "要替换的原始文本，必须精确匹配（包括空白和缩进）",
            },
            "new_string": {
                "type": "string",
                "description": "替换后的新文本",
            },
        },
        "required": ["filename", "old_string", "new_string"],
    },
}


def _exec_file_edit(args: dict) -> str:
    """执行文件精确编辑"""
    filename = (args.get("filename") or "").strip()
    old_string = args.get("old_string", "")
    new_string = args.get("new_string", "")

    if not filename:
        return "错误: filename 不能为空"
    if old_string == new_string:
        return "错误: old_string 和 new_string 必须不同"

    try:
        filepath = _safe_path(filename)
    except ValueError as e:
        return f"错误: {e}"

    if not filepath.exists():
        # 列出工作区文件帮助用户
        files = list(WORKSPACE.rglob("*"))
        text_files = [f for f in files if f.is_file() and f.suffix not in
                      {".pyc", ".pyo", ".png", ".jpg", ".gif", ".zip", ".tar", ".gz"}]
        files_str = "\n".join(
            f"  - {f.relative_to(WORKSPACE)} ({_format_size(f.stat().st_size)})"
            for f in sorted(text_files)[:15]
        )
        return (
            f"错误: 文件 '{filename}' 不存在。\n"
            f"当前工作区文本文件:\n{files_str}"
        ) if files_str else f"错误: 文件 '{filename}' 不存在，工作区为空。"

    try:
        content = filepath.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"错误: '{filename}' 不是 UTF-8 文本文件，无法编辑"
    except Exception as e:
        return f"错误: 读取文件失败 - {str(e)}"

    # 统计 old_string 出现次数
    count = content.count(old_string)

    if count == 0:
        # 尝试给出有用的提示
        hint = ""
        # 检查是否有相似的字符串（忽略首尾空白差异）
        stripped_old = old_string.strip()
        if stripped_old and stripped_old in content:
            hint = "\n💡 提示: 去掉首尾空白后找到了匹配，请检查 old_string 的缩进和换行是否精确。"
        elif stripped_old:
            # 搜索部分匹配
            first_line = stripped_old.split("\n")[0][:40]
            if first_line and first_line in content:
                hint = f"\n💡 提示: 找到了以 '{first_line}...' 开头的内容，但后续不完全匹配。请检查 old_string 是否精确。"
        return (
            f"❌ 编辑失败: old_string 在文件中未找到（出现 0 次）。\n"
            f"文件: {filename} ({len(content)} 字符, {len(content.splitlines())} 行)\n"
            f"请确保 old_string 与文件中的内容完全一致（包括空白和缩进）。{hint}"
        )

    if count > 1:
        return (
            f"❌ 编辑失败: old_string 在文件中出现了 {count} 次（需要唯一匹配）。\n"
            f"文件: {filename}\n"
            f"请提供更长的 old_string 使其在文件中唯一，或使用 file_read 查看文件后用 file_write 整体重写。"
        )

    # 执行替换
    new_content = content.replace(old_string, new_string)

    try:
        filepath.write_text(new_content, encoding="utf-8")
    except Exception as e:
        return f"错误: 写入文件失败 - {str(e)}"

    # 计算变更统计
    old_len = len(old_string)
    new_len = len(new_string)
    diff = new_len - old_len
    diff_str = f"+{diff}" if diff > 0 else str(diff)

    return (
        f"✅ 编辑成功: {filename}\n"
        f"📝 替换了 1 处（old_string 出现 {count} 次中的 1 次）\n"
        f"📏 字符变化: {old_len} → {new_len} ({diff_str})"
    )


# ============================================================
# 注册工具到 registry
# ============================================================
_tool_list = [
    (GLOB_SEARCH_DEF, _exec_glob_search),
    (GREP_SEARCH_DEF, _exec_grep_search),
    (FILE_EDIT_DEF, _exec_file_edit),
]

for tool_def, executor in _tool_list:
    tool_registry.register(tool_def["name"], tool_def, executor)


# ============================================================
# Flask 路由（供前端面板使用）
# ============================================================
def register_routes(app):
    @app.route("/api/file-search/glob", methods=["POST"])
    def glob_search():
        """手动触发 glob 搜索"""
        data = request.get_json(force=True)
        pattern = (data.get("pattern") or "").strip()
        max_results = min(int(data.get("max_results", 30)), 100)

        if not pattern:
            return jsonify({"error": "pattern 不能为空"}), 400
        if ".." in pattern or pattern.startswith("/") or pattern.startswith("\\"):
            return jsonify({"error": "pattern 不能包含绝对路径或上级目录引用"}), 400

        t0 = time.time()
        try:
            result = _exec_glob_search({"pattern": pattern, "max_results": max_results})
            latency_ms = round((time.time() - t0) * 1000)
            return jsonify({"success": True, "result": result, "latency_ms": latency_ms})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 400

    @app.route("/api/file-search/grep", methods=["POST"])
    def grep_search():
        """手动触发内容搜索"""
        data = request.get_json(force=True)
        pattern = (data.get("pattern") or "").strip()
        search_path = (data.get("path") or "").strip()
        max_results = min(int(data.get("max_results", 30)), 100)
        case_sensitive = bool(data.get("case_sensitive", True))
        use_regex = bool(data.get("use_regex", True))

        if not pattern:
            return jsonify({"error": "pattern 不能为空"}), 400

        t0 = time.time()
        try:
            result = _exec_grep_search({
                "pattern": pattern,
                "path": search_path,
                "max_results": max_results,
                "case_sensitive": case_sensitive,
                "use_regex": use_regex,
            })
            latency_ms = round((time.time() - t0) * 1000)
            return jsonify({"success": True, "result": result, "latency_ms": latency_ms})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 400

    @app.route("/api/file-search/edit", methods=["POST"])
    def file_edit():
        """手动触发文件编辑"""
        data = request.get_json(force=True)
        filename = (data.get("filename") or "").strip()
        old_string = data.get("old_string", "")
        new_string = data.get("new_string", "")

        if not filename:
            return jsonify({"error": "filename 不能为空"}), 400
        if old_string == new_string:
            return jsonify({"error": "old_string 和 new_string 必须不同"}), 400

        t0 = time.time()
        try:
            result = _exec_file_edit({
                "filename": filename,
                "old_string": old_string,
                "new_string": new_string,
            })
            latency_ms = round((time.time() - t0) * 1000)
            success = result.startswith("✅")
            return jsonify({"success": success, "result": result, "latency_ms": latency_ms})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 400

    @app.route("/api/file-search/workspace")
    def file_search_workspace_info():
        """获取工作区信息"""
        all_files = []
        for f in WORKSPACE.rglob("*"):
            if f.is_file():
                all_files.append({
                    "path": str(f.relative_to(WORKSPACE)),
                    "size": f.stat().st_size,
                    "size_display": _format_size(f.stat().st_size),
                    "modified": time.strftime(
                        "%Y-%m-%d %H:%M:%S",
                        time.localtime(f.stat().st_mtime),
                    ),
                })

        return jsonify({
            "workspace": str(WORKSPACE),
            "file_count": len(all_files),
            "files": sorted(all_files, key=lambda x: x["path"]),
        })
