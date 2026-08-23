"""全局缓存：优先 Redis，不可用时降级为进程内 dict（LRU 容量 1024）。"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import OrderedDict
from typing import Any, Optional

try:
    import redis  # type: ignore
except ImportError:
    redis = None


def _jloads(s):
    try:
        return json.loads(s)
    except Exception:
        return None


class MemoryLRU:
    def __init__(self, maxsize: int = 1024):
        self._data: "OrderedDict[str, tuple[Any, float]]" = OrderedDict()
        self._lock = threading.Lock()
        self._max = maxsize

    def get(self, key: str) -> Any:
        with self._lock:
            v = self._data.get(key)
            if not v:
                return None
            value, expire_ts = v
            if expire_ts and expire_ts < time.time():
                del self._data[key]
                return None
            self._data.move_to_end(key)
            return value

    def set(self, key: str, value: Any, ex: int = 0) -> None:
        with self._lock:
            self._data[key] = (value, time.time() + ex if ex else 0)
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                self._data.popitem(last=False)

    def delete(self, pattern: str) -> int:
        if pattern.endswith("*"):
            prefix = pattern[:-1]
            with self._lock:
                keys = [k for k in self._data if k.startswith(prefix)]
                for k in keys:
                    self._data.pop(k, None)
                return len(keys)
        with self._lock:
            return 1 if self._data.pop(pattern, None) else 0


class CacheLayer:
    _instance: Optional["CacheLayer"] = None

    def __init__(self):
        self.use_redis = False
        self.rds: Any = None
        if redis is not None:
            url = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
            try:
                r = redis.Redis.from_url(url, socket_timeout=1, socket_connect_timeout=1,
                                         decode_responses=True)
                r.ping()
                self.rds = r
                self.use_redis = True
            except Exception:
                self.rds = None
        if not self.use_redis:
            self._mem = MemoryLRU()

    @classmethod
    def instance(cls) -> "CacheLayer":
        if cls._instance is None:
            cls._instance = CacheLayer()
        return cls._instance

    # ---- public ----
    def get_json(self, key: str) -> Any:
        if self.use_redis:
            raw = self.rds.get(key)
            return _jloads(raw) if raw else None
        return self._mem.get(key)

    def set_json(self, key: str, value: Any, ex: int = 3600) -> None:
        s = json.dumps(value, ensure_ascii=False, default=str)
        if self.use_redis:
            self.rds.set(key, s, ex=ex)
        else:
            self._mem.set(key, value, ex=ex)

    def delete(self, pattern: str) -> int:
        if self.use_redis:
            if pattern.endswith("*"):
                keys = list(self.rds.scan_iter(match=pattern))
                if keys:
                    return self.rds.delete(*keys) or 0
                return 0
            return self.rds.delete(pattern) or 0
        return self._mem.delete(pattern)
