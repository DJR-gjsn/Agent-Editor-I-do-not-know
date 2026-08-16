"""mcp_utility 通用工具测试：zip 往返/zip-slip 防护/HTTP 请求/图片处理"""
import io
import json
import os
import sys
import threading
import time
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.mcp_utility import (
    _exec_http_request, _exec_image_compress, _exec_image_convert,
    _exec_image_info, _exec_image_resize, _exec_screenshot, _exec_zip_create,
    _exec_zip_extract,
)
from modules.utils import WORKSPACE, safe_path


def _w(name, content="hello world"):
    p = safe_path(name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


class TestZipTools(unittest.TestCase):
    def setUp(self):
        self.files = [_w(f"zip_test_{time.time():.0f}/a.txt", "AAA"),
                      _w(f"zip_test_{time.time():.0f}/b.txt", "BBB")]
        self.zip_name = f"zip_test_{time.time():.0f}.zip"

    def tearDown(self):
        for f in self.files:
            try:
                f.unlink()
            except OSError:
                pass
        try:
            safe_path(self.zip_name).unlink()
        except OSError:
            pass

    def test_zip_roundtrip(self):
        r1 = _exec_zip_create({"zip_path": self.zip_name,
                               "files": [str(f.relative_to(WORKSPACE)) for f in self.files]})
        self.assertIn("已创建", r1)
        zpath = safe_path(self.zip_name)
        self.assertTrue(zpath.exists())
        # 解压到子目录
        r2 = _exec_zip_extract({"zip_path": self.zip_name, "dest_dir": "zip_out_test"})
        self.assertIn("已解压", r2)
        out1 = safe_path("zip_out_test/" + self.files[0].name)
        self.assertTrue(out1.exists())
        self.assertEqual(out1.read_text(encoding="utf-8"), "AAA")
        # 清理
        import shutil
        shutil.rmtree(safe_path("zip_out_test"), ignore_errors=True)

    def test_zip_extract_zip_slip_protected(self):
        """构造带 ../ 越界成员的 zip，解压必须被拒绝"""
        zpath = safe_path(f"evil_{time.time():.0f}.zip")
        try:
            with zipfile.ZipFile(zpath, "w") as zf:
                zf.writestr("../evil_escape.txt", "PWNED")
            r = _exec_zip_extract({"zip_path": zpath.name})
            self.assertIn("非法路径", r)
            # 越界文件不应被写出（zip-slip 防护）
            escaped = WORKSPACE.parent / "evil_escape.txt"
            self.assertFalse(escaped.exists())
        finally:
            try:
                zpath.unlink()
            except OSError:
                pass


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"hello": "world", "path": self.path}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode() if length else "{}"
        body = json.dumps({"echo": raw}).encode()
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class TestHttpRequest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), _Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_get(self):
        r = _exec_http_request({"method": "GET", "url": f"http://127.0.0.1:{self.port}/test?x=1"})
        d = json.loads(r)
        self.assertEqual(d["status"], 200)
        self.assertEqual(d["body"], json.dumps({"hello": "world", "path": "/test?x=1"}))

    def test_post_json(self):
        r = _exec_http_request({"method": "POST", "url": f"http://127.0.0.1:{self.port}/",
                                "json_body": {"a": 1}})
        d = json.loads(r)
        self.assertEqual(d["status"], 201)
        self.assertIn("a", d["body"])

    def test_bad_url(self):
        r = _exec_http_request({"url": "ftp://bad"})
        self.assertIn("错误", r)

    def test_timeout_cap(self):
        r = _exec_http_request({"method": "GET", "url": f"http://127.0.0.1:{self.port}/",
                                "timeout": 999})
        # 超时被压到 30，请求应正常完成（本地服务器）
        d = json.loads(r)
        self.assertEqual(d["status"], 200)


class TestImageTools(unittest.TestCase):
    def setUp(self):
        from PIL import Image
        self.img_path = safe_path(f"img_test_{time.time():.0f}.png")
        Image.new("RGB", (100, 50), color=(200, 30, 30)).save(self.img_path, "PNG")
        self.name = self.img_path.name

    def tearDown(self):
        import glob as g
        for f in g.glob(str(safe_path("img_test_*")) + "*"):
            try:
                os.remove(f)
            except OSError:
                pass

    def test_image_info(self):
        r = _exec_image_info({"path": self.name})
        self.assertIn("100x50", r)
        self.assertIn("PNG", r)

    def test_image_convert(self):
        r = _exec_image_convert({"path": self.name, "target_format": "jpeg"})
        self.assertIn("已转换", r)
        out = safe_path(self.name).with_suffix(".jpg")
        self.assertTrue(out.exists())
        from PIL import Image
        with Image.open(out) as im:
            self.assertEqual(im.format, "JPEG")

    def test_image_resize(self):
        r = _exec_image_resize({"path": self.name, "width": 50})
        self.assertIn("100x50 → 50x25", r)
        out = safe_path(self.name).with_name(
            safe_path(self.name).stem + "_resized.png")
        self.assertTrue(out.exists())

    def test_image_compress_requires_jpeg(self):
        r = _exec_image_compress({"path": self.name})
        self.assertIn("仅支持压缩", r)


class TestScreenshot(unittest.TestCase):
    def test_screenshot_windows_only(self):
        r = _exec_screenshot({"filename": f"shot_{time.time():.0f}.png"})
        # Windows 桌面环境成功；无头/非 Windows 环境返回错误提示
        if "✅" in r:
            self.assertIn(".png", r)
        else:
            self.assertIn("不支持", r)


if __name__ == "__main__":
    unittest.main()
