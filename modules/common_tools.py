"""
常用工具模块 — get_current_time / url_fetch / file_read / file_write / json_query
提供给 LLM 日常高频使用的实用工具
"""

import json
import os
import re
import tempfile
import time
from pathlib import Path

import requests as _requests
from flask import jsonify, request

from . import tool_registry
from .utils import WORKSPACE, safe_path as _safe_path


# ============================================================
# 工具定义
# ============================================================
GET_TIME_DEF = {
    "name": "get_current_time",
    "description": (
        "获取当前日期和时间。"
        "返回日期、时间、星期、Unix 时间戳、时区信息。"
        "当用户询问当前时间、今天日期、星期几时使用。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "timezone": {
                "type": "string",
                "description": "时区，如 'Asia/Shanghai'、'America/New_York'、'UTC'，默认 Asia/Shanghai",
            },
        },
        "required": [],
    },
}

URL_FETCH_DEF = {
    "name": "url_fetch",
    "description": (
        "获取指定 URL 的网页内容，提取纯文本。"
        "与 web_search 互补：web_search 用来找链接，url_fetch 用来读具体内容。"
        "适合阅读新闻全文、查看文档页面、获取 API 的 JSON 响应。"
        "限制：最大 500KB，超时 15 秒。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "要抓取的网页 URL",
            },
            "max_length": {
                "type": "integer",
                "description": "返回文本的最大字符数，默认 5000",
                "default": 5000,
            },
        },
        "required": ["url"],
    },
}

FILE_READ_DEF = {
    "name": "file_read",
    "description": (
        "读取工作区中的文本文件。"
        "可以读取全部内容或指定行范围。"
        "用于查看之前保存的文件内容。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "文件名，如 'notes.txt'",
            },
            "start_line": {
                "type": "integer",
                "description": "起始行号（从 1 开始），不指定则从头开始",
            },
            "end_line": {
                "type": "integer",
                "description": "结束行号（包含），不指定则到末尾",
            },
        },
        "required": ["filename"],
    },
}

FILE_WRITE_DEF = {
    "name": "file_write",
    "description": (
        "将文本内容写入工作区文件。会覆盖已有文件。"
        "适合保存对话结果、记录笔记、导出数据。"
        "⚠️ 仅在用户明确要求保存到文件时使用，不要在普通对话中自动创建文件。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "文件名，如 'result.txt'、'data.json'",
            },
            "content": {
                "type": "string",
                "description": "要写入的文本内容",
            },
        },
        "required": ["filename", "content"],
    },
}

JSON_QUERY_DEF = {
    "name": "json_query",
    "description": (
        "对 JSON 数据执行路径查询，提取指定字段。"
        "路径语法: $.key.subkey 访问属性, $[0] 访问数组元素。"
        "例如: $.data.items[0].name 提取第一个元素的 name 字段。"
        "适合解析 JSON 格式的 API 响应、配置文件等。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "json_str": {
                "type": "string",
                "description": "JSON 字符串",
            },
            "path": {
                "type": "string",
                "description": "查询路径，如 $.name、$.data[0].title",
            },
        },
        "required": ["json_str", "path"],
    },
}


# ============================================================
# 执行器
# ============================================================

def _exec_get_time(args: dict) -> str:
    """获取当前时间"""
    tz_name = args.get("timezone", "Asia/Shanghai")
    now = time.time()
    local = time.localtime(now)

    # 简单时区偏移（不使用 zoneinfo 以兼容旧版 Python）
    tz_offsets = {
        "UTC": 0,
        "Asia/Shanghai": 8,
        "Asia/Tokyo": 9,
        "Asia/Seoul": 9,
        "Asia/Singapore": 8,
        "Asia/Kolkata": 5.5,
        "Asia/Dubai": 4,
        "Europe/London": 1,
        "Europe/Paris": 2,
        "Europe/Berlin": 2,
        "Europe/Moscow": 3,
        "America/New_York": -4,
        "America/Chicago": -5,
        "America/Denver": -6,
        "America/Los_Angeles": -7,
        "Australia/Sydney": 10,
        "Pacific/Auckland": 12,
    }
    offset = tz_offsets.get(tz_name, 8)

    # 应用偏移
    utc_hour = local.tm_hour - 8  # CST = UTC+8
    target_hour = (utc_hour + int(offset)) % 24

    weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    wd = weekdays[local.tm_wday]

    return (
        f"📅 日期: {local.tm_year}年{local.tm_mon}月{local.tm_mday}日 {wd}\n"
        f"⏰ 时间: {local.tm_hour:02d}:{local.tm_min:02d}:{local.tm_sec:02d}\n"
        f"🕐 时区: {tz_name} (UTC{offset:+d}:00)\n"
        f"🔢 Unix 时间戳: {int(now)}\n"
        f"📆 年第 {local.tm_yday} 天 / 第 {local.tm_mon} 月"
    )


