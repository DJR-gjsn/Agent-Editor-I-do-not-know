"""
配置中心 — 所有模块共享的配置管理
统一从环境变量读取，支持运行时覆盖，避免在 8+ 个文件中重复 os.getenv()

使用方式:
    from .config import get_config

    cfg = get_config()
    print(cfg["model"])        # 读取配置
    cfg["model"] = "gpt-4"     # 运行时覆盖
"""

import os
import threading

_lock = threading.Lock()

# 默认配置
_DEFAULTS = {
    "api_base": "https://api.openai.com/v1",
    "api_key": "sk-your-api-key-here",
    "model": "gpt-3.5-turbo",
    "max_tokens": 2048,
    "temperature": 0.7,
    "port": 5000,
    "system_prompt": (
        "你是一个有帮助的AI助手。\n\n"
        "## 工具选择规则（重要）\n"
        "- 创建 Word 文档（.docx）→ 必须使用 word_create/word_add_heading/word_add_paragraph/word_save\n"
        "- 创建 Excel 表格（.xlsx）→ 必须使用 excel_create/excel_write_cell/excel_save\n"
        "- 创建 PPT 演示文稿（.pptx）→ 必须使用 ppt_create/ppt_add_slide/ppt_save\n"
        "- 创建 PDF 文件 → 使用 pdf_create（仅用于最终导出为 PDF 格式）\n"
        "- 创建文本文件 → 使用 file_write\n"
        "- 不要将 pdf_create 用于创建 Word/Excel/PPT 文档"
    ),
}

# 环境变量 → 配置键映射
_ENV_MAP = {
    "LLM_API_BASE": "api_base",
    "LLM_API_KEY": "api_key",
    "LLM_MODEL": "model",
    "LLM_MAX_TOKENS": "max_tokens",
    "LLM_TEMPERATURE": "temperature",
    "LLM_SYSTEM_PROMPT": "system_prompt",
    "PORT": "port",
}

# 需要转为 int 的键
_INT_KEYS = {"max_tokens", "port"}

# 需要转为 float 的键
_FLOAT_KEYS = {"temperature"}


def _get_runtime_config() -> dict:
    """从环境变量读取并构建配置字典，数值类型自动转换"""
    cfg = dict(_DEFAULTS)
    for env_key, cfg_key in _ENV_MAP.items():
        val = os.getenv(env_key)
        if val is not None:
            if cfg_key in _INT_KEYS:
                try:
                    cfg[cfg_key] = int(val)
                except ValueError:
                    pass
            elif cfg_key in _FLOAT_KEYS:
                try:
                    cfg[cfg_key] = float(val)
                except ValueError:
                    pass
            else:
                cfg[cfg_key] = val
    return cfg


# 模块级配置缓存（首次加载后不变，除非显式调用 reload_config）
_cfg = None


def get_config() -> dict:
    """
    获取当前配置（返回可变字典，可直接修改实现运行时覆盖）
    首次调用从环境变量加载，之后返回缓存
    """
    global _cfg
    with _lock:
        if _cfg is None:
            _cfg = _get_runtime_config()
    return _cfg


def reload_config():
    """重新从环境变量加载配置（用于测试或动态更新）"""
    global _cfg
    with _lock:
        _cfg = _get_runtime_config()
    return _cfg


def has_api_key() -> bool:
    """检查是否配置了有效的 API Key"""
    cfg = get_config()
    key = cfg.get("api_key", "")
    return bool(key and key != _DEFAULTS["api_key"])
