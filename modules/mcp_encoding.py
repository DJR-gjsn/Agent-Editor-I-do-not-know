"""
MCP Encoding 编码与实用工具模块
提供 base64、哈希、密码生成、UUID、正则、文本差异、Markdown、单位换算等工具
全部使用 Python 内置模块，无需 API Key
"""

import base64
import difflib
import hashlib
import math
import re
import secrets
import string
import time
import uuid as _uuid

from flask import jsonify, request

from . import tool_registry

# ============================================================
# 1. base64_encode / base64_decode
# ============================================================
B64ENC_DEF = {
    "name": "base64_encode",
    "description": "将文本或字符串编码为 Base64 格式。支持标准 Base64 和 URL-safe Base64。",
    "parameters": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "要编码的文本"},
            "url_safe": {"type": "boolean", "description": "使用 URL-safe Base64（默认 False）", "default": False},
        },
        "required": ["text"],
    },
}

B64DEC_DEF = {
    "name": "base64_decode",
    "description": "解码 Base64 格式的文本。自动尝试标准 Base64 和 URL-safe Base64。",
    "parameters": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Base64 编码的文本"},
        },
        "required": ["text"],
    },
}


def _exec_b64encode(args: dict) -> str:
    text = args.get("text", "")
    url_safe = bool(args.get("url_safe", False))
    data = text.encode("utf-8")
    result = base64.urlsafe_b64encode(data).decode() if url_safe else base64.b64encode(data).decode()
    return f"✅ Base64 编码结果:\n{result}"


def _exec_b64decode(args: dict) -> str:
    text = (args.get("text") or "").strip()
    for fn in [lambda t: base64.b64decode(t), lambda t: base64.urlsafe_b64decode(t)]:
        try:
            result = fn(text + "=" * (-len(text) % 4))
            decoded = result.decode("utf-8", errors="replace")
            return f"✅ Base64 解码结果:\n{decoded}"
        except Exception:
            continue
    return "❌ Base64 解码失败，请检查输入是否为有效的 Base64 字符串。"


# ============================================================
# 2. hash_compute
# ============================================================
HASH_DEF = {
    "name": "hash_compute",
    "description": "计算文本或字符串的哈希值。支持 MD5、SHA-1、SHA-256、SHA-512。",
    "parameters": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "要计算哈希的文本"},
            "algorithm": {
                "type": "string",
                "enum": ["md5", "sha1", "sha256", "sha512"],
                "description": "哈希算法，默认 sha256",
                "default": "sha256",
            },
        },
        "required": ["text"],
    },
}


def _exec_hash(args: dict) -> str:
    text = args.get("text", "")
    algo = args.get("algorithm", "sha256").lower()
    algos = {"md5": hashlib.md5, "sha1": hashlib.sha1, "sha256": hashlib.sha256, "sha512": hashlib.sha512}
    if algo not in algos:
        return f"不支持的算法: {algo}，可选: {', '.join(algos.keys())}"
    h = algos[algo](text.encode("utf-8"))
    return f"🔐 {algo.upper()}:\n{h.hexdigest()}"


# ============================================================
# 3. password_generate
# ============================================================
PASSWD_DEF = {
    "name": "password_generate",
    "description": "生成安全的随机密码。可指定长度和字符集。",
    "parameters": {
        "type": "object",
        "properties": {
            "length": {"type": "integer", "description": "密码长度，默认 16", "default": 16},
            "include_symbols": {"type": "boolean", "description": "是否包含特殊符号，默认 True", "default": True},
            "include_ambiguous": {"type": "boolean", "description": "是否包含易混淆字符 (0OIl1)，默认 False", "default": False},
        },
        "required": [],
    },
}


def _exec_password(args: dict) -> str:
    length = min(max(int(args.get("length", 16)), 6), 128)
    sym = bool(args.get("include_symbols", True))
    ambiguous = bool(args.get("include_ambiguous", False))

    chars = string.ascii_letters + string.digits
    if sym:
        chars += "!@#$%^&*()-_=+[]{}|;:,.<>?"
    if not ambiguous:
        chars = chars.translate(str.maketrans("", "", "0OIl1o"))

    pwd = "".join(secrets.choice(chars) for _ in range(length))
    return f"🔑 随机密码 ({length} 字符):\n{pwd}"


