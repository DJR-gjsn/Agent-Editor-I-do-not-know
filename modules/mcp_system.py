"""
MCP System 系统与网络工具模块
提供系统信息、DNS 查询、二维码、桌面通知、打开文件等工具
"""

import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path

from flask import jsonify, request, send_file

from . import tool_registry

# ============================================================
# 1. system_info
# ============================================================
SYSINFO_DEF = {
    "name": "system_info",
    "description": "获取系统信息：CPU 使用率、内存、磁盘空间、系统运行时间。",
    "parameters": {
        "type": "object",
        "properties": {
            "detail": {
                "type": "string",
                "enum": ["summary", "cpu", "memory", "disk"],
                "description": "信息类型: summary=概览(默认), cpu=CPU, memory=内存, disk=磁盘",
                "default": "summary",
            },
        },
        "required": [],
    },
}


def _exec_sysinfo(args: dict) -> str:
    detail = args.get("detail", "summary")
    lines = ["💻 系统信息:"]

    try:
        import psutil
    except ImportError:
        return _exec_sysinfo_fallback(detail)

    if detail in ("summary", "cpu"):
        cpu_pct = psutil.cpu_percent(interval=0.5)
        cpu_count = psutil.cpu_count()
        lines.append(f"🖥️ CPU: {cpu_pct}% (核心数: {cpu_count})")

    if detail in ("summary", "memory"):
        mem = psutil.virtual_memory()
        lines.append(f"🧠 内存: {_fmt_bytes(mem.used)} / {_fmt_bytes(mem.total)} ({mem.percent}%)")

    if detail in ("summary", "disk"):
        for part in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(part.mountpoint)
                lines.append(f"💾 {part.mountpoint}: {_fmt_bytes(usage.used)} / {_fmt_bytes(usage.total)} ({usage.percent}%)")
            except Exception:
                pass

    try:
        boot = psutil.boot_time()
        uptime = time.time() - boot
        h, m = divmod(int(uptime), 3600)
        m, s = divmod(m, 60)
        lines.append(f"⏱️ 运行时间: {h}小时{m}分钟")
    except Exception:
        pass

    return "\n".join(lines)


def _exec_sysinfo_fallback(detail: str) -> str:
    """无 psutil 时的回退方案"""
    lines = ["💻 系统信息 (基础模式):"]

    try:
        result = subprocess.run(["wmic", "cpu", "get", "loadpercentage"], capture_output=True, text=True, timeout=5)
        nums = [int(s) for s in result.stdout.split() if s.isdigit()]
        if nums:
            lines.append(f"🖥️ CPU: {nums[0]}%")
    except Exception:
        pass

    try:
        result = subprocess.run(["wmic", "OS", "get", "TotalVisibleMemorySize,FreePhysicalMemory"], capture_output=True, text=True, timeout=5)
        lines.append(f"🧠 内存: {result.stdout.strip()[:200]}")
    except Exception:
        pass

    try:
        result = subprocess.run(["wmic", "logicaldisk", "get", "size,freespace,caption"], capture_output=True, text=True, timeout=5)
        lines.append(f"💾 磁盘: {result.stdout.strip()[:300]}")
    except Exception:
        pass

    lines.append("\n💡 安装 psutil 获得更详细的信息: pip install psutil")
    return "\n".join(lines)


def _fmt_bytes(b: int) -> str:
    for u in ["B", "KB", "MB", "GB", "TB"]:
        if b < 1024:
            return f"{b:.1f} {u}"
        b /= 1024
    return f"{b:.1f} PB"


# ============================================================
# 2. dns_lookup
# ============================================================
DNS_DEF = {
    "name": "dns_lookup",
    "description": "DNS 查询：解析域名到 IP 地址（A/AAAA），查询 MX/NS/TXT 记录。",
    "parameters": {
        "type": "object",
        "properties": {
            "domain": {"type": "string", "description": "域名，如 'google.com'"},
            "record_type": {
                "type": "string",
                "enum": ["A", "AAAA", "MX", "NS", "TXT", "ALL"],
                "description": "DNS 记录类型，默认 A（IPv4 地址）",
                "default": "A",
            },
        },
        "required": ["domain"],
    },
}


