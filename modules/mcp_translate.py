"""
MCP Translate 翻译服务模块
多后端自动回退：有道 → MyMemory → Google → Argos(离线)
"""
import html
import os
import re
import time

from flask import jsonify, request

from . import tool_registry

# 语种检测 API key（可通过环境变量或 /api/translate/api-key 设置）
_detect_api_key = os.environ.get("DETECTLANGUAGE_API_KEY", "")

# ============================================================
# 工具定义
# ============================================================
TRANSLATE_DEF = {
    "name": "translate_text",
    "description": (
        "将文本翻译为其他语言。自动检测源语言。"
        "支持的语言代码: zh=中文, en=英语, ja=日语, ko=韩语, fr=法语, de=德语, "
        "es=西班牙语, ru=俄语, ar=阿拉伯语, pt=葡萄牙语, it=意大利语, th=泰语, vi=越南语 等。"
        "多后端自动回退（有道 > MyMemory > Google > 离线），国内网络可用。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "要翻译的文本"},
            "target": {"type": "string", "description": "目标语言代码，如 'zh'、'en'、'ja'。默认 'zh'", "default": "zh"},
            "source": {"type": "string", "description": "源语言代码，默认 'auto' 自动检测", "default": "auto"},
        },
        "required": ["text"],
    },
}

DETECT_DEF = {
    "name": "detect_language",
    "description": "检测文本的语言。返回语言代码和名称。",
    "parameters": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "要检测的文本"},
        },
        "required": ["text"],
    },
}


# ============================================================
# 语言名称映射
# ============================================================
LANG_NAMES = {
    "zh-CN": "中文（简体）", "zh-TW": "中文（繁体）", "zh": "中文",
    "en": "英语", "ja": "日语", "ko": "韩语", "fr": "法语", "de": "德语",
    "es": "西班牙语", "ru": "俄语", "ar": "阿拉伯语", "pt": "葡萄牙语",
    "it": "意大利语", "th": "泰语", "vi": "越南语", "nl": "荷兰语",
    "pl": "波兰语", "tr": "土耳其语", "hi": "印地语", "id": "印尼语",
    "ms": "马来语", "sv": "瑞典语", "da": "丹麦语", "fi": "芬兰语",
    "no": "挪威语", "cs": "捷克语", "ro": "罗马尼亚语", "hu": "匈牙利语",
    "el": "希腊语", "he": "希伯来语", "uk": "乌克兰语",
}


# ============================================================
# 翻译入口 — 多后端回退链
# ============================================================
def _exec_translate(args: dict) -> str:
    text = args.get("text", "")
    target = args.get("target", "zh")
    source = args.get("source", "auto")

    if not text:
        return "错误: text 不能为空"

    errors = []
    src_name = LANG_NAMES.get(source, source)
    tgt_name = LANG_NAMES.get(target, target)

    # 按优先级回退：有道 → MyMemory → Google → Argos 离线
    backends = [
        ("有道翻译", _translate_youdao),
        ("MyMemory", _translate_mymemory),
        ("Google", _translate_google_cn),
        ("Argos 离线", _translate_argos),
    ]

    for name, backend in backends:
        try:
            result = backend(text, target, source)
            if result:
                return (
                    f"翻译 ({src_name} → {tgt_name}) [{name}]:\n\n"
                    f"原文: {text[:200]}{'...' if len(text) > 200 else ''}\n\n"
                    f"译文: {result}"
                )
        except Exception as e:
            errors.append(f"{name}: {str(e)[:100]}")

    return f"翻译失败，所有后端均不可用:\n" + "\n".join(f"  - {err}" for err in errors)


# ============================================================
# 后端 1: 有道移动端（国内最快，免 Key）
# ============================================================
def _translate_youdao(text: str, target: str, source: str) -> str:
    """有道移动端非官方接口，无需 API Key，国内可用"""
    import requests as _r

    lang_map = {
        "zh": "zh-CHS", "zh-CN": "zh-CHS", "zh-TW": "zh-CHT",
        "en": "en", "ja": "ja", "ko": "ko", "fr": "fr",
        "de": "de", "es": "es", "ru": "ru", "pt": "pt",
        "it": "it", "th": "th", "vi": "vi", "ar": "ar",
    }
    tl = lang_map.get(target, target)
    sl = lang_map.get(source, source) if source != "auto" else "auto"

    # 有道移动端接口
    resp = _r.post(
        "https://m.youdao.com/translate",
        data={"inputtext": text, "type": "AUTO" if sl == "auto" else f"{sl}2{tl}"},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=8,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}")

    # 提取翻译结果
    match = re.search(r'<ul[^>]*id="translateResult"[^>]*>(.*?)</ul>', resp.text, re.DOTALL)
    if match:
        # 提取所有 <li> 中的文本
        parts = re.findall(r'<li[^>]*>(.*?)</li>', match.group(1), re.DOTALL)
        result = "".join(re.sub(r'<[^>]+>', '', p).strip() for p in parts)
        result = html.unescape(result)
        if result and result != text:
            return result

    raise RuntimeError("解析翻译结果失败")


