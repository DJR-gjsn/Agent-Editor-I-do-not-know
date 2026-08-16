"""
工具注册中心
管理所有 Function Calling 工具定义和对应的执行器
供 /api/chat 中的 tool call loop 使用
"""

import threading

import concurrent.futures

from .utils import set_request_api_config

_executor = concurrent.futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix="tool")

# 活跃任务计数：卡死工具占满 worker 时，新调用可快速失败而非排队等完整超时
_MAX_WORKERS = 8
_active_lock = threading.Lock()
_active_tasks = 0


def _track_start():
    global _active_tasks
    with _active_lock:
        _active_tasks += 1


def _track_end():
    global _active_tasks
    with _active_lock:
        _active_tasks -= 1


def _pool_saturated() -> bool:
    with _active_lock:
        return _active_tasks >= _MAX_WORKERS


def _tracked_run(fn, args, cfg):
    """在池线程内运行工具并跟踪活跃计数（配合 finally 保证计数不泄漏）"""
    _track_start()
    try:
        return _run_with_config(fn, args, cfg)
    finally:
        _track_end()

_lock = threading.Lock()
_tools = {}  # name -> {definition, executor}


def register(name: str, definition: dict, executor: callable):
    """
    注册一个工具
    - name: 工具名称（唯一标识）
    - definition: OpenAI Function Calling 的 function 定义（不含 type: function 外层）
    - executor: 函数，接收参数 dict，返回结果字符串
    """
    with _lock:
        _tools[name] = {
            "definition": definition,
            "executor": executor,
        }


def unregister(name: str):
    with _lock:
        _tools.pop(name, None)


def get_all_definitions() -> list:
    """返回所有已注册工具的 OpenAI tools 数组格式"""
    with _lock:
        return [
            {"type": "function", "function": t["definition"]}
            for t in _tools.values()
        ]


def get_definitions_by_names(names: list) -> list:
    """按名称筛选返回工具定义"""
    with _lock:
        return [
            {"type": "function", "function": _tools[n]["definition"]}
            for n in names if n in _tools
        ]


def _run_with_config(fn, args, cfg):
    """在工具执行线程内设置请求级配置，执行完毕后清理，避免跨请求泄漏"""
    set_request_api_config(cfg)
    try:
        return fn(args)
    finally:
        set_request_api_config({})


def execute(name: str, args: dict, timeout: float = None, request_config: dict = None) -> str:
    """执行指定工具，返回结果字符串。timeout 不为 None 时限制执行时长，超时返回提示。"""
    with _lock:
        tool = _tools.get(name)
    if not tool:
        return f"错误: 未知工具 '{name}'"
    try:
        if timeout is None:
            return str(_run_with_config(tool["executor"], args, request_config))
        if _pool_saturated():
            return (
                f"工具执行超时（线程池繁忙：{_active_tasks} 个工具仍在运行），"
                f"请稍后重试或简化请求"
            )
        future = _executor.submit(_tracked_run, tool["executor"], args, request_config)
        try:
            return str(future.result(timeout=timeout))
        except concurrent.futures.TimeoutError:
            return f"工具执行超时（超过 {timeout} 秒），请简化请求或稍后重试"
    except Exception as e:
        return f"工具执行错误: {str(e)}"
