"""
Code Executor 代码执行器模块
在沙箱子进程中安全执行 Python 代码，注册为 AI 可调用的工具
"""

import subprocess
import time
from flask import jsonify, request

from . import tool_registry

# ============================================================
# 沙箱包装器
# ============================================================
SANDBOX_WRAPPER = """
import sys, builtins, math, json, re, datetime, collections, itertools, functools, statistics

# 先保存原始 __import__，再覆盖为安全版本
_orig_import = builtins.__import__

def _safe_import(name, *args, **kwargs):
    blocked = ['os', 'subprocess', 'shutil', 'socket', 'ctypes',
               'multiprocessing', 'signal', 'threading',
               'tkinter', 'pygame', 'requests', 'urllib']
    if name in blocked:
        raise ImportError(f"Module '{name}' 在此环境中被禁用")
    if name in ('sys', 'builtins'):
        return sys.modules.get(name)
    return _orig_import(name, *args, **kwargs)
builtins.__import__ = _safe_import

_dangerous = ['open', 'exec', 'eval', 'compile', 'input',
              'breakpoint', 'memoryview', 'globals', 'locals', 'vars']
for _d in _dangerous:
    if hasattr(builtins, _d):
        delattr(builtins, _d)

sys.modules['os'] = None
sys.modules['posix'] = None

{user_code}
"""


def _run_code(code: str, timeout: int = 5) -> dict:
    """执行代码并返回结果"""
    wrapped = SANDBOX_WRAPPER.replace("{user_code}", code)
    proc = subprocess.run(
        ["python", "-c", wrapped],
        capture_output=True, text=True, timeout=timeout,
    )
    return {
        "ok": proc.returncode == 0,
        "stdout": proc.stdout[:3000],
        "stderr": proc.stderr[:3000],
        "exit_code": proc.returncode,
    }


# ============================================================
# 工具定义
# ============================================================
CODE_EXECUTOR_DEFINITION = {
    "name": "code_executor",
    "description": "在安全的沙箱环境中执行 Python 代码。可以进行数据处理、数学计算、文本分析等。支持 math、json、re、datetime、statistics 等模块。当需要进行编程计算或数据处理时使用此工具。",
    "parameters": {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "要执行的 Python 代码。可以使用 math、json、re、datetime、statistics 等模块。print() 输出会被返回。",
            },
        },
        "required": ["code"],
    },
}


def execute_code_executor(args: dict) -> str:
    """AI 调用的代码执行器"""
    code = args.get("code", "")
    if not code:
        return "错误: 代码不能为空"
    if len(code) > 5000:
        return "错误: 代码过长（最多 5000 字符）"

    result = _run_code(code, timeout=10)
    if result["ok"]:
        output = result["stdout"].strip() or "(代码执行成功，无输出)"
        return f"执行成功:\n{output}"
    else:
        return f"执行失败:\n{result['stderr'].strip() or result['stdout'].strip()}"


tool_registry.register("code_executor", CODE_EXECUTOR_DEFINITION, execute_code_executor)


# ============================================================
# Flask 路由
# ============================================================
def register_routes(app):
    @app.route("/api/code-executor", methods=["POST"])
    def code_execute():
        data = request.get_json(force=True)
        code = (data.get("code") or "").strip()
        timeout = min(int(data.get("timeout", 5)), 30)

        if not code:
            return jsonify({"error": "code 不能为空"}), 400
        if len(code) > 10000:
            return jsonify({"error": "代码过长（最多 10000 字符）"}), 400

        t0 = time.time()
        try:
            result = _run_code(code, timeout)
            latency_ms = round((time.time() - t0) * 1000)
            return jsonify({
                "success": result["ok"],
                "stdout": result["stdout"],
                "stderr": result["stderr"],
                "exit_code": result["exit_code"],
                "was_timeout": False,
                "latency_ms": latency_ms,
            })
        except subprocess.TimeoutExpired:
            latency_ms = round((time.time() - t0) * 1000)
            return jsonify({
                "success": False, "stdout": "",
                "stderr": f"执行超时（{timeout} 秒）",
                "exit_code": -1, "was_timeout": True,
                "latency_ms": latency_ms,
            })
        except Exception as e:
            latency_ms = round((time.time() - t0) * 1000)
            return jsonify({"success": False, "error": str(e), "latency_ms": latency_ms})
