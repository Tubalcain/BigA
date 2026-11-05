"""进程内 TTL 缓存，避免 Streamlit 反复请求同一行情。"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from functools import wraps

from .config import get_data_config


class TTLCache:
    def __init__(self, max_size=1000, default_ttl=300, enabled=True):
        self.max_size = max_size
        self.default_ttl = default_ttl
        self.enabled = enabled
        self._store = {}
        self._lock = threading.Lock()

    def _evict_if_needed(self):
        if len(self._store) < self.max_size:
            return
        # 先删过期，再按最早过期时间淘汰
        now = time.time()
        expired = [key for key, (_, exp) in self._store.items() if exp <= now]
        for key in expired:
            self._store.pop(key, None)
        if len(self._store) < self.max_size:
            return
        oldest = min(self._store.items(), key=lambda item: item[1][1])[0]
        self._store.pop(oldest, None)

    def get(self, key):
        if not self.enabled:
            return None
        with self._lock:
            item = self._store.get(key)
            if not item:
                return None
            value, expires_at = item
            if expires_at <= time.time():
                self._store.pop(key, None)
                return None
            return value

    def set(self, key, value, ttl=None):
        if not self.enabled:
            return
        ttl = self.default_ttl if ttl is None else int(ttl)
        with self._lock:
            if ttl <= 0:
                self._store.pop(key, None)
                return
            self._evict_if_needed()
            self._store[key] = (value, time.time() + ttl)

    def clear(self):
        with self._lock:
            self._store.clear()

    def __len__(self):
        return len(self._store)


_CACHE = None
_CACHE_LOCK = threading.Lock()


def get_cache(cfg=None):
    global _CACHE
    cfg = cfg or get_data_config()
    with _CACHE_LOCK:
        if _CACHE is None:
            _CACHE = TTLCache(
                max_size=cfg.cache.max_size,
                default_ttl=cfg.cache.ttl,
                enabled=cfg.cache.enabled,
            )
        else:
            _CACHE.enabled = cfg.cache.enabled
            _CACHE.max_size = cfg.cache.max_size
            _CACHE.default_ttl = cfg.cache.ttl
        return _CACHE


def reset_cache():
    cache = get_cache()
    cache.clear()
    return cache


def make_cache_key(*parts):
    payload = json.dumps(parts, ensure_ascii=False, default=str, sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def cached(ttl=None, ttl_attr=None):
    """简单方法缓存。ttl_attr 指向实例上的 TTL 秒数字段。"""

    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            cache = getattr(self, "cache", None) or get_cache()
            seconds = ttl
            if seconds is None and ttl_attr:
                seconds = getattr(self, ttl_attr, None)
            if seconds is None:
                seconds = getattr(self, "cache_ttl", None)
            key = make_cache_key(self.__class__.__name__, func.__name__, args, kwargs)
            hit = cache.get(key)
            if hit is not None:
                return hit
            result = func(self, *args, **kwargs)
            cache.set(key, result, ttl=seconds)
            return result

        return wrapper

    return decorator
