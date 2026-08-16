"""
会话生命周期管理 — TTL 字典
解决 mcp_office / plan / loop / weather 等模块中全局字典无限增长的内存泄漏问题

提供:
- TTLDict: 带过期时间和最大容量的字典，自动清理过期条目
- 线程安全，适合 Flask 多线程部署
"""

import threading
import time
from collections import OrderedDict


class TTLDict:
    """
    带 TTL（Time-To-Live）和最大容量的线程安全字典。

    特性:
    - 每个条目有独立的过期时间（从最后访问/更新起算）
    - 超过 max_size 时按 LRU 淘汰最早条目
    - 线程安全（读写均加锁）
    - 支持可选的后台清理线程

    用法:
        cache = TTLDict(max_size=100, ttl_seconds=1800)
        cache.set("key1", some_object)
        obj = cache.get("key1")       # 访问自动刷新 TTL
        cache.set("key1", new_obj)    # 更新也刷新 TTL
        cache.cleanup()               # 手动清理过期条目
    """

    def __init__(self, max_size: int = 100, ttl_seconds: int = 1800):
        """
        Args:
            max_size: 最大条目数，超出时淘汰最旧的（LRU）
            ttl_seconds: 条目过期时间（秒），从最后访问起算
        """
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._data = OrderedDict()  # {key: (value, expiry_time)}
        self._lock = threading.Lock()

    def get(self, key, default=None):
        """获取值，访问时自动刷新 TTL。返回 default 如果不存在或已过期。"""
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return default
            value, expiry = entry
            if time.time() > expiry:
                del self._data[key]
                return default
            # 刷新 TTL（LRU: 移到最后）
            self._data.move_to_end(key)
            self._data[key] = (value, time.time() + self._ttl)
            return value

    def set(self, key, value):
        """设置值，如果已存在则更新并刷新 TTL。"""
        with self._lock:
            expiry = time.time() + self._ttl
            if key in self._data:
                self._data.move_to_end(key)
            self._data[key] = (value, expiry)
            # 超出容量时淘汰最旧的
            while len(self._data) > self._max_size:
                self._data.popitem(last=False)

    def delete(self, key):
        """删除指定 key。"""
        with self._lock:
            self._data.pop(key, None)

    def contains(self, key) -> bool:
        """检查 key 是否存在且未过期。"""
        return self.get(key, _SENTINEL) is not _SENTINEL

    def cleanup(self):
        """手动清理所有过期条目。"""
        with self._lock:
            now = time.time()
            expired = [k for k, (_, exp) in self._data.items() if now > exp]
            for k in expired:
                del self._data[k]

    def clear(self):
        """清空所有条目。"""
        with self._lock:
            self._data.clear()

    def items(self):
        """返回所有有效（未过期）条目的 (key, value) 列表。"""
        with self._lock:
            now = time.time()
            return [(k, v) for k, (v, exp) in self._data.items() if now <= exp]

    def __len__(self):
        """返回当前有效条目数（不清除过期条目，仅计数）。"""
        with self._lock:
            return len(self._data)

    def __contains__(self, key):
        return self.contains(key)


# 哨兵值，用于区分「不存在」和「值为 None」
_SENTINEL = object()
