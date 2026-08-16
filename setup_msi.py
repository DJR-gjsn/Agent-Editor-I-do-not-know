"""
cx_Freeze 打包配置 — 生成 wybzd MSI 安装包
"""
import sys
import os
from cx_Freeze import setup, Executable

# 设置 DPI 感知
import ctypes
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except:
    pass

# 收集数据文件
base_dir = os.path.dirname(os.path.abspath(__file__))
build_options = {
    "packages": [
        "flask", "requests", "tiktoken", "jinja2", "markupsafe",
        "itsdangerous", "werkzeug", "blinker", "http", "json",
    ],
    "includes": [
        "modules", "modules.config", "modules.tool_registry",
        "modules.llm_client", "modules.utils",
        "modules.system_prompt", "modules.function_calling",
        "modules.vision", "modules.json_mode", "modules.embeddings",
        "modules.token_manager",
        "modules.web_search", "modules.calculator", "modules.code_executor",
        "modules.text_tools", "modules.common_tools", "modules.file_search_tools",
        "modules.mcp_office", "modules.mcp_weather", "modules.mcp_database",
        "modules.mcp_git", "modules.mcp_clipboard", "modules.mcp_encoding",
        "modules.mcp_system", "modules.mcp_email", "modules.mcp_translate",
        "modules.mcp_calendar", "modules.mcp_pdf", "modules.mcp_finance",
        "modules.mcp_geocode", "modules.mcp_navigation", "modules.mcp_skills",
        "modules.sequential_executor", "modules.plan", "modules.executor",
        "modules.loop", "modules.memory", "modules.agent", "modules.reflection",
        "modules.skills_manager",
    ],
    "include_files": [
        ("templates", "templates"),
        ("static", "static"),
        ("data", "data"),
    ],
    "excludes": [
        "tkinter", "unittest", "email", "pydoc", "test",
        "lib2to3", "distutils", "setuptools",
    ],
    "optimize": 2,
}

executables = [
    Executable(
        "server.py",
        base="console",
        target_name="wybzd.exe",
        icon=None,
    ),
]

setup(
    name="wybzd",
    version="1.3.0",
    description="wybzd 拖拽构建管理系统",
    author="wybzd",
    options={"build_exe": build_options},
    executables=executables,
)
