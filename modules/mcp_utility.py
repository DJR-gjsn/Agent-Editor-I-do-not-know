"""
mcp_utility — 通用工具集模块
========================================
提供 8 个高频通用工具（全部基于标准库或已安装依赖，零新增依赖）:

- zip_create / zip_extract     文件压缩 / 解压（zipfile，zip-slip 防护）
- http_request                 通用 HTTP 请求（GET/POST/PUT/PATCH/DELETE）
- screenshot                   截取屏幕（Pillow，Windows 原生支持）
- image_info / image_convert / image_resize / image_compress
                               图片信息 / 格式转换 / 缩放 / 压缩

所有文件路径均经 utils.safe_path 限制在共享工作区内，防止目录穿越。
"""

import glob as _glob
import io
import json
import os
import time
import zipfile
from pathlib import Path

import requests
from flask import jsonify, request

from . import tool_registry
from .utils import WORKSPACE, get_logger, safe_path

logger = get_logger("wybzd")

# ============================================================
# 工具定义
# ============================================================

ZIP_CREATE_DEF = {
    "name": "zip_create",
    "description": (
        "把文件或目录压缩成一个 zip 压缩包。files 支持多个文件路径，"
        "也支持 glob 通配符（如 *.txt、data/**）。路径相对共享工作区。"
        "适合批量打包交付文件。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "zip_path": {"type": "string", "description": "zip 输出文件名（如 report.zip）"},
            "files": {
                "type": "array", "items": {"type": "string"},
                "description": "要压缩的文件路径或 glob 模式列表",
            },
        },
        "required": ["zip_path", "files"],
    },
}

ZIP_EXTRACT_DEF = {
    "name": "zip_extract",
    "description": "解压 zip 压缩包到指定目录（默认工作区根目录）。自动防护 zip-slip 路径穿越。",
    "parameters": {
        "type": "object",
        "properties": {
            "zip_path": {"type": "string", "description": "zip 文件路径"},
            "dest_dir": {"type": "string", "description": "解压目标目录（相对工作区），默认工作区根"},
        },
        "required": ["zip_path"],
    },
}

HTTP_REQUEST_DEF = {
    "name": "http_request",
    "description": (
        "发送通用 HTTP 请求。支持 GET/POST/PUT/PATCH/DELETE，可携带 JSON 请求体、"
        "自定义请求头和查询参数。响应返回状态码、响应头和响应体（截断到 5000 字符）。"
        "适合调用第三方 API、查询接口、测试 Webhook 等。超时上限 30 秒。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "method": {
                "type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
                "description": "HTTP 方法，默认 GET",
            },
            "url": {"type": "string", "description": "请求 URL"},
            "headers": {
                "type": "object", "description": "自定义请求头（可选）",
            },
            "json_body": {
                "description": "JSON 请求体（对象或字符串，可选；POST/PUT 常用）",
            },
            "params": {
                "type": "object", "description": "URL 查询参数（可选）",
            },
            "timeout": {
                "type": "number", "description": "超时秒数，默认 15，最大 30",
            },
        },
        "required": ["url"],
    },
}

SCREENSHOT_DEF = {
    "name": "screenshot",
    "description": (
        "截取当前屏幕并保存为 PNG 图片（Windows 桌面环境）。"
        "文件保存到共享工作区，返回文件路径。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "filename": {"type": "string", "description": "输出文件名（可选，默认 screenshot_时间戳.png）"},
        },
    },
}

IMAGE_INFO_DEF = {
    "name": "image_info",
    "description": "获取图片信息：格式、宽高、色彩模式、文件大小。",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "图片文件路径（相对工作区）"},
        },
        "required": ["path"],
    },
}

IMAGE_CONVERT_DEF = {
    "name": "image_convert",
    "description": "转换图片格式（png/jpeg/webp）。输出文件默认与原文件同名的目标格式。",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "源图片路径（相对工作区）"},
            "target_format": {
                "type": "string", "enum": ["png", "jpeg", "webp"],
                "description": "目标格式",
            },
            "output_path": {"type": "string", "description": "输出路径（可选，默认同名换扩展名）"},
        },
        "required": ["path", "target_format"],
    },
}

