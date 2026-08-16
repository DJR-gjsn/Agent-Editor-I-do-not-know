"""
工具注册中心
管理所有 Function Calling 工具定义和对应的执行器
供 /api/chat 中的 tool call loop 使用
"""

import threading

import concurrent.futures

_executor = concurrent.futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix="tool")

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


def execute(name: str, args: dict, timeout: float = None) -> str:
    """执行指定工具，返回结果字符串。timeout 不为 None 时限制执行时长，超时返回提示。"""
    with _lock:
        tool = _tools.get(name)
    if not tool:
        return f"错误: 未知工具 '{name}'"
    try:
        if timeout is None:
            return str(tool["executor"](args))
        future = _executor.submit(tool["executor"], args)
        try:
            return str(future.result(timeout=timeout))
        except concurrent.futures.TimeoutError:
            return f"工具执行超时（超过 {timeout} 秒），请简化请求或稍后重试"
    except Exception as e:
        return f"工具执行错误: {str(e)}"
