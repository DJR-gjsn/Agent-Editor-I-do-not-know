"""向量库持久化测试：验证落盘、重启恢复、next_id 连续性、损坏容错。

临时目录放在工作区 data/vector_store/.test_tmp/（已被 .gitignore 排除），
避免依赖系统 Temp 的写权限。
"""
import json
import os
import shutil
import unittest
import uuid

from modules import vector_memory as vm


class TestVectorMemoryPersistence(unittest.TestCase):
    def setUp(self):
        self._old_override = vm._STORE_PATH_OVERRIDE
        self._old_api = vm._api_available
        base = os.path.join(vm._PROJECT_ROOT, "data", "vector_store", ".test_tmp")
        self._tmp = os.path.join(base, "vs_" + uuid.uuid4().hex[:10])
        os.makedirs(self._tmp, exist_ok=True)
        # 跳过网络 embedding API，保证测试确定性（用本地 TF-IDF/哈希向量）
        vm._api_available = False
        vm.init_vector_store(os.path.join(self._tmp, "vs1", "vector_store.json"))

    def tearDown(self):
        vm.init_vector_store(self._old_override)
        vm._api_available = self._old_api
        shutil.rmtree(self._tmp, ignore_errors=True)

    # ----------------------------------------------------------
    def _add(self, text):
        return vm._exec_index({"text": text})

    def _disk_file(self):
        with open(vm._store_path(), encoding="utf-8") as f:
            return json.load(f)

    # ----------------------------------------------------------
    def test_index_persists_to_disk(self):
        self._add("第一份资料：向量库持久化说明")
        self._add("第二份资料：重启后应能恢复")
        data = self._disk_file()
        self.assertEqual(len(data["documents"]), 2)
        self.assertEqual(data["next_id"], 2)
        self.assertEqual(vm._get_stats()["doc_count"], 2)

    def test_reload_recovers_documents_and_next_id(self):
        self._add("文档A")
        self._add("文档B")
        # 模拟进程重启：重新从同一路径加载
        vm.init_vector_store(vm._store_path())
        self.assertEqual(vm._get_stats()["doc_count"], 2)
        # next_id 从盘恢复：新文档 id 不与旧文档重叠
        result = self._add("文档C")
        self.assertIn("vec_2", result)

    def test_next_id_recovers_from_file_value(self):
        path = vm._store_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "version": 1,
                "next_id": 7,
                "documents": [{
                    "id": "vec_0",
                    "text": "预置文档",
                    "embedding": [0.1, 0.2],
                    "created_at": "2026-01-01 00:00:00",
                }],
            }, f, ensure_ascii=False)
        vm.init_vector_store(path)
        self.assertEqual(vm._get_stats()["doc_count"], 1)
        result = self._add("新文档")
        self.assertIn("vec_7", result)

    def test_clear_persists_to_disk(self):
        self._add("将被清空")
        self._add("也将被清空")
        vm._clear_store()
        self.assertEqual(vm._get_stats()["doc_count"], 0)
        self.assertEqual(self._disk_file()["documents"], [])
        self.assertEqual(self._disk_file()["next_id"], 0)

    def test_corrupt_file_starts_empty(self):
        path = vm._store_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("这不是合法 JSON {{{")
        vm.init_vector_store(path)
        self.assertEqual(vm._get_stats()["doc_count"], 0)
        result = self._add("损坏后仍可正常写入")
        self.assertIn("vec_0", result)

    def test_path_isolation(self):
        path_a = os.path.join(self._tmp, "a.json")
        path_b = os.path.join(self._tmp, "b.json")
        vm.init_vector_store(path_a)
        self._add("只在A库")
        vm.init_vector_store(path_b)
        self.assertEqual(vm._get_stats()["doc_count"], 0)
        # 切回 A：数据仍在
        vm.init_vector_store(path_a)
        self.assertEqual(vm._get_stats()["doc_count"], 1)

    def test_save_creates_nested_dirs(self):
        deep = os.path.join(self._tmp, "x", "y", "z", "store.json")
        vm.init_vector_store(deep)
        self._add("深层目录写入")
        self.assertTrue(os.path.exists(deep))

    def test_load_ignores_malformed_docs(self):
        path = vm._store_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "version": 1,
                "next_id": 2,
                "documents": [
                    {"id": "vec_0", "text": "合法文档", "embedding": [0.1, 0.2],
                     "created_at": "2026-01-01 00:00:00"},
                    {"id": "vec_1", "text": "缺少向量"},          # 缺 embedding -> 丢弃
                    "不是字典",                                    # 非字典 -> 丢弃
                ],
            }, f, ensure_ascii=False)
        vm.init_vector_store(path)
        self.assertEqual(vm._get_stats()["doc_count"], 1)
        # 丢弃坏条目后 next_id 仍取文件记录值 2，不与已有 id 重叠
        result = self._add("追加")
        self.assertIn("vec_2", result)


if __name__ == "__main__":
    unittest.main()