IMAGE_RESIZE_DEF = {
    "name": "image_resize",
    "description": "缩放图片。指定宽度或高度（只给一个时按比例缩放，两个都给时强制拉伸）。",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "源图片路径（相对工作区）"},
            "width": {"type": "integer", "description": "目标宽度（像素）"},
            "height": {"type": "integer", "description": "目标高度（像素）"},
            "output_path": {"type": "string", "description": "输出路径（可选，默认 原名_resized 后缀）"},
        },
        "required": ["path"],
    },
}

IMAGE_COMPRESS_DEF = {
    "name": "image_compress",
    "description": "压缩图片（JPEG/WebP 质量压缩）。quality 越小体积越小。",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "源图片路径（相对工作区）"},
            "quality": {"type": "integer", "description": "压缩质量 1-95，默认 80"},
            "output_path": {"type": "string", "description": "输出路径（可选，默认 原名_compressed 后缀）"},
        },
        "required": ["path"],
    },
}

# ============================================================
# 工具执行
# ============================================================

def _fmt_size(n: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _exec_zip_create(args: dict) -> str:
    zip_path = safe_path(str(args.get("zip_path", "")))
    patterns = args.get("files") or []
    if not patterns:
        return "错误：请提供要压缩的文件列表"
    if zip_path.exists():
        return f"错误：输出文件已存在: {zip_path.name}"

    matched = []
    for p in patterns:
        p = str(p)
        # 支持绝对路径或相对工作区
        cand = Path(p) if os.path.isabs(p) else WORKSPACE / p
        hits = _glob.glob(str(cand), recursive=True) if any(ch in p for ch in "*?[") else ([str(cand)] if cand.exists() else [])
        for h in hits:
            hp = safe_path(h)
            if hp.is_file() and hp not in matched:
                matched.append(hp)

    if not matched:
        return "错误：没有匹配到任何文件"
    try:
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        total = 0
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for fp in matched:
                arcname = fp.name
                zf.write(fp, arcname)
                count += 1
                total += fp.stat().st_size
        return f"✅ 已创建 {zip_path.name}：{count} 个文件，原始大小 {_fmt_size(total)}，压缩包 {_fmt_size(zip_path.stat().st_size)}"
    except Exception as e:
        return f"错误：压缩失败: {e}"


def _exec_zip_extract(args: dict) -> str:
    zip_path = safe_path(str(args.get("zip_path", "")))
    if not zip_path.exists():
        return f"错误：zip 文件不存在: {zip_path.name}"
    dest = safe_path(str(args.get("dest_dir", ""))) if args.get("dest_dir") else WORKSPACE
    dest.mkdir(parents=True, exist_ok=True)
    dest_resolved = dest.resolve()

    count = 0
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for member in zf.infolist():
                # zip-slip 防护：成员路径必须落在目标目录内
                target = (dest / member.filename).resolve()
                if not str(target).startswith(str(dest_resolved)):
                    return f"错误：zip 包含非法路径，已中止解压: {member.filename}"
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, open(target, "wb") as dst:
                    dst.write(src.read())
                count += 1
        return f"✅ 已解压 {count} 个文件到 {dest.name or '工作区根目录'}"
    except zipfile.BadZipFile:
        return "错误：无效的 zip 文件"
    except Exception as e:
        return f"错误：解压失败: {e}"


def _exec_http_request(args: dict) -> str:
    method = str(args.get("method", "GET")).upper()
    url = str(args.get("url", "")).strip()
    if not url:
        return "错误：请提供 URL"
    if not url.startswith(("http://", "https://")):
        return "错误：URL 必须以 http:// 或 https:// 开头"
    try:
        timeout = min(float(args.get("timeout", 15)), 30.0)
    except (TypeError, ValueError):
        timeout = 15.0

    headers = args.get("headers") or {}
    params = args.get("params") or {}
    json_body = args.get("json_body")
    if isinstance(json_body, str):
        try:
            json_body = json.loads(json_body)
        except json.JSONDecodeError:
            return "错误：json_body 不是合法的 JSON"

    try:
        t0 = time.time()
        resp = requests.request(
            method, url, headers=headers, params=params, json=json_body, timeout=timeout,
        )
        elapsed = round(time.time() - t0, 2)
        body = resp.text[:5000]
        # 响应头只保留常用项，避免过长
        hdrs = {k: v for k, v in resp.headers.items() if k.lower() in
                ("content-type", "content-length", "server", "date", "location", "set-cookie")}
        return json.dumps({
            "status": resp.status_code,
            "reason": resp.reason,
            "elapsed_sec": elapsed,
            "headers": hdrs,
            "body": body,
            "truncated": len(resp.text) > 5000,
        }, ensure_ascii=False, indent=2)
    except requests.exceptions.Timeout:
        return f"错误：请求超时（{timeout}s）"
    except requests.exceptions.ConnectionError:
        return "错误：连接失败，请检查 URL 或网络"
    except Exception as e:
        return f"错误：请求失败: {e}"


def _load_pil():
    try:
        from PIL import Image
        return Image
    except ImportError:
        return None


def _exec_screenshot(args: dict) -> str:
    try:
        from PIL import ImageGrab
    except ImportError:
        return "错误：当前环境不支持截屏（需要 Pillow 的 ImageGrab，仅 Windows 桌面可用）"
    try:
        filename = str(args.get("filename") or f"screenshot_{time.strftime('%Y%m%d_%H%M%S')}.png")
        out = safe_path(filename)
        out.parent.mkdir(parents=True, exist_ok=True)
        img = ImageGrab.grab()
        img.save(out, "PNG")
        return f"✅ 已保存截图: {out.name}（{img.size[0]}x{img.size[1]}, {_fmt_size(out.stat().st_size)}）"
    except Exception as e:
        return f"错误：截屏失败: {e}"


def _open_image(path: str):
    Image = _load_pil()
    if Image is None:
        return None, "错误：Pillow 未安装"
    p = safe_path(path)
    if not p.exists():
        return None, f"错误：图片不存在: {p.name}"
    try:
        return Image.open(p), None
    except Exception as e:
        return None, f"错误：无法打开图片: {e}"


def _default_output(path: Path, suffix: str) -> Path:
    return path.with_name(path.stem + suffix + path.suffix)


def _exec_image_info(args: dict) -> str:
    img, err = _open_image(str(args.get("path", "")))
    if err:
        return err
    p = safe_path(str(args.get("path", "")))
    fmt = img.format or "未知"
    mode = img.mode
    w, h = img.size
    size = _fmt_size(p.stat().st_size)
    img.close()
    return f"📐 {p.name}: {w}x{h}px, 格式={fmt}, 色彩模式={mode}, 大小={size}"


def _exec_image_convert(args: dict) -> str:
    src = str(args.get("path", ""))
    target = str(args.get("target_format", "")).lower()
    if target not in ("png", "jpeg", "webp"):
        return "错误：target_format 仅支持 png/jpeg/webp"
    img, err = _open_image(src)
    if err:
        return err
    sp = safe_path(src)
    try:
        if args.get("output_path"):
            out = safe_path(str(args["output_path"]))
        else:
            out = sp.with_suffix("." + ("jpg" if target == "jpeg" else target))
        out.parent.mkdir(parents=True, exist_ok=True)
        img.save(out, format=target.upper())
        return f"✅ 已转换: {sp.name} → {out.name}（{_fmt_size(out.stat().st_size)}）"
    except Exception as e:
        return f"错误：转换失败: {e}"
    finally:
        img.close()


def _exec_image_resize(args: dict) -> str:
    img, err = _open_image(str(args.get("path", "")))
    if err:
        return err
    sp = safe_path(str(args.get("path", "")))
    try:
        width = args.get("width")
        height = args.get("height")
        if not width and not height:
            return "错误：请至少指定 width 或 height"
        w, h = img.size
        if width and height:
            nw, nh = int(width), int(height)
        elif width:
            nw = int(width)
            nh = max(1, round(h * nw / w))
        else:
            nh = int(height)
            nw = max(1, round(w * nh / h))
        if nw < 1 or nh < 1:
            return "错误：目标尺寸无效"
        resized = img.resize((nw, nh))
        if args.get("output_path"):
            out = safe_path(str(args["output_path"]))
        else:
            out = _default_output(sp, "_resized")
        out.parent.mkdir(parents=True, exist_ok=True)
        resized.save(out)
        return f"✅ 已缩放: {sp.name} → {out.name}（{w}x{h} → {nw}x{nh}, {_fmt_size(out.stat().st_size)}）"
    except Exception as e:
        return f"错误：缩放失败: {e}"
    finally:
        img.close()


def _exec_image_compress(args: dict) -> str:
    img, err = _open_image(str(args.get("path", "")))
    if err:
        return err
    sp = safe_path(str(args.get("path", "")))
    try:
        quality = int(args.get("quality", 80))
        quality = max(1, min(95, quality))
        fmt = (img.format or "JPEG").upper()
        if fmt not in ("JPEG", "WEBP"):
            return "错误：仅支持压缩 JPEG/WebP 图片，请先用 image_convert 转换"
        if args.get("output_path"):
            out = safe_path(str(args["output_path"]))
        else:
            out = _default_output(sp, "_compressed")
        out.parent.mkdir(parents=True, exist_ok=True)
        img.save(out, format=fmt, quality=quality)
        ratio = (1 - out.stat().st_size / sp.stat().st_size) * 100 if sp.stat().st_size else 0
        return f"✅ 已压缩: {sp.name} → {out.name}（{_fmt_size(sp.stat().st_size)} → {_fmt_size(out.stat().st_size)}, 减少 {ratio:.0f}%）"
    except Exception as e:
        return f"错误：压缩失败: {e}"
    finally:
        img.close()


# ============================================================
# 注册
# ============================================================
def register_utility_tools():
    tool_registry.register("zip_create", ZIP_CREATE_DEF, _exec_zip_create)
    tool_registry.register("zip_extract", ZIP_EXTRACT_DEF, _exec_zip_extract)
    tool_registry.register("http_request", HTTP_REQUEST_DEF, _exec_http_request)
    tool_registry.register("screenshot", SCREENSHOT_DEF, _exec_screenshot)
    tool_registry.register("image_info", IMAGE_INFO_DEF, _exec_image_info)
    tool_registry.register("image_convert", IMAGE_CONVERT_DEF, _exec_image_convert)
    tool_registry.register("image_resize", IMAGE_RESIZE_DEF, _exec_image_resize)
    tool_registry.register("image_compress", IMAGE_COMPRESS_DEF, _exec_image_compress)
    logger.info("mcp_utility: 注册 8 个通用工具（zip/http/screenshot/image）")


def register_routes(app, http_session=None):
    """注册直接 API 端点（供前端/外部直接调用同一执行器）"""
    register_utility_tools()

    @app.route("/api/utility/zip", methods=["POST"])
    def utility_zip():
        data = request.get_json(force=True, silent=True) or {}
        if data.get("action") == "extract":
            return jsonify({"success": True, "result": _exec_zip_extract(data)})
        return jsonify({"success": True, "result": _exec_zip_create(data)})

    @app.route("/api/utility/http", methods=["POST"])
    def utility_http():
        data = request.get_json(force=True, silent=True) or {}
        return jsonify({"success": True, "result": _exec_http_request(data)})

    @app.route("/api/utility/image", methods=["POST"])
    def utility_image():
        data = request.get_json(force=True, silent=True) or {}
        action = data.get("action", "info")
        fn = {"info": _exec_image_info, "convert": _exec_image_convert,
              "resize": _exec_image_resize, "compress": _exec_image_compress}.get(action)
        if not fn:
            return jsonify({"success": False, "error": f"未知 action: {action}"}), 400
        return jsonify({"success": True, "result": fn(data)})

    @app.route("/api/utility/screenshot", methods=["POST"])
    def utility_screenshot():
        data = request.get_json(force=True, silent=True) or {}
        return jsonify({"success": True, "result": _exec_screenshot(data)})