# ============================================================
# 4. uuid_generate
# ============================================================
UUID_DEF = {
    "name": "uuid_generate",
    "description": "生成 UUID（通用唯一标识符）。支持 v4（随机）和 v1（基于时间）。",
    "parameters": {
        "type": "object",
        "properties": {
            "version": {
                "type": "string",
                "enum": ["v4", "v1", "v4_upper", "v4_short"],
                "description": "UUID 版本: v4 随机(默认), v1 时间, v4_upper 大写, v4_short 无连字符",
                "default": "v4",
            },
            "count": {"type": "integer", "description": "生成数量，默认 1，最大 10", "default": 1},
        },
        "required": [],
    },
}


def _exec_uuid(args: dict) -> str:
    ver = args.get("version", "v4")
    count = min(max(int(args.get("count", 1)), 1), 10)

    results = []
    for _ in range(count):
        if ver == "v1":
            uid = str(_uuid.uuid1())
        elif ver == "v4_upper":
            uid = str(_uuid.uuid4()).upper()
        elif ver == "v4_short":
            uid = _uuid.uuid4().hex
        else:
            uid = str(_uuid.uuid4())
        results.append(uid)

    return f"🆔 UUID ({ver}, {count}个):\n" + "\n".join(results)


# ============================================================
# 5. regex_test
# ============================================================
REGEX_DEF = {
    "name": "regex_test",
    "description": "用正则表达式测试文本，返回所有匹配及其分组和位置。可用于提取邮箱、URL、电话号码等模式。",
    "parameters": {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "正则表达式，如 r'\\d{3}-\\d{4}'"},
            "text": {"type": "string", "description": "要测试的文本"},
            "flags": {
                "type": "string",
                "enum": ["", "i", "m", "im", "s"],
                "description": "正则标志: i=忽略大小写, m=多行, s=点匹配换行",
                "default": "",
            },
        },
        "required": ["pattern", "text"],
    },
}


def _exec_regex(args: dict) -> str:
    pattern = args.get("pattern", "")
    text = args.get("text", "")
    flags_str = args.get("flags", "")

    if not pattern:
        return "错误: pattern 不能为空"

    flag_map = {"i": re.IGNORECASE, "m": re.MULTILINE, "s": re.DOTALL}
    flags = 0
    for c in flags_str:
        flags |= flag_map.get(c, 0)

    try:
        compiled = re.compile(pattern, flags)
    except re.error as e:
        return f"❌ 正则表达式错误: {e}"

    matches = list(compiled.finditer(text))
    if not matches:
        return f"未找到匹配 '{pattern}'。"

    lines = [f"🔍 正则匹配结果 ({len(matches)} 处):"]
    for i, m in enumerate(matches[:20], 1):
        lines.append(f"\n  [{i}] 位置 {m.start()}-{m.end()}: \"{m.group()[:100]}\"")
        if m.groups():
            for gi, g in enumerate(m.groups(), 1):
                if g is not None:
                    lines.append(f"      组 {gi}: \"{g[:100]}\"")
        if m.groupdict():
            for gk, gv in m.groupdict().items():
                if gv is not None:
                    lines.append(f"      {gk}: \"{gv[:100]}\"")

    if len(matches) > 20:
        lines.append(f"\n  ... 还有 {len(matches) - 20} 处未显示")
    return "\n".join(lines)


# ============================================================
# 6. diff_text
# ============================================================
DIFF_DEF = {
    "name": "diff_text",
    "description": "对比两段文本的差异，返回逐行 unified diff。用于比较代码版本、文档修改等。",
    "parameters": {
        "type": "object",
        "properties": {
            "text_a": {"type": "string", "description": "原始文本（旧版本）"},
            "text_b": {"type": "string", "description": "新文本（新版本）"},
            "label_a": {"type": "string", "description": "旧版本标签，默认 '原始'", "default": "原始"},
            "label_b": {"type": "string", "description": "新版本标签，默认 '修改'", "default": "修改"},
        },
        "required": ["text_a", "text_b"],
    },
}


def _exec_diff(args: dict) -> str:
    a = args.get("text_a", "").splitlines(keepends=True)
    b = args.get("text_b", "").splitlines(keepends=True)
    la = args.get("label_a", "原始")
    lb = args.get("label_b", "修改")

    diff = list(difflib.unified_diff(a, b, fromfile=la, tofile=lb))
    if not diff:
        return "✅ 两段文本完全相同。"
    result = "".join(diff)
    if len(result) > 3000:
        result = result[:3000] + f"\n... [diff 截断，原文共 {len(result)} 字符]"
    return f"📝 文本差异:\n```diff\n{result}\n```"


