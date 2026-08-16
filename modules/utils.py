"""
工具函数模块 — 跨模块复用的通用功能

提供:
- make_sse_response(): Flask SSE 流式响应工厂（消除 5 处重复）
- clean_json_response(): LLM JSON 响应清理（消除 plan/agent 中的重复）
- setup_logging(): 全局日志配置（替换裸 print()）
- safe_path(): 工作区路径安全检查（消除 common_tools/file_search_tools 中的重复）
- format_file_size(): 文件大小格式化（消除 file_search_tools/mcp_system 中的重复）
- SSE_HEADERS: 常量
"""

import io
import json
import logging
import re
import sys
import tempfile
import time
from pathlib import Path

from flask import Response, stream_with_context

# ============================================================
# 工作区工具（消除 common_tools.py 和 file_search_tools.py 中的重复）
# ============================================================

WORKSPACE = Path(tempfile.gettempdir()) / "common_tools_workspace"
WORKSPACE.mkdir(parents=True, exist_ok=True)


def safe_path(filename: str, workspace: Path = None) -> Path:
    """将文件名解析到 workspace 内，防止目录穿越攻击。"""
    ws = workspace or WORKSPACE
    p = (ws / filename).resolve()
    if not str(p).startswith(str(ws.resolve())):
        raise ValueError(f"不允许访问工作区以外的路径: {filename}")
    return p


def format_file_size(size: int) -> str:
    """格式化文件大小（B/KB/MB/GB）。"""
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.0f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"

# ============================================================
# SSE 响应
# ============================================================

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


def make_sse_response(generator):
    """
    创建 Flask SSE (Server-Sent Events) 流式响应。
    替代在各模块中重复的 Response(stream_with_context(generate()), ...) 样板代码。

    用法:
        def my_events():
            yield "data: {...}\\n\\n"
            yield "data: [DONE]\\n\\n"

        return make_sse_response(my_events())
    """
    return Response(
        stream_with_context(generator),
        mimetype="text/event-stream",
        headers=SSE_HEADERS,
    )


def sse_event(data: dict) -> str:
    """将 dict 编码为一条 SSE 事件字符串"""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def sse_error(message: str) -> str:
    """构建 SSE 错误事件"""
    return sse_event({"error": message})


def sse_done() -> str:
    """SSE 流结束信号"""
    return "data: [DONE]\n\n"


# ============================================================
# JSON 响应清理
# ============================================================

def clean_json_response(content: str) -> str:
    """
    清理 LLM 返回的 JSON 内容。
    去除 markdown 代码块标记（```json ... ```）和前后空白。

    替代 plan.py 和 agent.py 中的手写版本（包括那个不健壮的贪婪 regex）。
    """
    text = content.strip()
    # 去除开头的 markdown 代码块标记（```json 或 ```）
    while text.startswith("```"):
        # 去掉第一行
        idx = text.find("\n")
        if idx == -1:
            text = text[3:]  # 只有 ```，去掉它
            break
        text = text[idx + 1:]
        if text.startswith("```"):
            continue  # 连续多个 ```

    # 去除结尾的 ```
    while text.rstrip().endswith("```"):
        text = text.rstrip()[:-3].rstrip()

    # 确保以 { 或 [ 开头（有时 LLM 会在 JSON 前后加说明文字）
    brace_idx = text.find("{")
    bracket_idx = text.find("[")
    start_indices = [i for i in (brace_idx, bracket_idx) if i != -1]
    if start_indices:
        text = text[min(start_indices):]

    # 从末尾找最后一个 } 或 ]
    brace_end = text.rfind("}")
    bracket_end = text.rfind("]")
    end_indices = [i for i in (brace_end, bracket_end) if i != -1]
    if end_indices:
        text = text[:max(end_indices) + 1]

    return text.strip()


# ============================================================
# 日志系统
# ============================================================

_logger_configured = False


def setup_logging(name: str = "wybzd", level: int = logging.INFO):
    """
    配置全局日志系统。首次调用后生效，重复调用无副作用。

    - INFO 及以上输出到 stdout（带时间戳和级别）
    - DEBUG 输出到 stderr
    """
    global _logger_configured
    if _logger_configured:
        return

    fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-5s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Windows 下 stdout 默认 GBK 编码，无法输出 emoji
    # 包装为 UTF-8 避免 UnicodeEncodeError
    try:
        utf8_stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        utf8_stdout = sys.stdout

    handler = logging.StreamHandler(utf8_stdout)
    handler.setFormatter(fmt)
    handler.setLevel(level)

    root = logging.getLogger(name)
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)
    root.propagate = False

    _logger_configured = True


def get_logger(name: str = "wybzd") -> logging.Logger:
    """获取 logger 实例"""
    return logging.getLogger(name)


def with_heartbeat(events, idle_seconds: float = 15.0):
    """
    包装事件生成器：事件流空闲超过 idle_seconds 时产出 ("heartbeat", None)，
    其余情况原样产出 ("event", event)。用于 SSE 长连接保活。
    内部用 daemon 泵线程 + 队列实现空闲检测；生成器被关闭（GeneratorExit）
    时会通知泵线程退出，避免线程泄漏。
    """
    import queue
    import threading

    q = queue.Queue(maxsize=16)
    stop = threading.Event()

    def _pump():
        try:
            for ev in events:
                while not stop.is_set():
                    try:
                        q.put(("event", ev), timeout=0.2)
                        break
                    except queue.Full:
                        continue
                else:
                    return
            q.put(("done", None))
        except Exception as exc:
            try:
                q.put(("error", exc))
            except Exception:
                pass

    t = threading.Thread(target=_pump, daemon=True)
    t.start()
    try:
        while True:
            try:
                kind, payload = q.get(timeout=idle_seconds)
            except queue.Empty:
                yield ("heartbeat", None)
                continue
            if kind == "done":
                return
            if kind == "error":
                raise payload
            yield (kind, payload)
    except GeneratorExit:
        stop.set()
        raise