def _exec_url_fetch(args: dict) -> str:
    """抓取网页内容"""
    url = (args.get("url") or "").strip()
    max_length = min(int(args.get("max_length", 5000)), 20000)

    if not url:
        return "错误: URL 不能为空"

    # 安全检查：禁止内网地址
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    hostname = url.split("/")[2] if "//" in url else ""
    forbidden = ["127.0.0.1", "localhost", "0.0.0.0", "10.", "172.16.", "192.168."]
    for fb in forbidden:
        if hostname.startswith(fb):
            return f"错误: 不允许访问内网地址 ({hostname})"

    try:
        resp = _requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; CommonTools/1.0)",
                "Accept": "text/html,application/json,text/plain,*/*",
            },
            timeout=15,
            allow_redirects=True,
        )
        resp.encoding = resp.apparent_encoding or "utf-8"
        content_type = resp.headers.get("Content-Type", "")

        # JSON 响应
        if "application/json" in content_type:
            text = resp.text[:500000]
        # HTML 响应 → 提取纯文本
        elif "text/html" in content_type or resp.text.strip().startswith("<"):
            text = _extract_text_from_html(resp.text)
        else:
            text = resp.text

        text = text[:500000]

        if len(text) > max_length:
            text = text[:max_length] + f"\n\n... [截断，原文共 {len(text)} 字符]"

        status = f"HTTP {resp.status_code}"
        if resp.status_code != 200:
            status += " (非成功状态)"

        return f"📄 {url}\n{status} | 类型: {content_type or '未知'}\n\n{text or '(无文本内容)'}"

    except _requests.exceptions.Timeout:
        return f"错误: 请求超时 ({url})"
    except _requests.exceptions.ConnectionError:
        return f"错误: 无法连接到 {url}"
    except Exception as e:
        return f"错误: {str(e)}"


def _extract_text_from_html(html: str) -> str:
    """从 HTML 中提取纯文本"""
    # 去掉 script 和 style
    text = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)
    # 去掉 HTML 标签
    text = re.sub(r'<[^>]+>', '\n', text)
    # 解码常见实体
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    text = re.sub(r'&#?\w+;', '', text)
    # 合并空白行
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _exec_file_read(args: dict) -> str:
    """读取工作区文件"""
    filename = (args.get("filename") or "").strip()
    start_line = int(args.get("start_line", 0))
    end_line = int(args.get("end_line", 0))

    if not filename:
        return "错误: 文件名不能为空"

    try:
        filepath = _safe_path(filename)
    except ValueError as e:
        return f"错误: {e}"

    if not filepath.exists():
        # 列出工作区文件帮助用户
        files = list(WORKSPACE.glob("*"))
        files_str = "\n".join(f"  - {f.name} ({f.stat().st_size} bytes)" for f in files[:20])
        return f"错误: 文件 '{filename}' 不存在。\n当前工作区文件:\n{files_str}" if files_str else f"错误: 文件 '{filename}' 不存在，工作区为空。"

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()

        total_lines = len(lines)
        if start_line > 0:
            lines = lines[start_line - 1:]
        if end_line > 0:
            lines = lines[:end_line - (start_line - 1 if start_line > 0 else 0)]

        content = "".join(lines)
        if len(content) > 10000:
            content = content[:10000] + f"\n\n... [截断，文件共 {total_lines} 行]"

        return f"📄 {filename} (共 {total_lines} 行):\n\n{content}"
    except UnicodeDecodeError:
        return f"错误: '{filename}' 不是 UTF-8 文本文件"


def _exec_file_write(args: dict) -> str:
    """写入工作区文件"""
    filename = (args.get("filename") or "").strip()
    content = args.get("content", "")

    if not filename:
        return "错误: 文件名不能为空"
    if not content:
        return "错误: 内容不能为空"

    try:
        filepath = _safe_path(filename)
    except ValueError as e:
        return f"错误: {e}"

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        size = filepath.stat().st_size
        return f"✅ 已保存到 {filepath}\n📏 {size} 字节 / {len(content)} 字符"
    except Exception as e:
        return f"错误: 写入失败 - {str(e)}"


def _exec_json_query(args: dict) -> str:
    """JSON 路径查询"""
    json_str = (args.get("json_str") or "").strip()
    path = (args.get("path") or "").strip()

    if not json_str:
        return "错误: JSON 字符串不能为空"
    if not path:
        return "错误: 查询路径不能为空"

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        return f"错误: JSON 格式不正确 - {str(e)}"

    try:
        result = _json_path_get(data, path)
        if isinstance(result, (dict, list)):
            return json.dumps(result, ensure_ascii=False, indent=2)
        return str(result)
    except (KeyError, IndexError, TypeError, ValueError) as e:
        return f"查询失败: {str(e)} - 路径 '{path}' 在数据中不存在"


def _json_path_get(data, path: str):
    """简易 JSON 路径查询，支持 $.key.subkey 和 [index]"""
    # 去掉开头的 $
    if path.startswith("$."):
        path = path[2:]
    elif path.startswith("$"):
        path = path[1:]

    current = data
    # 解析路径: key.subkey[0].field
    tokens = re.findall(r'\.?([^\[\].]+)|\[(\d+)\]', path)
    for name, idx in tokens:
        if name:
            current = current[name]
        elif idx:
            current = current[int(idx)]
    return current


# ============================================================
# 注册工具
# ============================================================
_tool_list = [
    (GET_TIME_DEF, _exec_get_time),
    (URL_FETCH_DEF, _exec_url_fetch),
    (FILE_READ_DEF, _exec_file_read),
    (FILE_WRITE_DEF, _exec_file_write),
    (JSON_QUERY_DEF, _exec_json_query),
]

for tool_def, executor in _tool_list:
    tool_registry.register(tool_def["name"], tool_def, executor)


# ============================================================
# Flask 路由
# ============================================================
def register_routes(app, http_session=None):
    @app.route("/api/common-tools/files")
    def list_workspace_files():
        """列出工作区文件"""
        files = []
        for f in WORKSPACE.iterdir():
            if f.is_file():
                files.append({
                    "name": f.name,
                    "size": f.stat().st_size,
                    "modified": time.strftime(
                        "%Y-%m-%d %H:%M:%S",
                        time.localtime(f.stat().st_mtime),
                    ),
                })
        return jsonify({"files": files, "workspace": str(WORKSPACE)})

    @app.route("/api/common-tools/time")
    def get_time():
        """直接获取当前时间（非 tool call 路径）"""
        tz = request.args.get("tz", "Asia/Shanghai")
        result = _exec_get_time({"timezone": tz})
        return jsonify({"success": True, "result": result})