# ============================================================
# 后端 2: MyMemory（免 Key，国内可用）
# ============================================================
def _translate_mymemory(text: str, target: str, source: str) -> str:
    """MyMemory 翻译 API，免费，无需 API Key，国内通常可用"""
    import requests as _r

    lang_map = {
        "zh": "zh-CN", "zh-CN": "zh-CN", "en": "en", "ja": "ja",
        "ko": "ko", "fr": "fr", "de": "de", "es": "es",
        "ru": "ru", "pt": "pt", "it": "it",
    }
    tl = lang_map.get(target, target)
    # MyMemory 不支持 auto，默认用 en
    sl = lang_map.get(source, source) if source != "auto" else "en"

    # 拆分长文本（MyMemory 免费版限制 500 字符/次）
    chunk_size = 450
    if len(text) <= chunk_size:
        chunks = [text]
    else:
        # 按句子边界拆分
        chunks = _split_text(text, chunk_size)

    results = []
    for chunk in chunks:
        params = {"q": chunk, "langpair": f"{sl}|{tl}"}
        resp = _r.get("https://api.mymemory.translated.net/get", params=params, timeout=10)
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}")
        data = resp.json()
        match_score = data.get("responseStatus", 0)
        translated = data.get("responseData", {}).get("translatedText", "")
        if not translated or translated == chunk:
            raise RuntimeError(f"未获取到翻译 (score={match_score})")
        results.append(translated)

    return "".join(results)


def _split_text(text: str, max_len: int) -> list:
    """按句子边界拆分文本，避免截断"""
    sentences = re.split(r'(?<=[。！？.!?\n])', text)
    chunks = []
    current = ""
    for s in sentences:
        if len(current) + len(s) <= max_len:
            current += s
        else:
            if current:
                chunks.append(current)
            current = s
    if current:
        chunks.append(current)
    return chunks if chunks else [text]


# ============================================================
# 后端 3: Google 翻译（多域名尝试，有时国内可用）
# ============================================================
def _translate_google_cn(text: str, target: str, source: str) -> str:
    """Google 翻译（多域名尝试）"""
    import requests as _r
    lang_map = {
        "zh": "zh-CN", "ja": "ja", "ko": "ko", "en": "en",
        "fr": "fr", "de": "de", "es": "es", "ru": "ru",
        "pt": "pt", "it": "it", "th": "th", "vi": "vi",
    }
    tl = lang_map.get(target, target)
    sl = lang_map.get(source, source) if source != "auto" else "auto"

    domains = [
        "translate.google.com.hk",
        "translate.google.com",
        "translate.google.cn",
    ]
    for domain in domains:
        try:
            url = f"https://{domain}/translate_a/single"
            params = {"client": "gtx", "sl": sl, "tl": tl, "dt": "t", "q": text}
            resp = _r.get(url, params=params, timeout=6)
            if resp.status_code == 200:
                data = resp.json()
                parts = []
                for sentence in data[0]:
                    if sentence[0]:
                        parts.append(sentence[0])
                result = "".join(parts)
                if result and result != text:
                    return result
        except Exception:
            continue
    raise RuntimeError("所有 Google 域名均不可用")


# ============================================================
# 后端 4: Argos Translate（离线回退）
# ============================================================
def _translate_argos(text: str, target: str, source: str) -> str:
    """Argos Translate 离线翻译，首次需安装模型"""
    import argostranslate.package
    import argostranslate.translate

    # 映射语言代码
    argos_lang = {
        "zh": "zh", "en": "en", "ja": "ja", "ko": "ko",
        "fr": "fr", "de": "de", "es": "es", "ru": "ru",
        "pt": "pt", "it": "it", "ar": "ar",
    }
    from_code = argos_lang.get(source, source) if source != "auto" else "en"
    to_code = argos_lang.get(target, target)

    # 检查是否已安装所需语言包
    installed = argostranslate.package.get_installed_packages()
    from_lang = next((p for p in installed if p.from_code == from_code), None)
    to_lang = next((p for p in installed if p.to_code == to_code), None)

    if not from_lang or not to_lang:
        raise RuntimeError(
            f"Argos 未安装 {from_code}→{to_code} 语言包。"
            f"运行: python -c \"import argostranslate.package; "
            f"argostranslate.package.update_package_index(); "
            f"from argostranslate.package import get_available_packages; "
            f"pkg = next(p for p in get_available_packages() if p.from_code=='{from_code}' and p.to_code=='{to_code}'); "
            f"pkg.install()\""
        )

    result = argostranslate.translate.translate(text, from_code, to_code)
    if result and result != text:
        return result
    raise RuntimeError("Argos 翻译返回空")


