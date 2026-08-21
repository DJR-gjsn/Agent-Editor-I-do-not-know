"""meta 元数据端点测试"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask

from modules import meta


class TestMeta(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask(__name__)
        meta.register_routes(cls.app)
        cls.client = cls.app.test_client()

    def test_components_endpoint_structure(self):
        r = self.client.get("/api/meta/components")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()["data"]
        defs = data["component_defs"]
        self.assertGreater(len(defs), 40, "应有全部组件")
        self.assertIn("llm", defs)
        self.assertIn("mcp_external", defs)
        for t, d in defs.items():
            for key in ("icon", "title", "color", "defaultSize", "ports",
                        "description", "renderKey", "category"):
                self.assertIn(key, d, f"{t} 缺 {key}")
            # renderKey 必须是字符串（前端关联渲染函数用）
            self.assertIsInstance(d["renderKey"], str, f"{t} renderKey 非字符串")
        self.assertGreater(len(data["tool_name_map"]), 20)
        self.assertGreater(len(data["quick_templates"]), 0, "应有快速模板")
        self.assertGreater(len(data["provider_presets"]), 0, "应有厂商预设")

    def test_render_keys_are_function_names(self):
        """renderKey 应为合法 JS 函数名模式（前端本地映射用）"""
        import re
        data = self.client.get("/api/meta/components").get_json()["data"]
        for t, d in data["component_defs"].items():
            rk = d["renderKey"]
            self.assertTrue(re.match(r"^[A-Za-z_$][A-Za-z0-9_$]*$", rk),
                            f"{t} renderKey '{rk}' 非法")

    def test_settings_endpoint_structure(self):
        """/api/meta/settings：themes 非空，主题字段完整，字号/行距滑块元数据齐全"""
        r = self.client.get("/api/meta/settings")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["success"])
        data = r.get_json()["data"]
        themes = data["themes"]
        self.assertGreater(len(themes), 0, "应有主题")
        keys = {t["key"] for t in themes}
        self.assertIn("industrial", keys, "应有默认主题 industrial")
        for t in themes:
            for k in ("key", "name", "description"):
                self.assertIn(k, t, f"主题 {t.get('key')} 缺 {k}")
        fs = data["fontSizes"]
        self.assertEqual((fs["min"], fs["max"], fs["default"]), (0.8, 1.2, 1.0))
        lh = data["lineHeights"]
        self.assertEqual((lh["min"], lh["max"], lh["default"]), (1.2, 2.2, 1.6))
        self.assertGreater(fs["step"], 0)
        self.assertGreater(lh["step"], 0)

    def test_settings_route_registered(self):
        """settings 路由应注册在应用上（与 components 同 app）"""
        rules = {str(r) for r in self.app.url_map.iter_rules()}
        self.assertIn("/api/meta/settings", rules)
        self.assertIn("/api/meta/components", rules)


if __name__ == "__main__":
    unittest.main()
