"""全局登录保护集成测试（真实 server app 结构）"""
import os
import sys
import unittest
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, jsonify, redirect, request

from modules import auth as auth_module, db

BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "data", "vector_store", ".test_tmp")

PUBLIC_PATHS = ("/login", "/static/", "/favicon.ico",
                "/api/auth/login", "/api/auth/register")


def _make_protected_app():
    app = Flask(__name__)
    auth_module.register_routes(app)

    @app.route("/")
    def index():
        return "index page"

    @app.route("/editor")
    def editor():
        return "editor page"

    @app.route("/api/probe")
    def api_probe():
        return jsonify({"success": True})

    @app.before_request
    def require_login():
        path = request.path
        for p in PUBLIC_PATHS:
            if path == p or (p.endswith("/") and path.startswith(p)):
                return None
        user = auth_module.get_current_user()
        if user:
            request.user = user
            return None
        if path.startswith("/api/"):
            return jsonify({"success": False, "error": "未登录"}), 401
        return redirect("/login")

    return app


class TestAuthProtection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.makedirs(BASE, exist_ok=True)
        cls.tmpdir = os.path.join(BASE, "authrt_" + uuid.uuid4().hex[:10])
        os.makedirs(cls.tmpdir, exist_ok=True)
        cls.db_path = os.path.join(cls.tmpdir, "auth.db")

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def setUp(self):
        db.init_db(self.db_path)
        self.app = _make_protected_app()
        self.client = self.app.test_client()

    def tearDown(self):
        db.close_connection()

    def test_page_redirects_when_anonymous(self):
        for path in ("/", "/editor"):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 302, path)
            self.assertIn("/login", r.headers.get("Location", ""))

    def test_api_401_when_anonymous(self):
        r = self.client.get("/api/probe")
        self.assertEqual(r.status_code, 401)
        self.assertFalse(r.get_json()["success"])

    def test_login_page_public(self):
        # 白名单路径不跳转（此处无 login 模板，返回 404 也证明未走 302）
        r = self.client.get("/login")
        self.assertNotEqual(r.status_code, 302)

    def test_authenticated_access(self):
        self.client.post("/api/auth/register",
                         json={"username": "dave", "password": "secret123"})
        self.client.post("/api/auth/login",
                         json={"username": "dave", "password": "secret123"})
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/api/probe").status_code, 200)


if __name__ == "__main__":
    unittest.main()