# ============================================================
# 7. markdown_to_html / html_to_markdown
# ============================================================
MD2HTML_DEF = {
    "name": "markdown_to_html",
    "description": "将 Markdown 文本转换为 HTML。适合需要粘贴到网页或邮件中的场景。",
    "parameters": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Markdown 格式文本"},
        },
        "required": ["text"],
    },
}

HTML2MD_DEF = {
    "name": "html_to_markdown",
    "description": "将 HTML 文本转换为 Markdown。用于从网页内容中提取可读文本。",
    "parameters": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "HTML 格式文本"},
        },
        "required": ["text"],
    },
}


def _exec_md2html(args: dict) -> str:
    text = args.get("text", "")
    try:
        import markdown
        html = markdown.markdown(text, extensions=["extra", "codehilite", "tables"])
        return f"✅ Markdown → HTML:\n\n{html[:3000]}"
    except ImportError:
        # 简易转换
        html = _simple_md_to_html(text)
        return f"✅ Markdown → HTML (基础模式):\n\n{html[:3000]}\n\n💡 安装 markdown 库获得更好效果: pip install markdown"


def _simple_md_to_html(text: str) -> str:
    """简易 Markdown → HTML 转换"""
    # 标题
    text = re.sub(r'^### (.+)$', r'<h3>\1</h3>', text, flags=re.MULTILINE)
    text = re.sub(r'^## (.+)$', r'<h2>\1</h2>', text, flags=re.MULTILINE)
    text = re.sub(r'^# (.+)$', r'<h1>\1</h1>', text, flags=re.MULTILINE)
    # 粗体/斜体
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
    # 行内代码
    text = re.sub(r'`(.+?)`', r'<code>\1</code>', text)
    # 链接
    text = re.sub(r'\[(.+?)\]\((.+?)\)', r'<a href="\2">\1</a>', text)
    # 换行
    text = re.sub(r'\n\n', '</p><p>', text)
    return f"<p>{text}</p>"


def _exec_html2md(args: dict) -> str:
    text = args.get("text", "")
    # 简易 HTML → Markdown
    md = text
    md = re.sub(r'<h1[^>]*>(.*?)</h1>', r'# \1', md, flags=re.DOTALL | re.IGNORECASE)
    md = re.sub(r'<h2[^>]*>(.*?)</h2>', r'## \1', md, flags=re.DOTALL | re.IGNORECASE)
    md = re.sub(r'<h3[^>]*>(.*?)</h3>', r'### \1', md, flags=re.DOTALL | re.IGNORECASE)
    md = re.sub(r'<strong[^>]*>(.*?)</strong>', r'**\1**', md, flags=re.DOTALL | re.IGNORECASE)
    md = re.sub(r'<b[^>]*>(.*?)</b>', r'**\1**', md, flags=re.DOTALL | re.IGNORECASE)
    md = re.sub(r'<em[^>]*>(.*?)</em>', r'*\1*', md, flags=re.DOTALL | re.IGNORECASE)
    md = re.sub(r'<i[^>]*>(.*?)</i>', r'*\1*', md, flags=re.DOTALL | re.IGNORECASE)
    md = re.sub(r'<code[^>]*>(.*?)</code>', r'`\1`', md, flags=re.DOTALL | re.IGNORECASE)
    md = re.sub(r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', r'[\2](\1)', md, flags=re.DOTALL | re.IGNORECASE)
    md = re.sub(r'<p[^>]*>(.*?)</p>', r'\1\n\n', md, flags=re.DOTALL | re.IGNORECASE)
    md = re.sub(r'<br\s*/?>', '\n', md, flags=re.IGNORECASE)
    md = re.sub(r'<[^>]+>', '', md)
    return f"✅ HTML → Markdown:\n\n{md[:3000]}"


# ============================================================
# 8. unit_convert
# ============================================================
UNIT_DEF = {
    "name": "unit_convert",
    "description": (
        "单位换算。支持长度(m/ft/in/km/mi/cm/mm)、重量(kg/lb/oz/g)、"
        "温度(C/F/K)、面积、体积、速度、数据量(B/KB/MB/GB/TB)。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "value": {"type": "number", "description": "要转换的数值"},
            "from_unit": {"type": "string", "description": "源单位，如 'km'、'lb'、'MB'"},
            "to_unit": {"type": "string", "description": "目标单位，如 'mi'、'kg'、'GB'"},
        },
        "required": ["value", "from_unit", "to_unit"],
    },
}