def _exec_dns(args: dict) -> str:
    domain = (args.get("domain") or "").strip()
    rtype = args.get("record_type", "A")
    if not domain:
        return "错误: domain 不能为空"

    results = []
    try:
        if rtype in ("A", "ALL"):
            ips = socket.getaddrinfo(domain, None, socket.AF_INET)
            for ip in ips:
                results.append(f"  A (IPv4): {ip[4][0]}")
        if rtype in ("AAAA", "ALL"):
            try:
                ips = socket.getaddrinfo(domain, None, socket.AF_INET6)
                for ip in ips:
                    results.append(f"  AAAA (IPv6): {ip[4][0]}")
            except Exception:
                results.append("  AAAA (IPv6): 无")
    except socket.gaierror as e:
        return f"❌ DNS 查询失败: {e}"

    # 别名
    try:
        canon = socket.getaddrinfo(domain, None, socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, socket.AI_CANONNAME)
        if canon and canon[0][3]:
            results.append(f"  规范名: {canon[0][3]}")
    except Exception:
        pass

    # MX 记录
    if rtype in ("MX", "ALL"):
        try:
            import dns.resolver
            answers = dns.resolver.resolve(domain, "MX")
            for a in answers:
                results.append(f"  MX: {a.exchange} (优先级 {a.preference})")
        except ImportError:
            results.append("  MX: 需要安装 dnspython: pip install dnspython")
        except Exception as e:
            results.append(f"  MX: 查询失败 ({e})")

    if not results:
        return f"未找到域名 '{domain}' 的 {rtype} 记录。"
    return f"🌐 DNS 查询: {domain}\n" + "\n".join(results)


# ============================================================
# 3. qr_generate
# ============================================================
QR_DEF = {
    "name": "qr_generate",
    "description": "根据文本或 URL 生成二维码图片，保存为 PNG 文件。",
    "parameters": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "要编码为二维码的文本或 URL"},
            "filename": {"type": "string", "description": "输出文件名（不含扩展名），默认 'qrcode'", "default": "qrcode"},
        },
        "required": ["text"],
    },
}


def _exec_qr(args: dict) -> str:
    text = args.get("text", "")
    filename = args.get("filename", "qrcode")
    if not text:
        return "错误: text 不能为空"

    out_dir = Path(tempfile.gettempdir()) / "mcp_qrcodes"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{filename}.png"

    try:
        import qrcode
        qr = qrcode.QRCode(box_size=10, border=4)
        qr.add_data(text)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        img.save(str(out_path))
        return f"✅ 二维码已生成: {out_path}\n📏 内容: {text[:50]}{'...' if len(text) > 50 else ''}"
    except ImportError:
        return "❌ 需要安装 qrcode 库: pip install qrcode Pillow"
    except Exception as e:
        # 文本二维码回退
        return _text_qr(text)


def _text_qr(text: str) -> str:
    """简易文本二维码"""
    qr_chars = " ▀▄█"
    h = hash(text) % 0xFFFF
    lines = ["📱 文本二维码 (基础):"]
    for i in range(21):
        row = []
        for j in range(21):
            v = (h >> ((i * j) % 16)) & 1
            row.append("██" if v else "  ")
        lines.append("".join(row))
    lines.append(f"内容: {text[:50]}")
    lines.append("💡 安装 qrcode 库生成真实二维码: pip install qrcode Pillow")
    return "\n".join(lines)


# ============================================================
# 4. open_file
# ============================================================
OPENFILE_DEF = {
    "name": "open_file",
    "description": "用系统默认程序打开文件或文件夹。支持打开文档、图片、网址、文件夹等。",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件或文件夹路径，或 URL"},
        },
        "required": ["path"],
    },
}


