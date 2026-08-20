"""认证与设置接口测试（Flask test client + 临时 SQLite）"""
import json
import os
import sys
import unittest
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask

from modules import auth, db

BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "data", "vector_store", ".test_tmp")


def _make_app():
    app = Flask(__name__)
    auth.register_routes(app)
    return app


class AuthTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.makedirs(BASE, exist_ok=True)
        cls.tmpdir = os.path.join(BASE, "auth_" + uuid.uuid4().hex[:10])
        os.makedirs(cls.tmpdir, exist_ok=True)
        cls.db_path = os.path.join(cls.tmpdir, "auth.db")

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def setUp(self):
        # 每个测试重建独立库文件，避免跨测试数据残留（db.init_db 不清库）
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        db.init_db(self.db_path)
        self.app = _make_app()
        self.client = self.app.test_client()

    def tearDown(self):
        db.close_connection()

    def _register(self, username="alice", password="secret123"):
        return self.client.post("/api/auth/register",
                                json={"username": username, "password": password})

    def _login(self, username="alice", password="secret123"):
        return self.client.post("/api/auth/login",
                                json={"username": username, "password": password})

    def test_register_success(self):
        r = self._register()
        self.assertEqual(r.status_code, 201)
        body = r.get_json()
        self.assertTrue(body["success"])
        self.assertEqual(body["user"]["username"], "alice")
        # 密码是哈希，非明文
        row = db.query_one("SELECT password_hash FROM users WHERE username='alice'")
        self.assertNotEqual(row["password_hash"], "secret123")
        self.assertTrue(row["password_hash"].startswith("pbkdf2"))

    def test_register_duplicate(self):
        self._register()
        r = self._register()
        self.assertEqual(r.status_code, 400)
        self.assertIn("已存在", r.get_json()["error"])

    def test_register_invalid_username(self):
        r = self.client.post("/api/auth/register",
                             json={"username": "a!", "password": "secret123"})
        self.assertEqual(r.status_code, 400)

    def test_register_short_password(self):
        r = self.client.post("/api/auth/register",
                             json={"username": "carol", "password": "123"})
        self.assertEqual(r.status_code, 400)

    def test_login_success_sets_cookie(self):
        self._register()
        r = self._login()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["success"])
        self.assertIn("session_id", r.headers.get("Set-Cookie", ""))
        self.assertIsNotNone(db.query_one("SELECT id FROM sessions"))

    def test_login_wrong_password_same_message(self):
        self._register()
        r = self._login(password="wrongpass")
        self.assertEqual(r.status_code, 401)
        self.assertIn("用户名或密码错误", r.get_json()["error"])
        r2 = self._login(username="nobody")
        self.assertEqual(r2.status_code, 401)
        self.assertIn("用户名或密码错误", r2.get_json()["error"])

    def test_me_requires_login(self):
        r = self.client.get("/api/auth/me")
        self.assertEqual(r.status_code, 401)

    def test_me_after_login(self):
        self._register()
        self._login()
        r = self.client.get("/api/auth/me")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["user"]["username"], "alice")

    def test_logout_clears_session(self):
        self._register()
        self._login()
        r = self.client.post("/api/auth/logout")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(db.query_one("SELECT id FROM sessions"), None)
        self.assertIn("session_id=", r.headers.get("Set-Cookie", ""))
        # 登出后再访问 me → 401
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_expired_session_rejected(self):
        self._register()
        self._login()
        db.execute("UPDATE sessions SET expires_at = '2000-01-01 00:00:00'")
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_settings_crud(self):
        self._register()
        self._login()
        r = self.client.put("/api/settings/llm_config", json={"value": {"model": "gpt-4"}})
        self.assertTrue(r.get_json()["success"])
        r = self.client.get("/api/settings")
        self.assertEqual(r.get_json()["settings"]["llm_config"], {"model": "gpt-4"})
        r = self.client.delete("/api/settings/llm_config")
        self.assertTrue(r.get_json()["success"])
        self.assertEqual(self.client.get("/api/settings").get_json()["settings"], {})

    def test_settings_require_login(self):
        self.assertEqual(self.client.get("/api/settings").status_code, 401)


if __name__ == "__main__":
    unittest.main()
