"""
Text Tools 文本工具模块
文本统计和格式化，注册为 AI 可调用的工具
"""

import re
import time
from collections import Counter
from flask import jsonify, request

from . import tool_registry

# ============================================================
# 共享逻辑（消除 tool executor 与 Flask 路由之间的重复代码）
# ============================================================
_FORMAT_ACTIONS = {
    "lowercase": lambda t: t.lower(),
    "uppercase": lambda t: t.upper(),
    "titlecase": lambda t: t.title(),
    "trim_lines": lambda t: "\n".join(l.strip() for l in t.splitlines()),
    "remove_empty_lines": lambda t: "\n".join(l for l in t.splitlines() if l.strip()),
    "remove_duplicate_lines": lambda t: "\n".join(dict.fromkeys(t.splitlines())),
    "sort_lines": lambda t: "\n".join(sorted(t.splitlines())),
    "sort_lines_reverse": lambda t: "\n".join(sorted(t.splitlines(), reverse=True)),
    "remove_extra_spaces": lambda t: re.sub(r"\s+", " ", t),
    "reverse": lambda t: t[::-1],
    "strip": lambda t: t.strip(),
}
_FORMAT_ACTION_NAMES = list(_FORMAT_ACTIONS.keys())


def _analyze_text(text: str) -> dict:
    """分析文本，返回统计信息 dict（供 tool executor 与路由复用）"""
    char_count = len(text)
    char_no_space = len(text.replace(" ", "").replace("\n", "").replace("\t", ""))
    byte_count = len(text.encode("utf-8"))
    words_en = len(re.findall(r"[a-zA-Z]+", text))
    cn_chars = len(re.findall(r"[一-鿿]", text))
    total_words = words_en + cn_chars
    lines = text.splitlines()
    line_count = len(lines)
    non_empty_lines = len([l for l in lines if l.strip()])
    paragraphs = len(re.split(r"\n\s*\n", text.strip()))
    sentences = len(re.findall(r"[^。！？.!?\n]+[。！？.!?]", text))
    reading_time = round(cn_chars / 400 + words_en / 200, 1)
    en_words_list = re.findall(r"[a-zA-Z]{3,}", text.lower())
    word_freq = Counter(en_words_list).most_common(10)

    return {
        "char_count": char_count, "char_no_space": char_no_space,
        "byte_count": byte_count, "word_count": total_words,
        "word_count_en": words_en, "word_count_cn": cn_chars,
        "line_count": line_count, "non_empty_lines": non_empty_lines,
        "paragraph_count": paragraphs, "sentence_count": sentences,
        "reading_time_min": reading_time, "top_words": word_freq,
    }


# ============================================================
# 工具定义
# ============================================================
TEXT_ANALYZE_DEFINITION = {
    "name": "text_analyze",
    "description": "分析文本的统计信息，包括字符数、词数、行数、段落数、阅读时间等。",
    "parameters": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "要分析的文本内容"},
        },
        "required": ["text"],
    },
}

TEXT_FORMAT_DEFINITION = {
    "name": "text_format",
    "description": "对文本进行格式化处理：大小写转换、去除空行、排序、去重、反转等。",
    "parameters": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "要格式化的文本内容"},
            "action": {
                "type": "string",
                "description": f"格式化操作: {', '.join(_FORMAT_ACTION_NAMES)}",
                "enum": _FORMAT_ACTION_NAMES,
            },
        },
        "required": ["text", "action"],
    },
}


def execute_text_analyze(args: dict) -> str:
    text = args.get("text", "")
    if not text:
        return "错误: 文本不能为空"
    s = _analyze_text(text)
    return (
        f"文本分析结果:\n"
        f"- 字符数: {s['char_count']} (不含空格: {s['char_no_space']})\n"
        f"- 词数: {s['word_count']} (英文: {s['word_count_en']}, 中文: {s['word_count_cn']})\n"
        f"- 行数: {s['line_count']} (非空行: {s['non_empty_lines']})\n"
        f"- 段落数: {s['paragraph_count']}\n"
        f"- 句子数: {s['sentence_count']}\n"
        f"- 预估阅读时间: {s['reading_time_min']} 分钟\n"
        f"- 字节数: {s['byte_count']}"
    )


def execute_text_format(args: dict) -> str:
    text = args.get("text", "")
    action = args.get("action", "lowercase")
    if not text:
        return "错误: 文本不能为空"
    if action not in _FORMAT_ACTIONS:
        return f"错误: 不支持的操作 '{action}'，可选: {', '.join(_FORMAT_ACTION_NAMES)}"
    result = _FORMAT_ACTIONS[action](text)
    preview = result[:1000]
    suffix = "…(截断)" if len(result) > 1000 else ""
    return f"格式化完成 ({action}):\n{preview}{suffix}"


tool_registry.register("text_analyze", TEXT_ANALYZE_DEFINITION, execute_text_analyze)
tool_registry.register("text_format", TEXT_FORMAT_DEFINITION, execute_text_format)


# ============================================================
# Flask 路由（供前端面板手动使用）
# ============================================================
def register_routes(app):
    @app.route("/api/text-tools/analyze", methods=["POST"])
    def text_analyze():
        data = request.get_json(force=True)
        text = data.get("text", "")
        if not text:
            return jsonify({"error": "text 不能为空"}), 400

        t0 = time.time()
        stats = _analyze_text(text)
        top_words = [{"word": w, "count": c} for w, c in stats.pop("top_words", [])]
        latency_ms = round((time.time() - t0) * 1000)

        return jsonify({
            "success": True,
            "stats": stats,
            "top_words": top_words,
            "latency_ms": latency_ms,
        })

    @app.route("/api/text-tools/format", methods=["POST"])
    def text_format():
        data = request.get_json(force=True)
        text = (data.get("text") or "")
        action = data.get("action", "lowercase")
        if not text:
            return jsonify({"error": "text 不能为空"}), 400
        if action not in _FORMAT_ACTIONS:
            return jsonify({"error": f"不支持的操作: {action}"}), 400

        t0 = time.time()
        try:
            result = _FORMAT_ACTIONS[action](text)
            latency_ms = round((time.time() - t0) * 1000)
            return jsonify({
                "success": True, "action": action, "result": result,
                "original_length": len(text), "result_length": len(result),
                "latency_ms": latency_ms,
            })
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 400
