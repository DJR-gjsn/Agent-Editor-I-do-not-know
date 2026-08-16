# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for wybzd 拖拽构建管理系统
"""

import os
import sys

block_cipher = None

# 收集数据文件
datas = [
    ('templates', 'templates'),
    ('static', 'static'),
    ('data', 'data'),
]

# 隐藏导入
hidden_imports = [
    'flask', 'requests', 'tiktoken',
    'modules', 'modules.config', 'modules.tool_registry',
    'modules.llm_client', 'modules.utils',
    'modules.system_prompt', 'modules.function_calling',
    'modules.vision', 'modules.json_mode', 'modules.embeddings',
    'modules.token_manager',
    'modules.web_search', 'modules.calculator', 'modules.code_executor',
    'modules.text_tools', 'modules.common_tools', 'modules.file_search_tools',
    'modules.mcp_office', 'modules.mcp_weather', 'modules.mcp_database',
    'modules.mcp_git', 'modules.mcp_clipboard', 'modules.mcp_encoding',
    'modules.mcp_system', 'modules.mcp_email', 'modules.mcp_translate',
    'modules.mcp_calendar', 'modules.mcp_pdf', 'modules.mcp_finance',
    'modules.mcp_geocode', 'modules.mcp_navigation', 'modules.mcp_skills',
    'modules.sequential_executor', 'modules.plan', 'modules.executor',
    'modules.loop', 'modules.memory', 'modules.agent', 'modules.reflection',
    'modules.skills_manager',
    'jinja2', 'jinja2.ext',
    'markupsafe',
    'itsdangerous',
    'werkzeug', 'blinker',
]

a = Analysis(
    ['server.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='wybzd',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
