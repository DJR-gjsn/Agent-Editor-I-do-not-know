"""延期项修复回归测试：
1. LLM_TOOL_TIMEOUT 支持小数（tool_timeout 走 _FLOAT_KEYS）
2. 工具线程池饱和时快速失败（不排队等完整超时）
3. 智能模式 _activated_skills 计数线程安全（锁保护 read-modify-write）
"""
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules import config as cfg_mod
from modules import tool_registry
from modules import chat_routes


class TestConfigFloatTimeout(unittest.TestCase):
    def test_llm_tool_timeout_supports_float(self):
        old = os.environ.get("LLM_TOOL_TIMEOUT")
        try:
            os.environ["LLM_TOOL_TIMEOUT"] = "0.5"
            cfg = cfg_mod.reload_config()
            self.assertEqual(cfg["tool_timeout"], 0.5)
            self.assertIsInstance(cfg["tool_timeout"], float)
        finally:
            if old is None:
                os.environ.pop("LLM_TOOL_TIMEOUT", None)
            else:
                os.environ["LLM_TOOL_TIMEOUT"] = old
            cfg_mod.reload_config()

    def test_default_timeout_still_180(self):
        cfg = cfg_mod.reload_config()
        self.assertEqual(cfg["tool_timeout"], 180)


class TestPoolSaturation(unittest.TestCase):
    def test_saturation_fails_fast(self):
        release = threading.Event()

        def stuck(args):
            release.wait(30)
            return "released"

        tool_registry.register("_stuck", {"name": "_stuck"}, stuck)
        try:
            # 占满 8 个 worker：每次 0.3s 超时返回，但底层线程卡在 release.wait
            for _ in range(8):
                r = tool_registry.execute("_stuck", {}, timeout=0.3)
                self.assertIn("超时", r)
            time.sleep(0.5)  # 等 8 个 worker 全部启动并阻塞
            # 第 9 次：池已满 → 应快速返回"繁忙"提示（远小于 5s 超时）
            t0 = time.time()
            r9 = tool_registry.execute("_stuck", {}, timeout=5)
            elapsed = time.time() - t0
            self.assertIn("繁忙", r9)
            self.assertLess(elapsed, 2, f"饱和时应快速失败，实际耗时 {elapsed:.1f}s")
        finally:
            release.set()  # 释放卡住的线程
            time.sleep(0.5)
            tool_registry.unregister("_stuck")


class TestSmartModeLock(unittest.TestCase):
    def setUp(self):
        chat_routes._smart_skills_cache["skillA"] = {"name": "A", "prompt": "指导", "tools": []}
        chat_routes._activated_skills.clear()

    def tearDown(self):
        chat_routes._smart_skills_cache.clear()
        chat_routes._activated_skills.clear()

    def test_first_activation_returns_full_prompt(self):
        r1 = tool_registry.execute("use_skill", {"skill_id": "skillA"})
        self.assertIn("✅ 已激活技能", r1)

    def test_second_activation_returns_warning(self):
        tool_registry.execute("use_skill", {"skill_id": "skillA"})
        r2 = tool_registry.execute("use_skill", {"skill_id": "skillA"})
        self.assertIn("已经激活过了", r2)

    def test_activation_count_thread_safe(self):
        results = []

        def worker():
            results.append(tool_registry.execute("use_skill", {"skill_id": "skillA"}))

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # 20 次并发激活，计数必须精确为 20（无锁时 read-modify-write 会丢更新）
        self.assertEqual(chat_routes._activated_skills.get("skillA"), 20)


if __name__ == "__main__":
    unittest.main()
