"""SSE 空闲心跳测试"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.utils import with_heartbeat


class TestHeartbeat(unittest.TestCase):
    def test_heartbeat_emitted_when_idle(self):
        def slow_events():
            yield {"type": "content", "content": "a"}
            time.sleep(0.4)
            yield {"type": "content", "content": "b"}
        items = list(with_heartbeat(slow_events(), idle_seconds=0.2))
        kinds = [k for k, _ in items]
        self.assertIn("heartbeat", kinds)
        self.assertIn("event", kinds)
        self.assertEqual([k for k, _ in items if k == "event"], ["event", "event"])

    def test_no_heartbeat_when_fast(self):
        def fast_events():
            yield {"type": "content", "content": "x"}
        items = list(with_heartbeat(fast_events(), idle_seconds=0.2))
        kinds = [k for k, _ in items]
        self.assertNotIn("heartbeat", kinds)

    def test_event_order_preserved(self):
        def seq():
            for i in range(5):
                yield {"type": "content", "content": str(i)}
                time.sleep(0.05)
        contents = [p["content"] for k, p in with_heartbeat(seq(), idle_seconds=0.1) if k == "event"]
        self.assertEqual(contents, ["0", "1", "2", "3", "4"])


if __name__ == "__main__":
    unittest.main()
