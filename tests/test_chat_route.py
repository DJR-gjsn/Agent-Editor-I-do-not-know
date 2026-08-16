"""/api/chat 路由冒烟测试（不依赖真实 LLM API）"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server  # noqa: F401  (导入即注册所有路由)


class TestChatRoute(unittest.TestCase):
    def setUp(self):
        server.app.config["TESTING"] = True
        self.client = server.app.test_client()

    def test_route_registered(self):
        rules = {str(r) for r in server.app.url_map.iter_rules()}
        self.assertIn("/api/chat", rules)

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
