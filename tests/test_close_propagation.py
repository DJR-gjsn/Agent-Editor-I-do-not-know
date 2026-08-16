"""客户端断开连接时关闭内部生成器的回归测试"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.utils import with_heartbeat


class TestClosePropagation(unittest.TestCase):
    def test_consumer_close_closes_suspended_inner(self):
        import threading
        closed = threading.Event()

        def inner():
            try:
                for i in range(100):
                    yield {'type': 'content', 'content': str(i)}
            finally:
                closed.set()

        gen = inner()  # 持有强引用，防止 GC 提前触发 finally
        hb = with_heartbeat(gen, idle_seconds=0.05)
        for _ in range(5):
            next(hb)
        # 泵线程填满有界队列(16)后阻塞在 put，inner 挂起于某个 yield
        time.sleep(0.2)
        hb.close()
        self.assertTrue(closed.wait(2), 'consumer close must close the suspended inner generator')


if __name__ == '__main__':
    unittest.main()
