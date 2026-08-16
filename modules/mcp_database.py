"""
MCP Database 数据库服务模块
提供 SQLite 数据库查询工具，支持 SELECT 查询和表结构浏览
"""

import os
import sqlite3
import time
from pathlib import Path

from flask import jsonify, request

from . import tool_registry

# ============================================================
# 会话配置
# ============================================================
_connections = {}  # session_id -> {db_path, connected, last_test}


def _get_conn(session_id: str) -> dict:
    if session_id not in _connections:
        _connections[session_id] = {
            "db_path": "",
            "connected": False,
            "last_test": None,
        }
    return _connections[session_id]


def _connect(db_path: str) -> sqlite3.Connection | None:
    """安全连接数据库"""
    try:
        p = Path(db_path).expanduser().resolve()
        if not p.exists():
            return None
        conn = sqlite3.connect(str(p))
        conn.row_factory = sqlite3.Row
        # 只读检查
        conn.execute("SELECT 1")
        return conn
    except Exception:
        return None


# ============================================================
# 工具定义
# ============================================================
DB_QUERY_DEF = {
    "name": "db_query",
    "description": (
        "对 SQLite 数据库执行 SELECT 查询。"
        "仅支持 SELECT 语句，不支持 INSERT/UPDATE/DELETE 等修改操作。"
        "适合查询数据、统计、筛选、排序等。"
        "返回查询结果的表格。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "sql": {
                "type": "string",
                "description": "SELECT 查询语句，如 'SELECT * FROM users LIMIT 10'",
            },
            "session_id": {
                "type": "string",
                "description": "会话 ID",
            },
        },
        "required": ["sql"],
    },
}

DB_TABLES_DEF = {
    "name": "db_list_tables",
    "description": (
        "列出 SQLite 数据库中的所有表名。"
        "在查询之前使用，了解数据库有哪些表。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "会话 ID",
            },
        },
        "required": [],
    },
}

DB_SCHEMA_DEF = {
    "name": "db_schema",
    "description": (
        "获取 SQLite 数据库中指定表的完整结构（列名、类型、约束等 CREATE TABLE 语句）。"
        "在写 SQL 查询之前使用，了解表的字段名和类型。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "table": {
                "type": "string",
                "description": "表名，如 'users'",
            },
            "session_id": {
                "type": "string",
                "description": "会话 ID",
            },
        },
        "required": ["table"],
    },
}


# ============================================================
# 执行器
# ============================================================
def _get_db(session_id: str):
    conn_info = _get_conn(session_id)
    db_path = conn_info.get("db_path", "")
    if not db_path:
        return None, "❌ 数据库未配置。请在数据库服务面板中设置 SQLite 数据库文件路径。"
    db = _connect(db_path)
    if not db:
        return None, f"❌ 无法连接数据库 '{db_path}'。请检查文件是否存在。"
    return db, None


def _exec_db_query(args: dict) -> str:
    session_id = args.get("session_id", "default")
    sql = (args.get("sql") or "").strip()

    if not sql:
        return "错误: SQL 语句不能为空"

    # 安全检查：仅允许 SELECT
    sql_upper = sql.upper().strip()
    if not sql_upper.startswith("SELECT"):
        return "❌ 仅允许 SELECT 查询。不支持 INSERT/UPDATE/DELETE 等修改操作。"

    # 禁止危险关键字
    dangerous = ["ATTACH", "DETACH", "PRAGMA"]
    for kw in dangerous:
        if kw in sql_upper:
            return f"❌ 不允许使用 {kw}"

    db, err = _get_db(session_id)
    if err:
        return err

    try:
        t0 = time.time()
        cursor = db.execute(sql)
        rows = cursor.fetchall()
        elapsed = (time.time() - t0) * 1000

        if not rows:
            return f"✅ 查询执行成功（{elapsed:.0f}ms），无结果。"

        # 格式化输出
        columns = [d[0] for d in cursor.description] if cursor.description else []
        max_rows = 50
        lines = [f"📊 查询结果（{len(rows)} 行, {elapsed:.0f}ms）:"]
        lines.append(" | ".join(columns))
        lines.append("-" * (sum(len(c) for c in columns) + 3 * (len(columns) - 1)))

        for row in rows[:max_rows]:
            lines.append(" | ".join(str(v)[:100] for v in row))

        if len(rows) > max_rows:
            lines.append(f"... 还有 {len(rows) - max_rows} 行未显示，请用 LIMIT 和 OFFSET 分页。")

        return "\n".join(lines)
    except Exception as e:
        return f"❌ 查询失败: {str(e)}"
    finally:
        try:
            db.close()
        except Exception:
            pass


