"""
Token Manager 模块
Token 计数与模型上下文窗口管理
"""

import threading
from flask import jsonify, request

# 尝试导入 tiktoken，失败则使用近似估算
try:
    import tiktoken

    _HAS_TIKTOKEN = True
    # 缓存编码器
    _encoders = {}
    _enc_lock = threading.Lock()

    def _get_encoder(model):
        with _enc_lock:
            if model not in _encoders:
                try:
                    _encoders[model] = tiktoken.encoding_for_model(model)
                except KeyError:
                    _encoders[model] = tiktoken.get_encoding("cl100k_base")
            return _encoders[model]

except ImportError:
    _HAS_TIKTOKEN = False


# 常见模型上下文窗口信息
MODEL_INFO = {
    "gpt-4o": {"max_tokens": 128000, "training": "2023-10"},
    "gpt-4o-mini": {"max_tokens": 128000, "training": "2023-10"},
    "gpt-4-turbo": {"max_tokens": 128000, "training": "2023-04"},
    "gpt-4": {"max_tokens": 8192, "training": "2021-09"},
    "gpt-3.5-turbo": {"max_tokens": 16385, "training": "2021-09"},
    "claude-3-5-sonnet": {"max_tokens": 200000, "training": "2024-04"},
    "claude-3-opus": {"max_tokens": 200000, "training": "2024-02"},
    "deepseek-chat": {"max_tokens": 65536, "training": "N/A"},
    "glm-4": {"max_tokens": 128000, "training": "N/A"},
    "qwen-turbo": {"max_tokens": 131072, "training": "N/A"},
    "moonshot-v1-8k": {"max_tokens": 8192, "training": "N/A"},
    "moonshot-v1-32k": {"max_tokens": 32768, "training": "N/A"},
    "moonshot-v1-128k": {"max_tokens": 131072, "training": "N/A"},
    "text-embedding-3-small": {"max_tokens": 8191, "training": "N/A"},
    "text-embedding-3-large": {"max_tokens": 8191, "training": "N/A"},
}


def register_routes(app):
    @app.route("/api/token-manager/count", methods=["POST"])
    def tm_count():
        data = request.get_json(force=True)
        text = data.get("text", "")
        model = data.get("model", "gpt-3.5-turbo")

        char_count = len(text)

        if _HAS_TIKTOKEN:
            try:
                enc = _get_encoder(model)
                token_count = len(enc.encode(text))
                method = "tiktoken"
            except Exception:
                token_count = _estimate_tokens(text)
                method = "approximation"
        else:
            token_count = _estimate_tokens(text)
            method = "approximation"

        return jsonify({
            "tokens": token_count,
            "characters": char_count,
            "model": model,
            "method": method,
        })

    @app.route("/api/token-manager/info", methods=["GET"])
    def tm_info():
        # 可选：查询特定模型
        model = request.args.get("model")
        if model and model in MODEL_INFO:
            return jsonify({model: MODEL_INFO[model]})
        return jsonify(MODEL_INFO)


def _estimate_tokens(text):
    """基于字符类型的粗略 token 估算（fallback）"""
    import re

    # 英文单词/标点
    en_chars = len(re.findall(r"[a-zA-Z0-9]", text))
    # CJK 字符
    cjk_chars = len(re.findall(r"[一-鿿　-〿＀-￯]", text))
    # 其他字符
    other = len(text) - en_chars - cjk_chars

    # 英文约 4 字符/token，CJK 约 1.5 字符/token
    return max(1, round(en_chars / 4 + cjk_chars / 1.5 + other / 4))