# ============================================================
# 语种检测
# ============================================================
def _exec_detect(args: dict) -> str:
    text = args.get("text", "")
    if not text:
        return "错误: text 不能为空"

    # 1. 尝试 langdetect（简单快速，免 Key）
    try:
        from langdetect import detect
        result = detect(text)
        lang_name = LANG_NAMES.get(result, result)
        return f"检测结果: {result} ({lang_name})\n文本: {text[:100]}"
    except Exception:
        pass

    # 2. 尝试 deep_translator single_detection
    try:
        from deep_translator import single_detection
        result = single_detection(text, api_key=_detect_api_key or None)
        if result:
            lang_name = LANG_NAMES.get(result, result)
            return f"检测结果: {result} ({lang_name})\n文本: {text[:100]}"
    except Exception:
        pass

    # 3. 启发式检测（终极回退）
    return _heuristic_detect(text)


def _heuristic_detect(text: str) -> str:
    """启发式语种检测（无需任何依赖）"""
    cjk = sum(1 for c in text if '一' <= c <= '鿿')
    jp = sum(1 for c in text if '぀' <= c <= 'ヿ')
    kr = sum(1 for c in text if '가' <= c <= '힯')
    ar = sum(1 for c in text if '؀' <= c <= 'ۿ')
    ru = sum(1 for c in text if 'Ѐ' <= c <= 'ӿ')
    th = sum(1 for c in text if '฀' <= c <= '๿')

    total = len(text) or 1
    if cjk > total * 0.3: lang = "zh"
    elif jp > total * 0.1: lang = "ja"
    elif kr > total * 0.3: lang = "ko"
    elif ar > total * 0.2: lang = "ar"
    elif ru > total * 0.3: lang = "ru"
    elif th > total * 0.2: lang = "th"
    else:
        ascii_count = sum(1 for c in text if c.isascii() and c.isalpha())
        lang = "en" if ascii_count > len(text) * 0.5 else "unknown"

    lang_name = LANG_NAMES.get(lang, lang)
    return (
        f"检测结果: {lang} ({lang_name}) [启发式]\n"
        f"文本: {text[:100]}\n"
        f"提示: pip install langdetect 获得更准确的检测"
    )


# ============================================================
# 注册工具
# ============================================================
_tool_list = [
    (TRANSLATE_DEF, _exec_translate),
    (DETECT_DEF, _exec_detect),
]

for tool_def, executor in _tool_list:
    tool_registry.register(tool_def["name"], tool_def, executor)


# ============================================================
# Flask 路由
# ============================================================
def register_routes(app, http_session=None):
    @app.route("/api/translate/api-key", methods=["GET", "POST"])
    def translate_api_key():
        """获取或设置 detectlanguage API Key"""
        global _detect_api_key
        if request.method == "POST":
            data = request.get_json(force=True) or {}
            _detect_api_key = (data.get("api_key") or "").strip()
            return jsonify({"success": True, "has_key": bool(_detect_api_key)})
        return jsonify({"has_key": bool(_detect_api_key), "preview": (_detect_api_key[:4] + "****") if _detect_api_key else ""})

    @app.route("/api/translate/test-connection", methods=["POST"])
    def translate_test_connection():
        """测试翻译服务可用性"""
        backends_ok = []
        backends_fail = []

        # 测有道
        try:
            import requests as _r
            resp = _r.post("https://m.youdao.com/translate",
                         data={"inputtext": "test", "type": "AUTO"},
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
            backends_ok.append(f"有道翻译 (HTTP {resp.status_code})" if resp.status_code == 200 else None)
            if resp.status_code != 200:
                backends_fail.append(f"有道: HTTP {resp.status_code}")
        except Exception as e:
            backends_fail.append(f"有道: {e}")

        # 测 MyMemory
        try:
            import requests as _r
            resp = _r.get("https://api.mymemory.translated.net/get",
                        params={"q": "test", "langpair": "en|zh"}, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("responseData", {}).get("translatedText"):
                    backends_ok.append("MyMemory")
                else:
                    backends_fail.append("MyMemory: 返回空")
            else:
                backends_fail.append(f"MyMemory: HTTP {resp.status_code}")
        except Exception as e:
            backends_fail.append(f"MyMemory: {e}")

        # 测 Argos
        try:
            import argostranslate.package
            pkgs = argostranslate.package.get_installed_packages()
            langs = set()
            for p in pkgs:
                langs.add(p.from_code)
                langs.add(p.to_code)
            backends_ok.append(f"Argos 离线 ({len(langs)} 语种)")
        except ImportError:
            backends_fail.append("Argos: 未安装 (pip install argostranslate)")
        except Exception as e:
            backends_fail.append(f"Argos: {e}")

        # 测 langdetect
        try:
            from langdetect import detect
            backends_ok.append("langdetect 语种检测")
        except ImportError:
            backends_fail.append("langdetect: 未安装 (pip install langdetect)")

        success = len(backends_ok) >= 1
        msg = ""
        if backends_ok:
            msg += f"可用后端: {', '.join(backends_ok)}\n"
        if backends_fail:
            msg += f"不可用: {', '.join(backends_fail)}\n"

        if success:
            msg += "\n国内网络推荐安装 langdetect 获得更好的语种检测。"
        else:
            msg += "\n所有后端不可用！请检查网络。可尝试: pip install argostranslate 获得离线翻译能力。"

        return jsonify({"success": success, "message": msg})
