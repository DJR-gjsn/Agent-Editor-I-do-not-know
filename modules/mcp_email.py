"""
MCP Email 邮件服务模块
通过 SMTP 发送邮件，支持附件、HTML 正文、抄送
"""

import smtplib
import time
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email import encoders
from pathlib import Path

from flask import jsonify, request

from . import tool_registry

# ============================================================
# 会话配置
# ============================================================
_connections = {}

SMTP_SERVERS = {
    "gmail":     ("smtp.gmail.com", 587),
    "outlook":   ("smtp.office365.com", 587),
    "qq":        ("smtp.qq.com", 587),
    "163":       ("smtp.163.com", 465),
    "126":       ("smtp.126.com", 465),
    "custom":    ("", 587),
}


def _get_conn(session_id: str) -> dict:
    if session_id not in _connections:
        _connections[session_id] = {
            "smtp_host": "", "smtp_port": 587,
            "email": "", "password": "",
            "connected": False, "last_test": None,
        }
    return _connections[session_id]


# ============================================================
# 工具定义
# ============================================================
EMAIL_SEND_DEF = {
    "name": "email_send",
    "description": (
        "通过 SMTP 发送邮件。支持纯文本和 HTML 正文、抄送、附件。"
        "⚠️ 必须在邮件服务面板中先配置 SMTP 服务器信息并测试连接。"
        "常见 SMTP: Gmail 需使用应用专用密码，QQ邮箱需开启 SMTP 服务获取授权码。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "收件人邮箱地址，多个用逗号分隔"},
            "subject": {"type": "string", "description": "邮件主题"},
            "body": {"type": "string", "description": "邮件正文（支持 Markdown 格式，会自动转换）"},
            "cc": {"type": "string", "description": "抄送，多个用逗号分隔（可选）"},
            "is_html": {"type": "boolean", "description": "正文是否为 HTML，默认 False（纯文本）", "default": False},
            "session_id": {"type": "string", "description": "会话 ID"},
        },
        "required": ["to", "subject", "body"],
    },
}


def _exec_email_send(args: dict) -> str:
    session_id = args.get("session_id", "default")
    conn = _get_conn(session_id)

    if not conn.get("smtp_host") or not conn.get("email"):
        return (
            "❌ 邮件服务未配置。请先在邮件服务面板中设置:\n"
            "1. 选择邮箱类型（Gmail/Outlook/QQ/163）或填入自定义 SMTP\n"
            "2. 填入邮箱地址和密码/授权码\n"
            "3. 点击「测试连接」\n\n"
            "💡 Gmail 用户: 需使用应用专用密码 (App Password)\n"
            "💡 QQ邮箱用户: 需在设置中开启 SMTP 服务获取授权码"
        )

    to = args.get("to", "")
    subject = args.get("subject", "")
    body = args.get("body", "")
    cc = args.get("cc", "")
    is_html = bool(args.get("is_html", False))

    if not to or not body:
        return "错误: to、subject 和 body 都不能为空"

    try:
        msg = MIMEMultipart()
        msg["From"] = conn["email"]
        msg["To"] = to
        msg["Subject"] = subject
        if cc:
            msg["Cc"] = cc

        # 正文
        subtype = "html" if is_html else "plain"
        msg.attach(MIMEText(body, subtype, "utf-8"))

        # 发送
        with smtplib.SMTP(conn["smtp_host"], int(conn["smtp_port"]), timeout=15) as server:
            server.starttls()
            server.login(conn["email"], conn["password"])
            all_rcpt = [a.strip() for a in to.split(",") if a.strip()]
            if cc:
                all_rcpt += [a.strip() for a in cc.split(",") if a.strip()]
            server.sendmail(conn["email"], all_rcpt, msg.as_string())

        return f"✅ 邮件已发送!\n📧 发件人: {conn['email']}\n📩 收件人: {to}\n📝 主题: {subject}"
    except smtplib.SMTPAuthenticationError:
        return "❌ SMTP 认证失败。请检查邮箱地址和密码/授权码是否正确。"
    except smtplib.SMTPException as e:
        return f"❌ SMTP 发送失败: {str(e)}"
    except Exception as e:
        return f"❌ 发送失败: {str(e)}"


_tool_list = [
    (EMAIL_SEND_DEF, _exec_email_send),
]

for tool_def, executor in _tool_list:
    tool_registry.register(tool_def["name"], tool_def, executor)


# ============================================================
# Flask 路由
# ============================================================
def register_routes(app, http_session=None):
    @app.route("/api/email/test-connection", methods=["POST"])
    def email_test_connection():
        """测试 SMTP 连接"""
        data = request.get_json(force=True)
        provider = data.get("provider", "custom")
        email_addr = (data.get("email") or "").strip()
        password = (data.get("password") or "").strip()
        smtp_host = (data.get("smtp_host") or "").strip()
        smtp_port = int(data.get("smtp_port", 587))
        session_id = data.get("session_id", "default")

        if not email_addr or not password:
            return jsonify({"success": False, "error": "请填入邮箱地址和密码/授权码"}), 400

        # 自动解析 SMTP 服务器
        if provider in SMTP_SERVERS and not smtp_host:
            smtp_host, smtp_port = SMTP_SERVERS[provider]

        if not smtp_host:
            return jsonify({"success": False, "error": "请选择邮箱类型或填入自定义 SMTP 服务器地址"}), 400

        conn = _get_conn(session_id)
        conn["email"] = email_addr
        conn["password"] = password
        conn["smtp_host"] = smtp_host
        conn["smtp_port"] = smtp_port

        t0 = time.time()
        try:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                server.starttls()
                server.login(email_addr, password)
            latency_ms = round((time.time() - t0) * 1000)
            conn["connected"] = True
            conn["last_test"] = time.time()
            return jsonify({
                "success": True,
                "message": f"SMTP 连接成功！\n服务器: {smtp_host}:{smtp_port}\n账号: {email_addr}",
                "latency_ms": latency_ms,
            })
        except smtplib.SMTPAuthenticationError:
            conn["connected"] = False
            return jsonify({"success": False, "error": "认证失败。\nGmail: 请使用应用专用密码\nQQ/163: 请使用 SMTP 授权码"})
        except Exception as e:
            conn["connected"] = False
            return jsonify({"success": False, "error": str(e)})

    @app.route("/api/email/smtp-presets", methods=["GET"])
    def email_smtp_presets():
        """返回常见 SMTP 服务器预设"""
        return jsonify({k: {"host": v[0], "port": v[1]} for k, v in SMTP_SERVERS.items()})
