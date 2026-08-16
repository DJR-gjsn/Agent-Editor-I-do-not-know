#!/usr/bin/env python3
"""
LLM 对话窗口 - 通过 API 连接 AI
支持 OpenAI 兼容接口（OpenAI / DeepSeek / 通义千问 / 智谱 等）
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import requests

# ============================================================
# Windows 兼容：尝试导入 readline
# ============================================================
try:
    import readline  # Unix
except ImportError:
    try:
        import pyreadline3 as readline  # Windows (newer)
    except ImportError:
        try:
            import pyreadline as readline  # Windows (older)
        except ImportError:
            readline = None  # 无 readline 支持，功能降级但不崩溃

# ============================================================
# 配置 - 可通过环境变量覆盖
# ============================================================
# 将项目路径加入 sys.path 以使用共享配置模块
_project_root = Path(__file__).parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from modules.config import get_config as _get_config

_cfg = _get_config()
CONFIG = {
    "api_base": os.getenv("LLM_API_BASE", _cfg["api_base"]),
    "api_key": os.getenv("LLM_API_KEY", _cfg["api_key"]),
    "model": os.getenv("LLM_MODEL", _cfg["model"]),
    "max_tokens": int(os.getenv("LLM_MAX_TOKENS", str(_cfg["max_tokens"]))),
    "temperature": float(os.getenv("LLM_TEMPERATURE", str(_cfg["temperature"]))),
    "system_prompt": os.getenv("LLM_SYSTEM_PROMPT", _cfg["system_prompt"]),
}

# 复用 HTTP 连接
http_session = requests.Session()
http_session.headers.update({"Content-Type": "application/json"})

# 历史记录文件
HISTORY_DIR = Path.home() / ".llm_chat"
HISTORY_DIR.mkdir(exist_ok=True)
HISTORY_FILE = HISTORY_DIR / "conversations.json"
INPUT_HISTORY_FILE = HISTORY_DIR / ".input_history"

# 颜色代码（跨平台）
COLORS = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "cyan": "\033[36m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "red": "\033[31m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
}


def color(text: str, c: str) -> str:
    """给文字添加颜色"""
    return f"{COLORS.get(c, '')}{text}{COLORS['reset']}"


def print_banner():
    """打印欢迎横幅"""
    banner = r"""
╔══════════════════════════════════════════════╗
║          🤖  LLM 对话窗口 v1.1              ║
║         通过 API 连接 AI 助手               ║
╚══════════════════════════════════════════════╝
"""
    print(color(banner, "cyan"))
    print(color(f"  模型: {CONFIG['model']}", "dim"))
    print(color(f"  接口: {CONFIG['api_base']}", "dim"))
    print(color("  输入 /help 查看命令 | /exit 退出\n", "dim"))


def print_help():
    """打印帮助信息"""
    help_text = """
