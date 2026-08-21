#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 static/app.js 提取前端元数据，生成 modules/meta.py 的数据部分。

提取方法（本机已确认 node v24.18.0 可用，走 Node 路径）：
1. 首选 Node.js：把 JS 对象/数组字面量原样交给 `node -e` 求值
   （eval + JSON.stringify，文件 IO 传递，不依赖 piped stdio）。
2. 无 Node 时回退：Python 括号配对 + JS→JSON 兼容子集转换
   （单引号/注释/尾逗号/\\u{XXXX}/未引号 key）。
   回退结果会在本机与 Node 输出做一致性自检（--force-python 强制走回退路径）。

数据来源（全部位于 static/app.js）：
- COMPONENT_DEFS（254-734 行）：组件定义，render: renderXxxPanel 引用 →
  renderKey 字符串（render 字段是函数引用或工厂调用，取 render\\w+ 函数名）。
- TOOL_NAME_MAP（129-155 行）：组件类型 → 工具名列表。
- COMPONENT_CATEGORIES（1119-1184 行）：组件类型 → [分类名, css 类]。
- AGENT_PRESETS（5849-6147 行）：快速模板布局数据（name/description/components/connections），
  与 templates/index.html 的"⭐ 快速模板"按钮（data-preset）一一对应。
- API_PROVIDERS（8351-8361 行）：getAllProviders() 的静态 return 数组
  （getAllProviders 本身 return [...API_PROVIDERS, ...loadCustomProviders()]，
  loadCustomProviders 是 localStorage 运行时数据，不可静态提取，故取静态部分）。

用法：
    python tools/extract_meta.py [--force-python]
"""
import json
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "static" / "app.js"
INDEX = ROOT / "templates" / "index.html"
OUT = ROOT / "modules" / "meta.py"
SCRATCH_DIR = ROOT / "data" / "vector_store" / ".test_tmp"

RENDER_RE = re.compile(r"render\s*:\s*(render\w+)(\([^)]*\))?")

META_HEADER = '''"""前端元数据单一来源：组件定义/工具映射/分类/模板/厂商预设

