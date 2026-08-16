"""请求级 API 配置在线程化工具执行中的传递回归测试"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules import tool_registry
from modules.utils import get_request_api_config, set_request_api_config


class TestRequestConfigPropagation(unittest.TestCase):
    def test_config_reaches_tool_in_pool_thread(self):
        seen = {}

        def probe(args):
            seen['cfg'] = get_request_api_config()
            return 'ok'

        tool_registry.register('_probe', {'name': '_probe'}, probe)
        try:
            tool_registry.execute('_probe', {}, timeout=1,
                                  request_config={'api_base': 'http://req.example', 'api_key': 'k', 'model': 'm'})
            self.assertEqual(seen['cfg'].get('api_base'), 'http://req.example')
        finally:
            tool_registry.unregister('_probe')

    def test_no_leakage_between_executions(self):
        seen = []

        def probe(args):
            seen.append(get_request_api_config())
            return 'ok'

        tool_registry.register('_probe2', {'name': '_probe2'}, probe)
        try:
            tool_registry.execute('_probe2', {}, timeout=1, request_config={'api_base': 'http://a'})
            tool_registry.execute('_probe2', {})  # 无 request_config → 不应看到上一个请求的配置
            self.assertEqual(seen[1], {})
        finally:
            tool_registry.unregister('_probe2')

    def test_thread_local_direct(self):
        set_request_api_config({'api_base': 'http://x'})
        self.assertEqual(get_request_api_config().get('api_base'), 'http://x')
        set_request_api_config({})
        self.assertEqual(get_request_api_config(), {})


if __name__ == '__main__':
    unittest.main()