# 换算表（以标准单位为基础）
_LENGTH = {"m": 1, "km": 1000, "cm": 0.01, "mm": 0.001, "mi": 1609.344, "ft": 0.3048, "in": 0.0254, "yd": 0.9144}
_WEIGHT = {"kg": 1, "g": 0.001, "lb": 0.453592, "oz": 0.0283495, "ton": 1000}
_DATA = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4, "PB": 1024**5}
_AREA = {"m2": 1, "km2": 1e6, "ha": 10000, "acre": 4046.86, "ft2": 0.092903}
_VOLUME = {"L": 1, "mL": 0.001, "gal": 3.78541, "qt": 0.946353, "cup": 0.236588}
_SPEED = {"m/s": 1, "km/h": 0.277778, "mph": 0.44704, "knot": 0.514444}


def _exec_unit_convert(args: dict) -> str:
    value = float(args.get("value", 0))
    fu = (args.get("from_unit") or "").strip()
    tu = (args.get("to_unit") or "").strip()

    if not fu or not tu:
        return "错误: from_unit 和 to_unit 不能为空"

    # 温度特殊处理
    if fu in ("C", "F", "K") and tu in ("C", "F", "K"):
        result = _convert_temp(value, fu, tu)
        return f"🌡️ {value}{fu} = {result:.2f}{tu}"

    # 查找换算表
    for name, table in [("长度", _LENGTH), ("重量", _WEIGHT), ("数据量", _DATA),
                         ("面积", _AREA), ("体积", _VOLUME), ("速度", _SPEED)]:
        if fu in table and tu in table:
            std = value * table[fu]
            result = std / table[tu]
            return f"📐 {value} {fu} = {result:g} {tu} ({name})"

    return f"❌ 不支持的单位组合: {fu} → {tu}\n支持: 长度({', '.join(_LENGTH)}) 重量({', '.join(_WEIGHT)}) 数据量({', '.join(_DATA)}) 温度(C/F/K)"


def _convert_temp(v: float, f: str, t: str) -> float:
    if f == t:
        return v
    # 先转 Celsius
    c = v if f == "C" else (v - 32) * 5 / 9 if f == "F" else v - 273.15
    # 从 Celsius 转目标
    return c if t == "C" else c * 9 / 5 + 32 if t == "F" else c + 273.15


# ============================================================
# 9. url_encode / url_decode
# ============================================================
import urllib.parse

URLENC_DEF = {
    "name": "url_encode",
    "description": "对文本进行 URL 编码（百分号编码）或解码。",
    "parameters": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "要编码或解码的文本"},
            "action": {
                "type": "string",
                "enum": ["encode", "decode"],
                "description": "encode=编码, decode=解码",
                "default": "encode",
            },
        },
        "required": ["text"],
    },
}


def _exec_urlenc(args: dict) -> str:
    text = args.get("text", "")
    action = args.get("action", "encode")
    if action == "decode":
        result = urllib.parse.unquote(text)
        return f"✅ URL 解码:\n{result}"
    else:
        result = urllib.parse.quote(text, safe="")
        return f"✅ URL 编码:\n{result}"


# ============================================================
# 注册所有工具
# ============================================================
_tool_list = [
    (B64ENC_DEF, _exec_b64encode),
    (B64DEC_DEF, _exec_b64decode),
    (HASH_DEF, _exec_hash),
    (PASSWD_DEF, _exec_password),
    (UUID_DEF, _exec_uuid),
    (REGEX_DEF, _exec_regex),
    (DIFF_DEF, _exec_diff),
    (MD2HTML_DEF, _exec_md2html),
    (HTML2MD_DEF, _exec_html2md),
    (UNIT_DEF, _exec_unit_convert),
    (URLENC_DEF, _exec_urlenc),
]

for tool_def, executor in _tool_list:
    tool_registry.register(tool_def["name"], tool_def, executor)


# ============================================================
# Flask 路由
# ============================================================
def register_routes(app, http_session=None):
    @app.route("/api/encoding/test-connection", methods=["POST"])
    def encoding_test_connection():
        """编码模块无需外部连接，始终可用"""
        modules_ok = []
        try:
            import markdown
            modules_ok.append("markdown")
        except ImportError:
            pass
        return jsonify({
            "success": True,
            "message": f"编码工具模块就绪（{len(_tool_list)} 个工具）",
            "extras": modules_ok,
            "note": "所有工具使用 Python 内置模块，无需外部 API Key" if not modules_ok else None,
        })