本文件由 tools/extract_meta.py 从 static/app.js 自动生成，请勿手改。
"""
from flask import jsonify

'''

META_ROUTES = '''

def register_routes(app):
    @app.route("/api/meta/components", methods=["GET"])
    def meta_components():
        return jsonify({"success": True, "data": _DATA})
'''


# ---------------------------------------------------------------------------
# 括号配对提取（跳过字符串/注释，支持 ' " ` 与 // /* */）
# ---------------------------------------------------------------------------
def find_literal_span(src, start):
    """从 start（'[' 或 '{' 下标）开始括号配对，返回 (start, end) 闭区间含边界。"""
    open_ch = src[start]
    close_ch = "}" if open_ch == "{" else "]"
    depth = 0
    i = start
    n = len(src)
    while i < n:
        ch = src[i]
        if ch in "'\"`":
            q = ch
            i += 1
            while i < n:
                if src[i] == "\\":
                    i += 2
                    continue
                if src[i] == q:
                    break
                i += 1
        elif ch == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                i += 1
        elif ch == "/" and i + 1 < n and src[i + 1] == "*":
            i += 2
            while i + 1 < n and not (src[i] == "*" and src[i + 1] == "/"):
                i += 1
            i += 2
        else:
            if ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth == 0:
                    return start, i
        i += 1
    raise ValueError("括号未配对: %r" % src[start:start + 40])


def extract_literal(src, name):
    """提取 `const NAME = <对象/数组字面量>` 的源文本。"""
    m = re.search(r"\bconst\s+" + re.escape(name) + r"\s*=\s*([\[{])", src)
    if not m:
        raise ValueError("未找到 const %s =" % name)
    start, end = find_literal_span(src, m.start(1))
    return src[start:end + 1]


# ---------------------------------------------------------------------------
# Node.js 求值（文件 IO 传递，避免 piped stdio 的沙箱限制）
# ---------------------------------------------------------------------------
def eval_js_node(text):
    tmp_dir = SCRATCH_DIR
    tmp_dir.mkdir(parents=True, exist_ok=True)
    in_file = tmp_dir / (uuid.uuid4().hex + ".in.js")
    out_file = tmp_dir / (uuid.uuid4().hex + ".out.json")
    err_file = tmp_dir / (uuid.uuid4().hex + ".err.txt")
    try:
        in_file.write_text(text, encoding="utf-8")
        code = (
            "const fs=require('fs');"
            "const s=fs.readFileSync(" + json.dumps(str(in_file)) + ",'utf8');"
            "let v;try{v=eval('('+s+')');}"
            "catch(e){fs.writeFileSync(" + json.dumps(str(err_file)) + ",String(e&&e.stack||e));process.exit(1);}"
            "fs.writeFileSync(" + json.dumps(str(out_file)) + ",JSON.stringify(v));"
        )
        proc = subprocess.run(["node", "-e", code])
        if proc.returncode != 0:
            detail = err_file.read_text(encoding="utf-8") if err_file.exists() else "rc=%s" % proc.returncode
            raise RuntimeError("node 求值失败: %s" % detail[:800])
        if not out_file.exists():
            raise RuntimeError("node 未产出输出文件")
        return json.loads(out_file.read_text(encoding="utf-8"))
    finally:
        for f in (in_file, out_file, err_file):
            try:
                f.unlink()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Python 回退：JS→JSON 兼容子集转换 + json.loads
# ---------------------------------------------------------------------------
def _unicode_brace(m):
    cp = int(m.group(1), 16)
    if cp < 0x10000:
        return "\\u%04x" % cp
    cp -= 0x10000
    return "\\u%04x\\u%04x" % (0xD800 + (cp >> 10), 0xDC00 + (cp & 0x3FF))


def js_to_json(text):
    """JS 对象/数组字面量 → JSON 文本（兼容子集：单引号/注释/尾逗号/\\u{...}/未引号 key）。"""
    text = re.sub(r"\\u\{([0-9a-fA-F]+)\}", _unicode_brace, text)
    out = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        if ch in "'\"":
            q = ch
            out.append('"')
            i += 1
            while i < n:
                c = text[i]
                if c == "\\" and i + 1 < n:
                    nxt = text[i + 1]
                    if nxt == "'":
                        out.append("'")
                    elif nxt == '"':
                        out.append('\\"')
                    elif nxt == "u":
                        out.append("\\u")
                        i += 2
                        start_hex = i
                        while i < n and text[i] in "0123456789abcdefABCDEF":
                            i += 1
                        if i - start_hex != 4:
                            raise ValueError("非法 \\u 转义: %r" % text[start_hex - 2:i])
                        out.append(text[start_hex:i])
                        continue
                    else:
                        out.append("\\" + nxt)
                    i += 2
                    continue
                if c == q:
                    break
                if q == "'" and c == '"':
                    out.append('\\"')  # 单引号串内的 ASCII 双引号需转义
                else:
                    out.append(c)
                i += 1
            out.append('"')
            i += 1
            continue
        m = re.match(r"([A-Za-z_$][A-Za-z0-9_$]*)\s*:", text[i:])
        if m and (i == 0 or text[i - 1] in " \t\r\n,{"):
            out.append('"%s":' % m.group(1))
            i += m.end()
            continue
        if ch == ",":
            j = i + 1
            while j < n:
                c = text[j]
                if c in " \t\r\n":
                    j += 1
                elif c == "/" and j + 1 < n and text[j + 1] == "/":
                    while j < n and text[j] != "\n":
                        j += 1
                elif c == "/" and j + 1 < n and text[j + 1] == "*":
                    j += 2
                    while j + 1 < n and not (text[j] == "*" and text[j + 1] == "/"):
                        j += 1
                    j += 2
                else:
                    break
            if j < n and text[j] in "}]":
                i += 1
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def eval_js_python(text):
    return json.loads(js_to_json(text))


# ---------------------------------------------------------------------------
# 数据结构组装
# ---------------------------------------------------------------------------
def build_component_defs(defs, cats):
    out = {}
    for t, d in defs.items():
        dd = dict(d)
        dd.setdefault("category", list(cats.get(t, ["未分类", "cat-other"])))
        out[t] = dd
    return out


def build_quick_templates(presets):
    out = []
    for key, p in presets.items():
        out.append({
            "key": key,
            "name": p.get("name", key),
            "description": p.get("description", ""),
            "components": p.get("components", []),
            "connections": p.get("connections", []),
        })
    return out


def index_html_preset_keys():
    """index.html 预设按钮 data-preset 集合（用于交叉校验）。"""
    html = INDEX.read_text(encoding="utf-8")
    return set(re.findall(r'data-preset="([^"]+)"', html))


_JSON_BOOL_NULL_RE = re.compile(r'": (true|false|null)([ \t\r\n]*[,}\]])')
_PY_LIT = {"true": "True", "false": "False", "null": "None"}


def _json_to_python_literals(body):
    """JSON 布尔/null 字面量 → Python 字面量（仅匹配 key 后的值位置，不误伤字符串内容）。"""
    return _JSON_BOOL_NULL_RE.sub(lambda m: '": ' + _PY_LIT[m.group(1)] + m.group(2), body)


def main():
    use_node = shutil.which("node") is not None and "--force-python" not in sys.argv
    eval_fn = eval_js_node if use_node else eval_js_python

    src = APP_JS.read_text(encoding="utf-8")

    # COMPONENT_DEFS：render 引用/工厂调用 → renderKey 字符串
    defs_src = extract_literal(src, "COMPONENT_DEFS")
    defs_src = RENDER_RE.sub(lambda m: 'renderKey: "%s"' % m.group(1), defs_src)
    leftover = re.findall(r"render\s*:", defs_src)
    if leftover:
        raise RuntimeError("COMPONENT_DEFS 中仍有未转换的 render: 字段 %d 处" % len(leftover))

    defs = eval_fn(defs_src)
    tools = eval_fn(extract_literal(src, "TOOL_NAME_MAP"))
    cats = eval_fn(extract_literal(src, "COMPONENT_CATEGORIES"))
    presets = eval_fn(extract_literal(src, "AGENT_PRESETS"))
    providers = eval_fn(extract_literal(src, "API_PROVIDERS"))

    # 回退解析一致性自检（本机有 node 时）
    if use_node:
        for label, txt in (
            ("component_defs", defs_src),
            ("tool_name_map", extract_literal(src, "TOOL_NAME_MAP")),
            ("component_categories", extract_literal(src, "COMPONENT_CATEGORIES")),
            ("quick_templates", extract_literal(src, "AGENT_PRESETS")),
            ("provider_presets", extract_literal(src, "API_PROVIDERS")),
        ):
            try:
                py_val = eval_js_python(txt)
                ok = py_val == (defs if label == "component_defs" else
                                tools if label == "tool_name_map" else
                                cats if label == "component_categories" else
                                presets if label == "quick_templates" else providers)
                print("  [自检] %s: Python回退 %s Node" % (label, "一致" if ok else "不一致!"))
                if not ok:
                    print("  [警告] %s 回退解析与 Node 不一致，采用 Node 结果" % label)
            except Exception as e:  # noqa: BLE001
                print("  [警告] %s 回退解析失败（采用 Node 结果）: %s" % (label, e))

    defs_out = build_component_defs(defs, cats)
    templates = build_quick_templates(presets)

    data = {
        "component_defs": defs_out,
        "tool_name_map": tools,
        "component_categories": cats,
        "quick_templates": templates,
        "provider_presets": providers,
    }
    body = json.dumps(data, ensure_ascii=False, indent=2)
    body = _json_to_python_literals(body)
    OUT.write_text(META_HEADER + "_DATA = " + body + META_ROUTES, encoding="utf-8")

    render_keys = sorted({d["renderKey"] for d in defs.values()})
    html_presets = index_html_preset_keys()
    js_presets = set(presets.keys())
    missing_cat = sorted(t for t in defs if t not in cats)

    print("提取方法: %s" % ("Node.js" if use_node else "Python 回退"))
    print("component_defs: %d 个组件" % len(defs_out))
    print("  renderKey 不同函数名: %d 个（验收要求 39）" % len(render_keys))
    print("  缺 COMPONENT_CATEGORIES 条目: %s" % (missing_cat or "无"))
    print("tool_name_map: %d 条" % len(tools))
    print("component_categories: %d 条" % len(cats))
    print("quick_templates: %d 个（index.html 按钮 %d 个，JS %d 个，差异: %s）" % (
        len(templates), len(html_presets), len(js_presets),
        sorted(html_presets ^ js_presets) or "无"))
    print("provider_presets: %d 个" % len(providers))
    print("已生成: %s" % OUT)


if __name__ == "__main__":
    main()
