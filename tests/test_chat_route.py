"""/api/chat 路由冒烟测试（不依赖真实 LLM API）"""
import os
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 在 import server 前注入临时数据库路径（避免污染真实 data/app.db）
_TMP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "data", "vector_store", ".test_tmp")
os.makedirs(_TMP, exist_ok=True)
os.environ["APP_DB_PATH"] = os.path.join(_TMP, "chatroute_" + uuid.uuid4().hex[:10] + ".db")

import server  # noqa: F401  (导入即注册所有路由)

from modules import db


class TestChatRoute(unittest.TestCase):
    def setUp(self):
        server.app.config["TESTING"] = True
        self.client = server.app.test_client()
        # db._db_path 是模块级单例，其他测试类可能已改指向并删除其临时目录
        # （如 test_auth_routes tearDownClass 的 rmtree）→ 重新初始化到本测试的临时库
        db.init_db()
        # 全局登录保护：注册并登录测试用户（client 自动携带 cookie）
        self.client.post("/api/auth/register",
                         json={"username": "chat_test", "password": "secret123"})
        self.client.post("/api/auth/login",
                         json={"username": "chat_test", "password": "secret123"})

    def test_route_registered(self):
        rules = {str(r) for r in server.app.url_map.iter_rules()}
        self.assertIn("/api/chat", rules)

    def test_login_page_available(self):
        resp = self.client.get("/login")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Agent Editor", resp.data)

    def test_chat_returns_sse_stream(self):
        # api_base 指向不可达地址 → 立即 ConnectionError → SSE 错误事件
        resp = self.client.post("/api/chat", json={
            "messages": [{"role": "user", "content": "hi"}],
            "api_base": "http://127.0.0.1:1",
            "max_tool_rounds": 1,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/event-stream", resp.content_type)
        body = resp.get_data(as_text=True)
        self.assertIn("data:", body)

    def test_chat_new_format_layout(self):
        # 新请求体：layout + message（api_base 不可达 → SSE 错误事件，验证路由接受新格式）
        resp = self.client.post("/api/chat", json={
            "layout": {"components": [{"id": "llm1", "type": "llm"}],
                       "connections": []},
            "comp_id": "llm1",
            "message": "hi",
            "llm_config": {"api_base": "http://127.0.0.1:1", "max_tool_rounds": 1},
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/event-stream", resp.content_type)
        body = resp.get_data(as_text=True)
        self.assertIn("data:", body)

    def test_chat_new_format_layout_with_tool(self):
        # 新格式：layout 含 calculator 直连工具 → 工具进入 chat_with_tools 流（不可达 api_base
        # 会先报连接错误；此处主要验证路由不因工具注入 500，且 SSE 事件流正常产出）
        resp = self.client.post("/api/chat", json={
            "layout": {"components": [{"id": "llm1", "type": "llm"},
                                      {"id": "calc", "type": "calculator",
                                       "toolEnabled": True}],
                       "connections": [{"sourceCompId": "llm1", "sourcePortId": "llm-out",
                                        "targetCompId": "calc", "targetPortId": "in"}]},
            "comp_id": "llm1",
            "message": "1+1=?",
            "llm_config": {"api_base": "http://127.0.0.1:1", "max_tool_rounds": 1},
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/event-stream", resp.content_type)
        body = resp.get_data(as_text=True)
        self.assertIn("data:", body)


if __name__ == "__main__":
    unittest.main()
