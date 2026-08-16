"""工具执行超时保护测试"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules import tool_registry


class TestToolTimeout(unittest.TestCase):
    def test_timeout_returns_message(self):
        def slow(args):
            time.sleep(5)
            return "done"
        tool_registry.register("_test_slow", {"name": "_test_slow"}, slow)
        try:
            t0 = time.time()
            result = tool_registry.execute("_test_slow", {}, timeout=0.5)
            elapsed = time.time() - t0
            self.assertIn("超时", result)
            self.assertLess(elapsed, 3, "超时应快速返回而非等待工具完成")
        finally:
            tool_registry.unregister("_test_slow")

    def test_normal_execution_returns_result(self):
        def fast(args):
            return "ok:" + str(args.get("x"))
        tool_registry.register("_test_fast", {"name": "_test_fast"}, fast)
        try:
            self.assertEqual(tool_registry.execute("_test_fast", {"x": 1}), "ok:1")
        finally:
            tool_registry.unregister("_test_fast")

    def test_unknown_tool(self):
        self.assertIn("未知工具", tool_registry.execute("_no_such_tool", {}))


if __name__ == "__main__":
    unittest.main()