def _exec_openfile(args: dict) -> str:
    path = (args.get("path") or "").strip()
    if not path:
        return "错误: path 不能为空"

    try:
        if os.name == "nt":
            os.startfile(path)
        else:
            subprocess.run(["xdg-open", path])
        p = Path(path)
        what = "文件夹" if p.is_dir() else "网址" if path.startswith("http") else "文件"
        return f"✅ 已打开{what}: {path}"
    except FileNotFoundError:
        return f"❌ 文件不存在: {path}"
    except Exception as e:
        return f"❌ 打开失败: {str(e)}"


# ============================================================
# 5. desktop_notify
# ============================================================
NOTIFY_DEF = {
    "name": "desktop_notify",
    "description": "发送桌面通知。用于提醒、任务完成提示等。",
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "通知标题"},
            "message": {"type": "string", "description": "通知正文"},
            "duration": {"type": "integer", "description": "显示秒数，默认 5", "default": 5},
        },
        "required": ["title", "message"],
    },
}


def _exec_notify(args: dict) -> str:
    title = args.get("title", "通知")
    message = args.get("message", "")
    duration = int(args.get("duration", 5))

    # Windows toast
    if os.name == "nt":
        try:
            from win10toast import ToastNotifier
            toaster = ToastNotifier()
            toaster.show_toast(title, message, duration=duration, threaded=True)
            return f"✅ 已发送桌面通知: {title}"
        except ImportError:
            pass
        # PowerShell fallback — 用 CREATE_NO_WINDOW 后台运行，不阻塞
        try:
            subprocess.Popen(
                ["powershell", "-Command",
                 f"Add-Type -AssemblyName System.Windows.Forms; "
                 f"$n = New-Object System.Windows.Forms.NotifyIcon; "
                 f"$n.Icon = [System.Drawing.SystemIcons]::Information; "
                 f"$n.BalloonTipTitle = '{title}'; "
                 f"$n.BalloonTipText = '{message}'; "
                 f"$n.Visible = $true; "
                 f"$n.ShowBalloonTip({duration * 1000}); "
                 f"Start-Sleep -Seconds {duration}; "
                 f"$n.Dispose()"],
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
            return f"✅ 已发送桌面通知: {title}"
        except Exception:
            return f"⚠️ 通知已记录（桌面通知模块未安装）:\n📌 {title}: {message}\n💡 安装: pip install plyer"
    else:
        try:
            subprocess.run(["notify-send", title, message, "-t", str(duration * 1000)], timeout=5)
            return f"✅ 已发送桌面通知: {title}"
        except Exception:
            return f"⚠️ 通知已记录:\n📌 {title}: {message}"


# ============================================================
# 注册所有工具
# ============================================================
_tool_list = [
    (SYSINFO_DEF, _exec_sysinfo),
    (DNS_DEF, _exec_dns),
    (QR_DEF, _exec_qr),
    (OPENFILE_DEF, _exec_openfile),
    (NOTIFY_DEF, _exec_notify),
]

for tool_def, executor in _tool_list:
    tool_registry.register(tool_def["name"], tool_def, executor)


# ============================================================
# Flask 路由
# ============================================================
def register_routes(app, http_session=None):
    @app.route("/api/system/test-connection", methods=["POST"])
    def system_test_connection():
        """测试系统模块可用性"""
        checks = {}
        for mod in ["psutil", "qrcode", "PIL"]:
            try:
                __import__(mod)
                checks[mod] = "可用"
            except ImportError:
                checks[mod] = "未安装"

        return jsonify({
            "success": True,
            "message": f"系统工具模块就绪（{len(_tool_list)} 个工具）",
            "modules": checks,
            "platform": os.name,
            "hostname": socket.gethostname(),
        })

    @app.route("/api/system/qrcode/<filename>")
    def system_qrcode_download(filename):
        """下载生成的二维码图片"""
        out_dir = Path(tempfile.gettempdir()) / "mcp_qrcodes"
        filepath = out_dir / f"{filename}.png"
        if filepath.exists():
            return send_file(str(filepath), mimetype="image/png")
        return jsonify({"error": "文件不存在"}), 404
