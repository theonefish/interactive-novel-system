"""进程内 TTL 缓存：同一个 query 在 TTL 内只算一次（RAG 检索、搜索共用）。"""

import time


class TTLCache:
    """极简 TTL + 容量上限缓存，一个功能一个方法。"""

    def __init__(self, ttl: int, maxsize: int = 128):
        self._ttl = ttl
        self._maxsize = maxsize
        self._store = {}

    def get(self, key: str):
        """命中且未过期则返回缓存值，否则返回 None。"""
        if key in self._store:
            value, ts = self._store[key]
            if time.time() - ts < self._ttl:
                return value
            del self._store[key]
        return None

    def set(self, key: str, value):
        """写入缓存（超容量时淘汰最早写入的一条）。"""
        if len(self._store) >= self._maxsize and key not in self._store:
            oldest = min(self._store, key=lambda k: self._store[k][1])
            del self._store[oldest]
        self._store[key] = (value, time.time())

    def clear(self):
        self._store.clear()
