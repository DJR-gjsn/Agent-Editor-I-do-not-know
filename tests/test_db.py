"""数据库层测试：schema 初始化/幂等/外键/唯一约束"""
import os
import sqlite3
import sys
import unittest
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules import db

BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "data", "vector_store", ".test_tmp")


class TestDb(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.makedirs(BASE, exist_ok=True)
        cls.tmpdir = os.path.join(BASE, "db_" + uuid.uuid4().hex[:10])
        os.makedirs(cls.tmpdir, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def setUp(self):
        self.db_path = os.path.join(self.tmpdir, "test.db")
        db.init_db(self.db_path)

    def tearDown(self):
        # 断开本线程连接，避免跨测试复用
        db.close_connection()

    def test_tables_created(self):
        rows = db.query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
            "('users','sessions','user_settings') ORDER BY name")
        names = [r["name"] for r in rows]
        self.assertEqual(names, ["sessions", "user_settings", "users"])

    def test_init_idempotent(self):
        db.init_db(self.db_path)  # 第二次不报错
        rows = db.query("SELECT count(*) AS n FROM sqlite_master WHERE type='table'")
        self.assertGreater(rows[0]["n"], 0)

    def test_foreign_key_cascade(self):
        uid = db.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            ("alice", "hash"))
        db.execute(
            "INSERT INTO sessions (id, user_id, expires_at) VALUES (?, ?, ?)",
            ("s1", uid, "2099-01-01 00:00:00"))
        self.assertIsNotNone(db.query_one("SELECT id FROM sessions WHERE id='s1'"))
        db.execute("DELETE FROM users WHERE id = ?", (uid,))
        self.assertIsNone(db.query_one("SELECT id FROM sessions WHERE id='s1'"))

    def test_username_unique(self):
        db.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)",
                   ("bob", "h1"))
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)",
                       ("bob", "h2"))


if __name__ == "__main__":
    unittest.main()
