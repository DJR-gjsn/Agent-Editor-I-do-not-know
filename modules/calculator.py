"""
Calculator 安全计算器模块
支持数学表达式求值，注册为 AI 可调用的工具
"""

import ast
import math
import operator
import time
from flask import jsonify, request

from . import tool_registry

# ============================================================
# 安全求值引擎
# ============================================================
SAFE_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub,
    ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
    ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos,
}

SAFE_FUNCS = {
    "abs": abs, "round": round, "min": min, "max": max, "sum": sum,
    "int": int, "float": float,
    "sqrt": math.sqrt, "log": math.log, "log10": math.log10, "log2": math.log2,
    "exp": math.exp,
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan,
    "degrees": math.degrees, "radians": math.radians,
    "ceil": math.ceil, "floor": math.floor,
    "factorial": math.factorial, "gcd": math.gcd,
    "pi": math.pi, "e": math.e, "tau": math.tau,
}


def _safe_eval(node):
    if isinstance(node, ast.Constant):
        return node.value
    elif isinstance(node, ast.UnaryOp):
        op = SAFE_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"不支持的操作符: {type(node.op).__name__}")
        return op(_safe_eval(node.operand))
    elif isinstance(node, ast.BinOp):
        op = SAFE_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"不支持的操作符: {type(node.op).__name__}")
        return op(_safe_eval(node.left), _safe_eval(node.right))
    elif isinstance(node, ast.Call):
        func_name = node.func.id if isinstance(node.func, ast.Name) else None
        if func_name not in SAFE_FUNCS:
            raise ValueError(f"不允许的函数: {func_name}")
        args = [_safe_eval(arg) for arg in node.args]
        return SAFE_FUNCS[func_name](*args)
    elif isinstance(node, ast.Name):
        if node.id in SAFE_FUNCS:
            return SAFE_FUNCS[node.id]
        raise ValueError(f"未知变量: {node.id}")
    else:
        raise ValueError(f"不支持的表达式类型: {type(node).__name__}")


def calculate(expression: str):
    tree = ast.parse(expression.strip(), mode="eval")
    return _safe_eval(tree.body)


# ============================================================
# 工具定义
# ============================================================
CALCULATOR_DEFINITION = {
    "name": "calculator",
    "description": "执行数学计算。支持基本运算(+ - * / ** %)和函数(sqrt log sin cos tan abs round ceil floor pi e等)。当需要进行数学计算时使用此工具。",
    "parameters": {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "数学表达式，例如 'sqrt(16) + 2**10' 或 'sin(pi/2) * 100'",
            },
        },
        "required": ["expression"],
    },
}


def execute_calculator(args: dict) -> str:
    """AI 调用的计算执行器"""
    expression = args.get("expression", "")
    if not expression:
        return "错误: 表达式不能为空"
    try:
        result = calculate(expression)
        return f"{expression} = {result}"
    except SyntaxError:
        return f"错误: 表达式 '{expression}' 语法不正确"
    except (ValueError, ZeroDivisionError) as e:
        return f"计算错误: {str(e)}"


tool_registry.register("calculator", CALCULATOR_DEFINITION, execute_calculator)


# ============================================================
# Flask 路由
# ============================================================
def register_routes(app):
    @app.route("/api/calculator", methods=["POST"])
    def calculator_eval():
        data = request.get_json(force=True)
        expression = (data.get("expression") or "").strip()
        if not expression:
            return jsonify({"error": "expression 不能为空"}), 400
        if len(expression) > 500:
            return jsonify({"error": "表达式过长（最多 500 字符）"}), 400

        t0 = time.time()
        try:
            result = calculate(expression)
            latency_ms = round((time.time() - t0) * 1000)
            return jsonify({
                "success": True, "expression": expression,
                "result": result, "type": type(result).__name__,
                "latency_ms": latency_ms,
            })
        except (SyntaxError, ValueError, ZeroDivisionError) as e:
            return jsonify({"success": False, "error": str(e)}), 400
        except Exception as e:
            return jsonify({"success": False, "error": f"计算失败: {str(e)}"}), 400