┌─────────────────────────────────────────────┐
│  命令列表:                                   │
│  /help       - 显示此帮助                   │
│  /clear      - 清空当前对话                 │
│  /history    - 显示对话历史                 │
│  /save       - 保存当前对话                 │
│  /load <id>  - 加载历史对话                 │
│  /list       - 列出已保存的对话             │
│  /model <名> - 切换模型                     │
│  /system <语> - 设置系统提示词              │
│  /config     - 显示当前配置                 │
│  /exit       - 退出程序                     │
└─────────────────────────────────────────────┘
"""
    print(color(help_text, "yellow"))


class ChatSession:
    """对话会话管理"""

    def __init__(self):
        self.messages: list[dict] = []
        self.created_at = datetime.now()
        self.session_id = self.created_at.strftime("%Y%m%d_%H%M%S")
        self._init_system_prompt()

    def _init_system_prompt(self):
        """初始化系统提示词"""
        if CONFIG["system_prompt"]:
            self.messages.append({
                "role": "system",
                "content": CONFIG["system_prompt"]
            })

    def add_user_message(self, content: str):
        self.messages.append({"role": "user", "content": content})

    def add_assistant_message(self, content: str):
        self.messages.append({"role": "assistant", "content": content})

    def clear(self):
        """清空对话（保留系统提示词）"""
        system_msgs = [m for m in self.messages if m["role"] == "system"]
        self.messages = system_msgs
        self.created_at = datetime.now()
        self.session_id = self.created_at.strftime("%Y%m%d_%H%M%S")

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "model": CONFIG["model"],
            "created_at": self.created_at.isoformat(),
            "messages": self.messages,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ChatSession":
        session = cls()
        session.session_id = data.get("session_id", session.session_id)
        session.messages = data.get("messages", [])
        # 恢复创建时间
        created_str = data.get("created_at")
        if created_str:
            try:
                session.created_at = datetime.fromisoformat(created_str)
            except (ValueError, TypeError):
                pass
        return session


def stream_chat(session: ChatSession) -> str:
    """
    发送消息并流式获取回复
    支持 OpenAI 兼容的 chat/completions 接口
    """
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {CONFIG['api_key']}",
    }

    payload = {
        "model": CONFIG["model"],
        "messages": session.messages,
        "max_tokens": CONFIG["max_tokens"],
        "temperature": CONFIG["temperature"],
        "stream": True,
    }

    resp = None
    try:
        resp = http_session.post(
            f"{CONFIG['api_base']}/chat/completions",
            headers=headers,
            json=payload,
            stream=True,
            timeout=120,
        )

        if resp.status_code != 200:
            error_detail = resp.text[:500]
            print(color(f"\n  ❌ API 错误 ({resp.status_code}): {error_detail}", "red"))
            return ""

        full_content = ""
        print(color("\n  🤖 AI: ", "green"), end="", flush=True)

        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            if line.startswith("data: "):
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                    delta = data.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        print(content, end="", flush=True)
                        full_content += content
                except json.JSONDecodeError:
                    continue

        print()  # 换行
        return full_content

    except requests.exceptions.ConnectionError:
        print(color(f"\n  ❌ 连接失败! 请检查 API 地址: {CONFIG['api_base']}", "red"))
        return ""
    except requests.exceptions.Timeout:
        print(color("\n  ⏰ 请求超时，请重试", "red"))
        return ""
    except Exception as e:
        print(color(f"\n  ❌ 发生错误: {e}", "red"))
        return ""
    finally:
        if resp is not None:
            resp.close()


def save_conversations(sessions: dict):
    """保存所有对话到文件"""
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(sessions, f, ensure_ascii=False, indent=2)
    except OSError as e:
        print(color(f"\n  ⚠️ 保存失败: {e}", "yellow"))


def load_conversations() -> dict:
    """从文件加载对话"""
    if not HISTORY_FILE.exists():
        return {}
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(color(f"\n  ⚠️ 历史文件损坏，已忽略: {e}", "yellow"))
        return {}


def load_readline_history():
    """加载命令行历史"""
    if readline is None or not INPUT_HISTORY_FILE.exists():
        return
    try:
        readline.read_history_file(str(INPUT_HISTORY_FILE))
    except Exception:
        pass


def save_readline_history():
    """保存命令行历史"""
    if readline is None:
        return
    try:
        readline.write_history_file(str(INPUT_HISTORY_FILE))
    except Exception:
        pass


def main():
    """主循环"""
    print_banner()

    session = ChatSession()
    saved_sessions = load_conversations()

    load_readline_history()

    # 用于 /history 显示
    input_history = []

    while True:
        try:
            # 读取用户输入
            user_input = input(color("\n  👤 你: ", "blue")).strip()
        except (KeyboardInterrupt, EOFError):
            print(color("\n\n  再见! 👋\n", "cyan"))
            break

        if not user_input:
            continue

        input_history.append(user_input)

        # 处理命令
        if user_input.startswith("/"):
            cmd_parts = user_input.split(maxsplit=1)
            cmd = cmd_parts[0].lower()
            arg = cmd_parts[1] if len(cmd_parts) > 1 else ""

            if cmd == "/exit":
                print(color("\n  再见! 👋\n", "cyan"))
                break

            elif cmd == "/help":
                print_help()

            elif cmd == "/clear":
                session.clear()
                print(color("  ✅ 对话已清空", "green"))

            elif cmd == "/history":
                print(color("\n  📜 当前对话历史:", "yellow"))
                for i, msg in enumerate(session.messages):
                    role_map = {"system": "系统", "user": "你", "assistant": "AI"}
                    role = role_map.get(msg["role"], msg["role"])
                    content = msg["content"]
                    preview = content[:100].replace("\n", " ")
                    ellipsis = "..." if len(content) > 100 else ""
                    print(color(f"  [{i}] {role}: {preview}{ellipsis}", "dim"))

            elif cmd == "/save":
                saved_sessions[session.session_id] = session.to_dict()
                save_conversations(saved_sessions)
                print(color(f"  ✅ 对话已保存 (ID: {session.session_id})", "green"))

            elif cmd == "/load":
                if not arg:
                    print(color("  ⚠️ 用法: /load <session_id>", "yellow"))
                elif arg in saved_sessions:
                    session = ChatSession.from_dict(saved_sessions[arg])
                    print(color(f"  ✅ 已加载对话 (ID: {arg}), 共 {len(session.messages)} 条消息", "green"))
                else:
                    print(color(f"  ❌ 未找到对话: {arg}", "red"))

            elif cmd == "/list":
                if not saved_sessions:
                    print(color("  📭 没有已保存的对话", "dim"))
                else:
                    print(color("\n  📋 已保存的对话:", "yellow"))
                    for sid, data in saved_sessions.items():
                        created = data.get("created_at", "未知")
                        model = data.get("model", "未知")
                        msg_count = len(data.get("messages", []))
                        print(color(
                            f"  • {sid} | 模型: {model} | 消息数: {msg_count} | 时间: {created}", "dim"))

            elif cmd == "/model":
                if not arg:
                    print(color(f"  当前模型: {CONFIG['model']}", "dim"))
                else:
                    CONFIG["model"] = arg
                    print(color(f"  ✅ 已切换模型: {arg}", "green"))

            elif cmd == "/system":
                if not arg:
                    print(color(f"  当前系统提示词: {CONFIG['system_prompt']}", "dim"))
                else:
                    CONFIG["system_prompt"] = arg
                    # 更新或添加系统消息
                    if session.messages and session.messages[0]["role"] == "system":
                        session.messages[0]["content"] = arg
                    else:
                        session.messages.insert(0, {"role": "system", "content": arg})
                    print(color(f"  ✅ 系统提示词已更新", "green"))

            elif cmd == "/config":
                print(color("\n  ⚙️  当前配置:", "yellow"))
                for key in ["api_base", "model", "max_tokens", "temperature", "system_prompt"]:
                    val = CONFIG[key]
                    print(color(f"  {key}: {val}", "dim"))

            else:
                print(color(f"  ❓ 未知命令: {cmd}，输入 /help 查看帮助", "red"))

        else:
            # 正常对话
            session.add_user_message(user_input)

            # 调用 API
            reply = stream_chat(session)

            if reply:
                session.add_assistant_message(reply)

    # 退出前保存
    save_readline_history()

    # 自动保存当前对话
    if session.messages:
        saved_sessions[session.session_id] = session.to_dict()
        save_conversations(saved_sessions)
        print(color(f"  💾 对话已自动保存 (ID: {session.session_id})", "dim"))


if __name__ == "__main__":
    main()
