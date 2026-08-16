"""
MCP Calendar 日历服务模块
提供日历事件创建、查询功能
支持 Google Calendar API 和本地 JSON 存储两种模式
"""

import json
import os
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

from flask import jsonify, request

from . import tool_registry

# ============================================================
# 本地日历存储（无需 API Key）
# ============================================================
_CAL_DIR = Path(tempfile.gettempdir()) / "mcp_calendars"


def _get_cal_file(session_id: str) -> Path:
    _CAL_DIR.mkdir(parents=True, exist_ok=True)
    return _CAL_DIR / f"{session_id}.json"


def _load_events(session_id: str) -> list:
    f = _get_cal_file(session_id)
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save_events(session_id: str, events: list):
    _get_cal_file(session_id).write_text(
        json.dumps(events, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ============================================================
# 工具定义
# ============================================================
CAL_LIST_DEF = {
    "name": "calendar_list",
    "description": (
        "列出日历中的事件。可按日期范围筛选。"
        "使用本地 JSON 存储，无需 Google 账号。"
        "当用户询问今天/本周有什么安排、查看日程时使用。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "date_from": {"type": "string", "description": "起始日期，格式 YYYY-MM-DD，默认今天"},
            "date_to": {"type": "string", "description": "结束日期，格式 YYYY-MM-DD，默认 7 天后"},
            "session_id": {"type": "string", "description": "会话 ID"},
        },
        "required": [],
    },
}

CAL_CREATE_DEF = {
    "name": "calendar_create",
    "description": (
        "在日历中创建新事件。"
        "当用户要求安排日程、设置提醒、添加事件时使用。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "事件标题"},
            "date": {"type": "string", "description": "事件日期，格式 YYYY-MM-DD，默认今天"},
            "time": {"type": "string", "description": "事件时间，格式 HH:MM，如 '14:30'（可选）"},
            "duration_min": {"type": "integer", "description": "持续时间（分钟），默认 60", "default": 60},
            "description": {"type": "string", "description": "事件描述（可选）"},
            "session_id": {"type": "string", "description": "会话 ID"},
        },
        "required": ["title"],
    },
}


# ============================================================
# 执行器
# ============================================================
def _exec_calendar_list(args: dict) -> str:
    session_id = args.get("session_id", "default")
    today = time.strftime("%Y-%m-%d")
    date_from = args.get("date_from", today)
    date_to = args.get("date_to", (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d"))

    events = _load_events(session_id)

    # 筛选日期范围
    filtered = [e for e in events if date_from <= e.get("date", "") <= date_to]
    filtered.sort(key=lambda e: (e.get("date", ""), e.get("time", "00:00")))

    if not filtered:
        return f"📅 {date_from} ~ {date_to} 期间没有事件。"

    lines = [f"📅 日程 ({date_from} ~ {date_to})，共 {len(filtered)} 个事件:"]
    for e in filtered:
        time_str = f" {e['time']}" if e.get("time") else ""
        dur = e.get("duration_min", 60)
        dur_str = f" ({dur}分钟)" if dur != 60 else ""
        desc = f" — {e['description'][:60]}" if e.get("description") else ""
        lines.append(f"\n  📌 {e['date']}{time_str}: {e['title']}{dur_str}{desc}")

    return "\n".join(lines)


def _exec_calendar_create(args: dict) -> str:
    session_id = args.get("session_id", "default")
    title = args.get("title", "")
    date = args.get("date", time.strftime("%Y-%m-%d"))
    event_time = args.get("time", "")
    duration = int(args.get("duration_min", 60))
    description = args.get("description", "")

    if not title:
        return "错误: title 不能为空"

    event = {
        "id": f"evt_{int(time.time())}_{len(_load_events(session_id))}",
        "title": title,
        "date": date,
        "time": event_time,
        "duration_min": duration,
        "description": description,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    events = _load_events(session_id)
    events.append(event)
    _save_events(session_id, events)

    time_str = f" {event_time}" if event_time else ""
    return f"✅ 已创建事件:\n📌 {date}{time_str}: {title}" + (f"\n📝 {description}" if description else "")


_tool_list = [
    (CAL_LIST_DEF, _exec_calendar_list),
    (CAL_CREATE_DEF, _exec_calendar_create),
]

for tool_def, executor in _tool_list:
    tool_registry.register(tool_def["name"], tool_def, executor)


# ============================================================
# Flask 路由
# ============================================================
def register_routes(app, http_session=None):
    @app.route("/api/calendar/test-connection", methods=["POST"])
    def calendar_test_connection():
        """测试日历服务可用性"""
        session_id = (request.get_json(force=True) or {}).get("session_id", "default")
        events = _load_events(session_id)
        return jsonify({
            "success": True,
            "message": f"日历服务就绪（本地存储模式）\n已有 {len(events)} 个事件",
            "mode": "本地 JSON 存储",
            "storage": str(_get_cal_file(session_id)),
            "event_count": len(events),
            "note": "数据存储在本地，无需 Google 账号。如需 Google Calendar 集成，请配置 OAuth 凭证。",
        })

    @app.route("/api/calendar/events", methods=["GET"])
    def calendar_get_all_events():
        """获取所有日历事件（供前端面板显示）"""
        session_id = request.args.get("session_id", "default")
        events = _load_events(session_id)
        events.sort(key=lambda e: (e.get("date", ""), e.get("time", "00:00")))
        return jsonify({"events": events, "count": len(events)})
