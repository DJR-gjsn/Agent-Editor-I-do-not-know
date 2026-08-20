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


if __name__ == "__main__":
    unittest.main()
