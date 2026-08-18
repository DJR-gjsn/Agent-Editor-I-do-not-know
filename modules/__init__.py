"""
模块注册中心
遍历导入所有功能模块和工具模块并注册到 Flask app
"""

import requests


def register_all(app):
    # 创建共享 HTTP Session 供所有模块复用
    http_session = getattr(app, '_http_session', None)
    if http_session is None:
        http_session = requests.Session()
        http_session.headers.update({"Content-Type": "application/json"})
        app._http_session = http_session

    # 功能模块
    from . import system_prompt, function_calling, vision, json_mode, embeddings, token_manager
    # 工具模块（导入即注册到 tool_registry）
    from . import web_search, calculator, code_executor, text_tools, tool_registry, common_tools, file_search_tools
    # MCP 工具模块
    from . import mcp_office, mcp_weather, mcp_database, mcp_git
    from . import mcp_clipboard, mcp_encoding, mcp_system
    from . import mcp_email, mcp_translate, mcp_calendar
    from . import mcp_pdf, mcp_finance, mcp_geocode, mcp_navigation, mcp_skills
    # 通用工具集（压缩/HTTP/截图/图片）
    from . import mcp_utility
    # 顺序执行 & 计划模块
    from . import sequential_executor, plan, executor, loop
    # 记忆持久化模块
    from . import memory as memory_module
    # Agent 编排 & 反思模块
    from . import agent, reflection
    # 技能管理器模块
    from . import skills_manager
    # 记忆总结工具
    from . import memory_summarizer
    # 向量记忆（语义搜索）
    from . import vector_memory
    # 外部 MCP 工具
    from . import mcp_client, mcp_manager

    system_prompt.register_routes(app)
    function_calling.register_routes(app)
    vision.register_routes(app, http_session)
    json_mode.register_routes(app, http_session)
    embeddings.register_routes(app, http_session)
    token_manager.register_routes(app)

    web_search.register_routes(app, http_session)
    calculator.register_routes(app)
    code_executor.register_routes(app)
    text_tools.register_routes(app)
    common_tools.register_routes(app, http_session)
    file_search_tools.register_routes(app)
    mcp_office.register_routes(app, http_session)
    mcp_weather.register_routes(app, http_session)
    mcp_database.register_routes(app)
    mcp_git.register_routes(app)
    mcp_clipboard.register_routes(app)
    mcp_encoding.register_routes(app)
    mcp_system.register_routes(app)
    mcp_email.register_routes(app)
    mcp_translate.register_routes(app)
    mcp_calendar.register_routes(app)
    mcp_pdf.register_routes(app)
    mcp_finance.register_routes(app)
    mcp_geocode.register_routes(app)
    mcp_navigation.register_routes(app)
    mcp_skills.register_routes(app)
    mcp_utility.register_routes(app)
    sequential_executor.register_routes(app)
    plan.register_routes(app, http_session)
    executor.register_routes(app)
    loop.register_routes(app)
    agent.register_routes(app, http_session)
    reflection.register_routes(app, http_session)
    skills_manager.register_routes(app, http_session)
    memory_module.register_routes(app)
    memory_summarizer.register_routes(app)
    vector_memory.register_routes(app)
    mcp_manager.register_routes(app)
