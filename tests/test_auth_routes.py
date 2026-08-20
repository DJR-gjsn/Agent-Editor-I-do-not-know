"""全局登录保护集成测试（真实 server app 结构）+ 项目按用户隔离（Task 4）"""
import json
import os
import re
import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 在 import server 前注入临时数据库路径（避免污染真实 data/app.db，同 test_chat_route 模式）
_TMP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "data", "vector_store", ".test_tmp")
os.makedirs(_TMP, exist_ok=True)
os.environ["APP_DB_PATH"] = os.path.join(_TMP, "authroutes_" + uuid.uuid4().hex[:10] + ".db")

from flask import Flask, jsonify, redirect, request

import server  # noqa: F401  用于函数级 _project_path 隔离测试
from modules import auth as auth_module, db

BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "data", "vector_store", ".test_tmp")

PUBLIC_PATHS = ("/login", "/static/", "/favicon.ico",
                "/api/auth/login", "/api/auth/register")


def _make_protected_app(projects_dir=None):
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

    if projects_dir is not None:
        # 最小项目路由（复刻 server.py 隔离逻辑，供集成测试；目录注入测试临时目录）
        pd = Path(projects_dir)
        _PROJECT_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

        def _user_dir():
            user = getattr(request, "user", None)
            username = user["username"] if user else "anonymous"
            d = pd / username
            d.mkdir(parents=True, exist_ok=True)
            return d

        @app.route("/api/projects", methods=["GET"])
        def list_projects():
            projects = []
            for p in sorted(_user_dir().glob("*.json"),
                            key=lambda p: p.stat().st_mtime, reverse=True):
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue
                projects.append({"id": data.get("id", p.stem),
                                 "name": data.get("name", "未命名")})
            return jsonify({"projects": projects})

        @app.route("/api/projects", methods=["POST"])
        def create_project():
            body = request.get_json(force=True, silent=True) or {}
            project_id = body.get("id") or ("proj_" + uuid.uuid4().hex[:10])
            if not _PROJECT_ID_RE.match(project_id or ""):
                return jsonify({"error": "非法 project_id"}), 400
            path = _user_dir() / f"{project_id}.json"
            path.write_text(json.dumps({"id": project_id,
                                        "name": body.get("name", "未命名")},
                                       ensure_ascii=False), encoding="utf-8")
            return jsonify({"id": project_id, "name": body.get("name", "未命名")})

        @app.route("/api/projects/<project_id>", methods=["GET"])
        def get_project(project_id):
            if not _PROJECT_ID_RE.match(project_id or ""):
                return jsonify({"error": "非法 project_id"}), 400
            path = _user_dir() / f"{project_id}.json"
            if not path.exists():
                return jsonify({"error": "项目不存在"}), 404
            return jsonify(json.loads(path.read_text(encoding="utf-8")))

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
        self.projects_dir = os.path.join(self.tmpdir, "proj_" + uuid.uuid4().hex[:8])
        self.app = _make_protected_app(projects_dir=self.projects_dir)
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

    def _login_as(self, username, password="secret123"):
        self.client.post("/api/auth/register",
                         json={"username": username, "password": password})
        self.client.post("/api/auth/login",
                         json={"username": username, "password": password})

    def test_project_isolation(self):
        # 用户 A 建项目 → 登出 → 用户 B 登录：B 看不到 A 的项目（目录按用户名隔离）
        self._login_as("alice_iso")
        r = self.client.post("/api/projects", json={"id": "proj_alice_a",
                                                    "name": "A 的项目"})
        self.assertEqual(r.status_code, 200)
        # A 能列出自己的项目
        r = self.client.get("/api/projects")
        self.assertEqual(r.status_code, 200)
        ids = [p["id"] for p in r.get_json()["projects"]]
        self.assertIn("proj_alice_a", ids)
        # 登出后以 B 登录：B 列表看不到 A 的项目
        self.client.post("/api/auth/logout")
        self._login_as("bob_iso")
        r = self.client.get("/api/projects")
        self.assertEqual(r.status_code, 200)
        ids = [p["id"] for p in r.get_json()["projects"]]
        self.assertNotIn("proj_alice_a", ids)
        # B 直接 GET A 的项目 → 404（读不到别人的文件）
        r = self.client.get("/api/projects/proj_alice_a")
        self.assertEqual(r.status_code, 404)
        # 文件系统层面：A 的项目落在 alice 目录下，B 目录无此文件
        self.assertTrue(Path(self.projects_dir, "alice_iso", "proj_alice_a.json").exists())
        self.assertFalse(Path(self.projects_dir, "bob_iso", "proj_alice_a.json").exists())


class TestProjectPathIsolation(unittest.TestCase):
    """server._project_path / _projects_dir_for_user 函数级隔离测试（注入临时 PROJECTS_DIR）

    选择依据（brief Step 1/3 开放式方案）：直接测 server.py 真实函数，
    PROJECTS_DIR 为模块级变量可注入临时目录；无需改 server.py 的测试钩子。
    """

    @classmethod
    def setUpClass(cls):
        os.makedirs(BASE, exist_ok=True)
        cls.tmpdir = os.path.join(BASE, "projpath_" + uuid.uuid4().hex[:10])
        os.makedirs(cls.tmpdir, exist_ok=True)
        cls._orig_projects_dir = server.PROJECTS_DIR

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmpdir, ignore_errors=True)
        server.PROJECTS_DIR = cls._orig_projects_dir

    def setUp(self):
        self.data_dir = os.path.join(self.tmpdir, "data_" + uuid.uuid4().hex[:8])
        server.PROJECTS_DIR = Path(self.data_dir)

    def _path_for(self, project_id, username=None):
        with server.app.test_request_context("/"):
            if username is not None:
                request.user = {"id": 1, "username": username}
            return server._project_path(project_id)

    def test_path_contains_current_username(self):
        p = self._path_for("proj_abc123", username="alice")
        self.assertEqual(p.parent.name, "alice")
        self.assertEqual(p.name, "proj_abc123.json")
        self.assertEqual(p.parent.parent, Path(self.data_dir))
        self.assertTrue(p.parent.exists())  # 用户目录自动创建

    def test_anonymous_fallback_when_no_user(self):
        p = self._path_for("proj_xyz")
        self.assertEqual(p.parent.name, "anonymous")
        self.assertEqual(p.parent.parent, Path(self.data_dir))

    def test_invalid_project_ids_raise_valueerror(self):
        bad_ids = ("../evil", "a/b", "", "a b", "x.json", "a" * 65, None,
                   "..", "a\\b", "a:b")
        for bad in bad_ids:
            with self.assertRaises(ValueError, msg=f"id={bad!r}"):
                self._path_for(bad, username="alice")

    def test_valid_project_ids_accepted(self):
        for ok in ("proj_1", "A-b_c", "a", "a" * 64):
            p = self._path_for(ok, username="alice")
            self.assertEqual(p.parent.name, "alice")
            self.assertEqual(p.name, f"{ok}.json")


if __name__ == "__main__":
    unittest.main()
