"""
MCP Clipboard 剪贴板服务模块
提供系统剪贴板读写工具
"""

import time

from flask import jsonify, request

from . import tool_registry

# ============================================================
# 工具定义
# ============================================================
CLIPBOARD_READ_DEF = {
    "name": "clipboard_read",
    "description": (
        "读取系统剪贴板中的文本内容。"
        "当用户要求处理剪贴板内容、粘贴文本、查看复制了什么时使用。"
    ),
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

CLIPBOARD_WRITE_DEF = {
    "name": "clipboard_write",
    "description": (
        "将文本写入系统剪贴板。"
        "当用户要求复制内容、将结果放入剪贴板时使用。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "要写入剪贴板的文本内容",
            },
        },
        "required": ["text"],
    },
}


# ============================================================
# 执行器
# ============================================================
def _get_clipboard():
    """获取剪贴板模块"""
    try:
        import pyperclip
        return pyperclip, None
    except ImportError:
        pass
    # 回退：tkinter
    try:
        import tkinter
        root = tkinter.Tk()
        root.withdraw()
        return root, None
    except Exception:
        pass
    return None, "剪贴板模块未安装。请运行: pip install pyperclip"


def _exec_clipboard_read(args: dict) -> str:
    clip, err = _get_clipboard()
    if err:
        # tkinter 回退
        try:
            import tkinter
            root = tkinter.Tk()
            root.withdraw()
            text = root.clipboard_get()
            root.destroy()
            if text:
                return f"📋 剪贴板内容 ({len(text)} 字符):\n\n{text[:3000]}"
            return "📋 剪贴板为空。"
        except Exception as e:
            return f"❌ 读取剪贴板失败: {str(e)}"

    try:
        import pyperclip
        text = pyperclip.paste()
        if not text:
            return "📋 剪贴板为空。"
        return f"📋 剪贴板内容 ({len(text)} 字符):\n\n{text[:3000]}"
    except Exception as e:
        return f"❌ 读取剪贴板失败: {str(e)}"


def _exec_clipboard_write(args: dict) -> str:
    text = args.get("text", "")
    if not text:
        return "错误: text 不能为空"

    try:
        import pyperclip
        pyperclip.copy(text)
        return f"✅ 已写入剪贴板（{len(text)} 字符）"
    except ImportError:
        pass

    # tkinter 回退
    try:
        import tkinter
        root = tkinter.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        root.destroy()
        return f"✅ 已写入剪贴板（{len(text)} 字符）"
    except Exception as e:
        return f"❌ 写入剪贴板失败: {str(e)}。请安装 pyperclip: pip install pyperclip"


_tool_list = [
    (CLIPBOARD_READ_DEF, _exec_clipboard_read),
    (CLIPBOARD_WRITE_DEF, _exec_clipboard_write),
]

for tool_def, executor in _tool_list:
    tool_registry.register(tool_def["name"], tool_def, executor)


# ============================================================
# Flask 路由
# ============================================================
def register_routes(app, http_session=None):
    @app.route("/api/clipboard/test-connection", methods=["POST"])
    def clipboard_test_connection():
        """测试剪贴板模块可用性"""
        try:
            import pyperclip
            pyperclip.paste()
            return jsonify({"success": True, "message": "剪贴板模块 (pyperclip) 可用", "method": "pyperclip"})
        except ImportError:
            pass
        try:
            import tkinter
            root = tkinter.Tk()
            root.withdraw()
            root.clipboard_get()
            root.destroy()
            return jsonify({"success": True, "message": "剪贴板模块 (tkinter) 可用", "method": "tkinter"})
        except Exception:
            return jsonify({"success": False, "error": "剪贴板不可用。请安装 pyperclip: pip install pyperclip"})