def _exec_db_list_tables(args: dict) -> str:
    session_id = args.get("session_id", "default")
    db, err = _get_db(session_id)
    if err:
        return err

    try:
        cursor = db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [r[0] for r in cursor.fetchall()]

        if not tables:
            return "📊 数据库中暂无表。"

        # 统计每个表的行数
        lines = [f"📊 数据库表列表（共 {len(tables)} 个表）:"]
        for t in tables:
            try:
                cnt = db.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0]
                lines.append(f"  📋 {t} ({cnt} 行)")
            except Exception:
                lines.append(f"  📋 {t}")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ 查询失败: {str(e)}"
    finally:
        try:
            db.close()
        except Exception:
            pass


def _exec_db_schema(args: dict) -> str:
    session_id = args.get("session_id", "default")
    table = (args.get("table") or "").strip()
    if not table:
        return "错误: 表名不能为空"

    db, err = _get_db(session_id)
    if err:
        return err

    try:
        # 获取 CREATE TABLE 语句
        cursor = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        )
        row = cursor.fetchone()
        if not row:
            return f"❌ 表 '{table}' 不存在。使用 db_list_tables 查看可用表。"

        # 同时获取列信息
        cols = db.execute(f"PRAGMA table_info([{table}])").fetchall()

        lines = [f"📋 表结构: {table}"]
        lines.append(f"\n-- 列信息 ({len(cols)} 列):")
        for col in cols:
            pk = " [主键]" if col["pk"] else ""
            nn = " NOT NULL" if col["notnull"] else ""
            dv = f" DEFAULT {col['dflt_value']}" if col["dflt_value"] else ""
            lines.append(f"  {col['name']}: {col['type']}{pk}{nn}{dv}")

        lines.append(f"\n-- DDL:\n{row[0]}")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ 查询失败: {str(e)}"
    finally:
        try:
            db.close()
        except Exception:
            pass


# ============================================================
# 注册工具
# ============================================================
_tool_list = [
    (DB_QUERY_DEF, _exec_db_query),
    (DB_TABLES_DEF, _exec_db_list_tables),
    (DB_SCHEMA_DEF, _exec_db_schema),
]

for tool_def, executor in _tool_list:
    tool_registry.register(tool_def["name"], tool_def, executor)


# ============================================================
# Flask 路由
# ============================================================
def register_routes(app, http_session=None):
    @app.route("/api/database/test-connection", methods=["POST"])
    def database_test_connection():
        """测试 SQLite 数据库连接"""
        data = request.get_json(force=True)
        db_path = (data.get("db_path") or "").strip()
        session_id = data.get("session_id", "default")

        if not db_path:
            return jsonify({"success": False, "error": "请填入数据库文件路径（如 C:/data/mydb.sqlite）"}), 400

        conn = _get_conn(session_id)
        conn["db_path"] = db_path

        t0 = time.time()
        p = Path(db_path).expanduser().resolve()

        if not p.exists():
            conn["connected"] = False
            conn["last_test"] = time.time()
            return jsonify({
                "success": False,
                "error": f"文件不存在: {p}\n请检查路径是否正确。",
            })

        try:
            db = sqlite3.connect(str(p))
            cursor = db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [r[0] for r in cursor.fetchall()]
            db.close()

            latency_ms = round((time.time() - t0) * 1000)
            conn["connected"] = True
            conn["last_test"] = time.time()

            return jsonify({
                "success": True,
                "message": f"连接成功！{len(tables)} 个表",
                "tables": tables[:20],
                "table_count": len(tables),
                "db_path": str(p),
                "latency_ms": latency_ms,
            })
        except Exception as e:
            latency_ms = round((time.time() - t0) * 1000)
            conn["connected"] = False
            conn["last_test"] = time.time()
            return jsonify({
                "success": False,
                "error": f"无法打开数据库: {str(e)}",
                "latency_ms": latency_ms,
            })

    @app.route("/api/database/config", methods=["GET"])
    def database_get_config():
        """获取当前数据库配置"""
        session_id = request.args.get("session_id", "default")
        conn = _get_conn(session_id)
        return jsonify({
            "db_path": conn.get("db_path", ""),
            "connected": conn.get("connected", False),
            "last_test": conn.get("last_test"),
        })
