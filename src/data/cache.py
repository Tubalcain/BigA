"""Web/CLI 共享的 TTL 缓存：内存 + 可选磁盘，并发合并，失败冷却，过期可标陈旧。"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import pickle
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from .calendar import in_session, session_bucket, shanghai_now
from .config import cache_dir, get_data_config

logger = logging.getLogger("biga.data.cache")

CACHE_FORMAT = 1
_CACHE = None
_CACHE_LOCK = threading.Lock()

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None


def _copy_value(value):
    copy = getattr(value, "copy", None)
    if callable(copy):
        try:
            cloned = copy()
            attrs = getattr(value, "attrs", None)
            if attrs is not None and hasattr(cloned, "attrs"):
                cloned.attrs.update(dict(attrs))
            return cloned
        except Exception:
            return value
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, list):
        return list(value)
    return value


def _is_success(value):
    if value is None:
        return False
    empty = getattr(value, "empty", None)
    if empty is True:
        return False
    if empty is False:
        return True
    if isinstance(value, dict) and value.get("available") is False:
        return False
    return True


def stamp_cache_meta(
    value,
    *,
    hit,
    stale=False,
    fetched_at=None,
    age_seconds=None,
    source=None,
    session=None,
):
    work = _copy_value(value)
    if not hasattr(work, "attrs"):
        return work
    work.attrs["cache_hit"] = hit
    work.attrs["cache_stale"] = bool(stale)
    if fetched_at is not None:
        work.attrs["cache_fetched_at"] = fetched_at
    if age_seconds is not None:
        work.attrs["cache_age_seconds"] = int(age_seconds)
    if source:
        work.attrs["cache_source"] = source
        work.attrs.setdefault("source", source)
    if session:
        work.attrs["cache_session"] = session
    if stale:
        issues = list(work.attrs.get("issues") or [])
        if "stale_cache" not in issues:
            issues.append("stale_cache")
        work.attrs["issues"] = issues
        work.attrs["fresh"] = False
    else:
        work.attrs.setdefault("fresh", hit in ("fresh", "coalesced", "miss"))
    return work


@dataclass
class CacheEntry:
    value: object
    expires_at: float
    fetched_at: float
    ok: bool = True
    source: str | None = None
    session: str | None = None
    key: str = ""

    def expired(self, now):
        return float(self.expires_at) <= float(now)

    def age_seconds(self, now):
        return max(0.0, float(now) - float(self.fetched_at))


class TTLCache:
    def __init__(self, max_size=1000, default_ttl=300, enabled=True, clock=None):
        self.max_size = max_size
        self.default_ttl = default_ttl
        self.enabled = enabled
        self._store = {}
        self._cooldowns = {}
        self._lock = threading.Lock()
        self._clock = clock or time.time

    def now(self):
        return float(self._clock())

    def _evict_if_needed(self):
        if len(self._store) < self.max_size:
            return
        now = self.now()
        expired = [key for key, entry in self._store.items() if entry.expired(now)]
        for key in expired:
            self._store.pop(key, None)
        if len(self._store) < self.max_size:
            return
        oldest = min(self._store.items(), key=lambda item: item[1].expires_at)[0]
        self._store.pop(oldest, None)

    def get_entry(self, key, allow_expired=False):
        if not self.enabled:
            return None
        with self._lock:
            entry = self._store.get(key)
            if not entry:
                return None
            if entry.expired(self.now()) and not allow_expired:
                return None
            return entry

    def get(self, key):
        entry = self.get_entry(key)
        if entry is None:
            return None
        return _copy_value(entry.value)

    def set(self, key, value, ttl=None, ok=True, source=None, session=None, fetched_at=None):
        if not self.enabled:
            return None
        ttl = self.default_ttl if ttl is None else int(ttl)
        now = self.now()
        with self._lock:
            if ttl <= 0:
                self._store.pop(key, None)
                return None
            self._evict_if_needed()
            entry = CacheEntry(
                value=_copy_value(value),
                expires_at=now + ttl,
                fetched_at=float(fetched_at if fetched_at is not None else now),
                ok=bool(ok),
                source=source,
                session=session,
                key=key,
            )
            self._store[key] = entry
            return entry

    def set_cooldown(self, key, ttl):
        ttl = int(ttl or 0)
        with self._lock:
            if ttl <= 0:
                self._cooldowns.pop(key, None)
                return
            self._cooldowns[key] = self.now() + ttl

    def in_cooldown(self, key):
        with self._lock:
            expires = self._cooldowns.get(key)
            if expires is None:
                return False
            if expires <= self.now():
                self._cooldowns.pop(key, None)
                return False
            return True

    def clear(self):
        with self._lock:
            self._store.clear()
            self._cooldowns.clear()

    def __len__(self):
        return len(self._store)

    def __bool__(self):
        return True


class _FutureBox:
    def __init__(self):
        self._event = threading.Event()
        self._value = None
        self._error = None

    def set_result(self, value):
        self._value = value
        self._event.set()

    def set_exception(self, exc):
        self._error = exc
        self._event.set()

    def result(self, timeout=None):
        if not self._event.wait(timeout):
            raise TimeoutError("cache single-flight wait timed out")
        if self._error is not None:
            raise self._error
        return self._value


class SharedTTLCache(TTLCache):
    """内存 + 磁盘 + 单飞合并。磁盘写入原子替换；跨进程用文件锁。"""

    def __init__(
        self,
        max_size=1000,
        default_ttl=300,
        enabled=True,
        persist=True,
        directory=None,
        clock=None,
        failure_ttl=45,
        success_max_ttl=3600,
        realtime_ttl=30,
    ):
        super().__init__(max_size=max_size, default_ttl=default_ttl, enabled=enabled, clock=clock)
        self.persist = bool(persist)
        self.directory = Path(directory) if directory else None
        self.failure_ttl = int(failure_ttl)
        self.success_max_ttl = int(success_max_ttl)
        self.realtime_ttl = int(realtime_ttl)
        self._inflight = {}
        self._inflight_lock = threading.Lock()
        if self.persist and self.directory is not None:
            try:
                self.directory.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                logger.warning("缓存目录不可用，改为仅内存: %s", exc)
                self.persist = False

    def _disk_path(self, key):
        if not self.directory:
            return None
        safe = hashlib.sha1(key.encode("utf-8")).hexdigest()
        return self.directory / f"biga-{CACHE_FORMAT}-{safe}.pkl"

    def _lock_path(self, key):
        path = self._disk_path(key)
        if path is None:
            return None
        return path.with_suffix(".lock")

    def _read_disk(self, key):
        path = self._disk_path(key)
        if not self.persist or path is None or not path.exists():
            return None
        try:
            with path.open("rb") as handle:
                payload = pickle.load(handle)
        except Exception as exc:
            logger.warning("读取磁盘缓存失败: %s", exc)
            try:
                path.unlink()
            except OSError:
                pass
            return None
        if not isinstance(payload, dict) or payload.get("format") != CACHE_FORMAT:
            return None
        return CacheEntry(
            value=payload.get("value"),
            expires_at=float(payload.get("expires_at") or 0),
            fetched_at=float(payload.get("fetched_at") or 0),
            ok=bool(payload.get("ok", True)),
            source=payload.get("source"),
            session=payload.get("session"),
            key=key,
        )

    def _write_disk(self, key, entry: CacheEntry):
        path = self._disk_path(key)
        if not self.persist or path is None:
            return
        payload = {
            "format": CACHE_FORMAT,
            "value": entry.value,
            "expires_at": entry.expires_at,
            "fetched_at": entry.fetched_at,
            "ok": entry.ok,
            "source": entry.source,
            "session": entry.session,
            "key": key,
        }
        fd, tmp_name = tempfile.mkstemp(prefix=".biga-cache.", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "wb") as handle:
                pickle.dump(payload, handle, protocol=4)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, path)
        except Exception as exc:
            logger.warning("写入磁盘缓存失败: %s", exc)
            try:
                os.unlink(tmp_name)
            except OSError:
                pass

    def _with_file_lock(self, key, fn):
        lock_path = self._lock_path(key)
        if not self.persist or lock_path is None or fcntl is None:
            return fn()
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                return fn()
            finally:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass

    def get_entry(self, key, allow_expired=False):
        entry = super().get_entry(key, allow_expired=allow_expired)
        if entry is not None:
            return entry
        disk = self._read_disk(key)
        if disk is None:
            return None
        now = self.now()
        if disk.expired(now):
            return disk if allow_expired else None
        remaining = max(1, int(disk.expires_at - now))
        super().set(
            key,
            disk.value,
            ttl=remaining,
            ok=disk.ok,
            source=disk.source,
            session=disk.session,
            fetched_at=disk.fetched_at,
        )
        return super().get_entry(key) or disk

    def set(self, key, value, ttl=None, ok=True, source=None, session=None, fetched_at=None):
        entry = super().set(
            key,
            value,
            ttl=ttl,
            ok=ok,
            source=source,
            session=session,
            fetched_at=fetched_at,
        )
        if entry is not None:
            self._write_disk(key, entry)
        elif self.persist:
            path = self._disk_path(key)
            if path is not None:
                try:
                    path.unlink()
                except OSError:
                    pass
        return entry

    def clear(self):
        super().clear()
        if not self.persist or self.directory is None:
            return
        try:
            for path in self.directory.glob(f"biga-{CACHE_FORMAT}-*"):
                try:
                    path.unlink()
                except OSError:
                    pass
        except OSError:
            pass

    def coalesce(self, key, loader, timeout=60):
        """同一 key 并发只跑一次 loader。"""
        with self._inflight_lock:
            box = self._inflight.get(key)
            owner = box is None
            if owner:
                box = _FutureBox()
                self._inflight[key] = box
        if not owner:
            return box.result(timeout=timeout)
        try:
            result = self._with_file_lock(key, loader)
            box.set_result(result)
            return result
        except Exception as exc:
            box.set_exception(exc)
            raise
        finally:
            with self._inflight_lock:
                self._inflight.pop(key, None)


def bound_success_ttl(requested, kind="generic", now=None, cfg=None, clock=None):
    cfg = cfg or get_data_config()
    cap = int(getattr(cfg.cache, "ttl_success_max", 3600) or 3600)
    requested = int(requested or cfg.cache.ttl)
    realtime = int(getattr(cfg.cache, "ttl_realtime", 30) or 30)
    moment = now
    if moment is None and clock is not None:
        try:
            moment = shanghai_now()
        except Exception:
            moment = None
    if kind in ("flow", "realtime", "quote") and in_session(moment):
        requested = min(requested, realtime)
    return max(1, min(requested, cap))


def bound_failure_ttl(cfg=None):
    cfg = cfg or get_data_config()
    return max(1, min(int(getattr(cfg.cache, "ttl_failure", 45) or 45), 300))


def cached_load(
    cache,
    key,
    loader,
    default=None,
    success_ttl=300,
    failure_ttl=45,
    kind="generic",
    source=None,
    session=None,
    is_success=None,
):
    """
    命中新鲜缓存则返回；并发请求合并；失败短冷却；
    上游失败时若有过期成功结果，标 stale 后返回，不得冒充新鲜。
    """
    is_success = is_success or _is_success
    session = session or session_bucket()
    if cache is None:
        cache = get_cache()

    def _from_entry(entry, hit, stale=False):
        age = entry.age_seconds(cache.now()) if hasattr(cache, "now") else None
        try:
            fetched = datetime.fromtimestamp(entry.fetched_at, tz=timezone.utc).isoformat(timespec="seconds")
        except Exception:
            fetched = shanghai_now().isoformat(timespec="seconds")
        return stamp_cache_meta(
            entry.value if entry.value is not None else default,
            hit=hit,
            stale=stale,
            fetched_at=fetched,
            age_seconds=age,
            source=entry.source or source,
            session=entry.session or session,
        )

    if hasattr(cache, "in_cooldown") and cache.in_cooldown(key):
        cooled = cache.get_entry(key, allow_expired=True) if hasattr(cache, "get_entry") else None
        if cooled is not None:
            stale = cooled.expired(cache.now()) if hasattr(cooled, "expired") else (not cooled.ok)
            hit = "stale" if stale or not cooled.ok else "fresh"
            return _from_entry(cooled, hit, stale=bool(stale or not cooled.ok))

    fresh = cache.get_entry(key, allow_expired=False) if hasattr(cache, "get_entry") else None
    if fresh is not None:
        return _from_entry(fresh, "fresh", stale=False)

    def _load():
        # 拿到锁后再看一次，避免惊群重复打上游
        again = cache.get_entry(key, allow_expired=False) if hasattr(cache, "get_entry") else cache.get(key)
        if again is not None and hasattr(again, "value"):
            return _from_entry(again, "coalesced", stale=False)
        if again is not None and not hasattr(again, "value"):
            return stamp_cache_meta(again, hit="coalesced", source=source, session=session)
        try:
            value = loader()
        except Exception:
            if hasattr(cache, "set_cooldown"):
                cache.set_cooldown(key, failure_ttl)
            stale = cache.get_entry(key, allow_expired=True) if hasattr(cache, "get_entry") else None
            if stale is not None and stale.ok:
                labeled = _from_entry(stale, "stale", stale=True)
                return labeled
            raise
        if value is None:
            value = default
        ok = is_success(value)
        ttl = int(success_ttl if ok else min(int(success_ttl), int(failure_ttl)))
        if not ok:
            ttl = int(failure_ttl)
        setter = getattr(cache, "set")
        setter(key, value, ttl=ttl, ok=ok, source=source, session=session)
        return stamp_cache_meta(
            value if value is not None else default,
            hit="miss",
            stale=False,
            source=source,
            session=session,
        )

    coalesce = getattr(cache, "coalesce", None)
    if callable(coalesce):
        try:
            return coalesce(key, _load)
        except Exception:
            stale = cache.get_entry(key, allow_expired=True) if hasattr(cache, "get_entry") else None
            if stale is not None and stale.ok:
                return _from_entry(stale, "stale", stale=True)
            if default is not None:
                return stamp_cache_meta(default, hit="miss", stale=False, source=source, session=session)
            raise
    return _load()


def get_cache(cfg=None):
    global _CACHE
    cfg = cfg or get_data_config()
    directory = None
    try:
        directory = cache_dir(cfg)
    except Exception:
        directory = None
    persist = bool(getattr(cfg.cache, "persist", True))
    with _CACHE_LOCK:
        if _CACHE is None:
            _CACHE = SharedTTLCache(
                max_size=cfg.cache.max_size,
                default_ttl=cfg.cache.ttl,
                enabled=cfg.cache.enabled,
                persist=persist,
                directory=directory,
                failure_ttl=getattr(cfg.cache, "ttl_failure", 45),
                success_max_ttl=getattr(cfg.cache, "ttl_success_max", 3600),
                realtime_ttl=cfg.cache.ttl_realtime,
            )
        else:
            _CACHE.enabled = cfg.cache.enabled
            _CACHE.max_size = cfg.cache.max_size
            _CACHE.default_ttl = cfg.cache.ttl
            _CACHE.persist = persist
            if directory is not None:
                _CACHE.directory = Path(directory)
            _CACHE.failure_ttl = getattr(cfg.cache, "ttl_failure", 45)
            _CACHE.success_max_ttl = getattr(cfg.cache, "ttl_success_max", 3600)
            _CACHE.realtime_ttl = cfg.cache.ttl_realtime
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
