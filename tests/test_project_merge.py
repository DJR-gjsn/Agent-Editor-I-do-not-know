"""项目布局合并保护测试：自动保存携带空对话历史时保留服务器已有值"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server  # noqa: F401


class TestLayoutMerge(unittest.TestCase):
    def test_preserves_messages_when_incoming_empty(self):
        existing = {
            "components": [
                {"id": 1, "type": "llm", "messages": [{"role": "user", "content": "老对话"}],
                 "searchHistory": [{"q": "旧搜索"}], "x": 0, "y": 0},
                {"id": 2, "type": "web_search", "messages": [], "x": 1, "y": 1},
            ],
            "connections": [],
        }
        incoming = {
            "components": [
                {"id": 1, "type": "llm", "messages": [], "searchHistory": [], "x": 5, "y": 5},
                {"id": 2, "type": "web_search", "messages": [], "x": 1, "y": 1},
            ],
            "connections": [],
        }
        merged = server._merge_layout(incoming, existing)
        comp1 = merged["components"][0]
        self.assertEqual(comp1["messages"], [{"role": "user", "content": "老对话"}])
        self.assertEqual(comp1["searchHistory"], [{"q": "旧搜索"}])
        # 拓扑以传入为准（位置更新）
        self.assertEqual(comp1["x"], 5)

    def test_incoming_non_empty_updates(self):
        existing = {"components": [{"id": 1, "type": "llm", "messages": ["旧"]}], "connections": []}
        incoming = {"components": [{"id": 1, "type": "llm", "messages": ["新", "新2"]}], "connections": []}
        merged = server._merge_layout(incoming, existing)
        self.assertEqual(merged["components"][0]["messages"], ["新", "新2"])

    def test_new_components_pass_through(self):
        existing = {"components": [{"id": 1, "type": "llm", "messages": ["旧"]}], "connections": []}
        incoming = {
            "components": [{"id": 1, "type": "llm", "messages": []},
                           {"id": 2, "type": "calculator", "messages": []}],
            "connections": [{"sourceCompId": 1, "targetCompId": 2}],
        }
        merged = server._merge_layout(incoming, existing)
        self.assertEqual(len(merged["components"]), 2)
        self.assertEqual(merged["components"][0]["messages"], ["旧"])  # 已有组件保护
        self.assertEqual(merged["components"][1]["type"], "calculator")
        self.assertEqual(len(merged["connections"]), 1)

    def test_no_existing_layout(self):
        incoming = {"components": [{"id": 1, "type": "llm", "messages": ["新"]}], "connections": []}
        merged = server._merge_layout(incoming, {})
        self.assertEqual(merged["components"][0]["messages"], ["新"])

    def test_incoming_not_dict(self):
        self.assertEqual(server._merge_layout(None, {"components": []}), {"components": []})


if __name__ == "__main__":
    unittest.main()
