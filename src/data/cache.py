"""Web/CLI 共享的 TTL 缓存：内存 + JSON 磁盘，跨进程合并，失败冷却与好数据分离。"""

from __future__ import annotations

import hashlib
import json
import logging
import os
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

CACHE_FORMAT = 2
CACHE_MAGIC = b"BIGAJSON1\n"
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
    if stale or hit in ("failure", "cooldown"):
        work.attrs["fresh"] = False
    if stale:
        issues = list(work.attrs.get("issues") or [])
        if "stale_cache" not in issues:
            issues.append("stale_cache")
        work.attrs["issues"] = issues
    elif hit in ("fresh", "coalesced", "miss"):
        work.attrs.setdefault("fresh", True)
    else:
        work.attrs.setdefault("fresh", False)
    return work


def _jsonable(obj, depth=0):
    if depth > 8:
        return str(obj)
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        out = {}
        for key, value in obj.items():
            try:
                out[str(key)] = _jsonable(value, depth + 1)
            except TypeError:
                out[str(key)] = str(value)
        return out
    if isinstance(obj, (list, tuple)):
        return [_jsonable(item, depth + 1) for item in obj]
    return str(obj)


def encode_cache_value(value):
    try:
        import pandas as pd
    except ImportError:  # pragma: no cover
        pd = None
    if pd is not None and isinstance(value, pd.DataFrame):
        work = value.copy()
        attrs = _jsonable(dict(work.attrs))
        payload = json.loads(work.to_json(orient="split", date_format="iso"))
        return {"__biga__": "df", "data": payload, "attrs": attrs}
    if isinstance(value, dict):
        return {"__biga__": "dict", "data": _jsonable(value)}
    if isinstance(value, list):
        return {"__biga__": "list", "data": _jsonable(value)}
    return {"__biga__": "json", "data": _jsonable(value)}


def decode_cache_value(payload):
    if not isinstance(payload, dict):
        return None
    kind = payload.get("__biga__")
    if kind == "df":
        import pandas as pd

        data = payload.get("data") or {}
        frame = pd.DataFrame(
            data.get("data") or [],
            columns=data.get("columns"),
            index=data.get("index"),
        )
        if "date" in frame.columns:
            frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        attrs = payload.get("attrs") or {}
        if isinstance(attrs, dict):
            frame.attrs.update(attrs)
        return frame
    if kind == "dict":
        data = payload.get("data")
        return dict(data) if isinstance(data, dict) else {}
    if kind == "list":
        data = payload.get("data")
        return list(data) if isinstance(data, list) else []
    if kind == "json":
        return payload.get("data")
    return None


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

    def get_entry(self, key, allow_expired=False, max_stale_age=None):
        if not self.enabled:
            return None
        with self._lock:
            entry = self._store.get(key)
            if not entry:
                return None
            if not entry.ok:
                return None
            if entry.expired(self.now()) and not allow_expired:
                return None
            if allow_expired and max_stale_age is not None:
                if entry.age_seconds(self.now()) > float(max_stale_age):
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
        if not ok:
            self.set_cooldown(key, ttl)
            return None
        with self._lock:
            if ttl <= 0:
                self._store.pop(key, None)
                return None
            self._evict_if_needed()
            entry = CacheEntry(
                value=_copy_value(value),
                expires_at=now + ttl,
                fetched_at=float(fetched_at if fetched_at is not None else now),
                ok=True,
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
    """内存 + JSON 磁盘 + 跨进程文件锁合并。失败冷却不覆盖最后好数据。"""

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
        stale_max_age=259200,
        lock_timeout=8,
    ):
        super().__init__(max_size=max_size, default_ttl=default_ttl, enabled=enabled, clock=clock)
        self.persist = bool(persist)
        self.directory = Path(directory) if directory else None
        self.failure_ttl = int(failure_ttl)
        self.success_max_ttl = int(success_max_ttl)
        self.realtime_ttl = int(realtime_ttl)
        self.stale_max_age = int(stale_max_age)
        self.lock_timeout = float(lock_timeout)
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
        return self.directory / f"biga-{CACHE_FORMAT}-{safe}.json"

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
            raw = path.read_bytes()
        except OSError as exc:
            logger.warning("读取磁盘缓存失败: %s", exc)
            return None
        if not raw.startswith(CACHE_MAGIC):
            logger.warning("拒绝不可信/非本格式缓存: %s", path.name)
            try:
                path.unlink()
            except OSError:
                pass
            return None
        try:
            payload = json.loads(raw[len(CACHE_MAGIC) :].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            logger.warning("磁盘缓存损坏，已丢弃: %s", exc)
            try:
                path.unlink()
            except OSError:
                pass
            return None
        if not isinstance(payload, dict) or payload.get("format") != CACHE_FORMAT:
            return None
        if not payload.get("ok", True):
            return None
        try:
            value = decode_cache_value(payload.get("value"))
        except Exception as exc:
            logger.warning("磁盘缓存反序列化失败: %s", exc)
            try:
                path.unlink()
            except OSError:
                pass
            return None
        return CacheEntry(
            value=value,
            expires_at=float(payload.get("expires_at") or 0),
            fetched_at=float(payload.get("fetched_at") or 0),
            ok=True,
            source=payload.get("source"),
            session=payload.get("session"),
            key=key,
        )

    def _write_disk(self, key, entry: CacheEntry):
        path = self._disk_path(key)
        if not self.persist or path is None or not entry.ok:
            return
        payload = {
            "format": CACHE_FORMAT,
            "value": encode_cache_value(entry.value),
            "expires_at": entry.expires_at,
            "fetched_at": entry.fetched_at,
            "ok": True,
            "source": entry.source,
            "session": entry.session,
            "key": key,
        }
        fd, tmp_name = tempfile.mkstemp(prefix=".biga-cache.", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(CACHE_MAGIC)
                handle.write(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, path)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        except Exception as exc:
            logger.warning("写入磁盘缓存失败: %s", exc)
            try:
                os.unlink(tmp_name)
            except OSError:
                pass

    def _with_file_lock(self, key, fn, timeout=None):
        lock_path = self._lock_path(key)
        timeout = self.lock_timeout if timeout is None else float(timeout)
        if not self.persist or lock_path is None or fcntl is None:
            return fn()
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + max(0.0, timeout)
        handle = lock_path.open("a+")
        try:
            while True:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("cache lock timeout")
                    time.sleep(0.05)
            try:
                handle.seek(0)
                handle.truncate()
                handle.write(str(os.getpid()))
                handle.flush()
            except OSError:
                pass
            return fn()
        finally:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                handle.close()
            except OSError:
                pass

    def get_entry(self, key, allow_expired=False, max_stale_age=None):
        entry = super().get_entry(key, allow_expired=allow_expired)
        if entry is None:
            disk = self._read_disk(key)
            if disk is None:
                return None
            now = self.now()
            if disk.expired(now) and not allow_expired:
                return None
            remaining = max(1, int(disk.expires_at - now)) if not disk.expired(now) else 1
            if not disk.expired(now):
                super().set(
                    key,
                    disk.value,
                    ttl=remaining,
                    ok=True,
                    source=disk.source,
                    session=disk.session,
                    fetched_at=disk.fetched_at,
                )
            entry = disk
        if entry is None or not entry.ok:
            return None
        cap = self.stale_max_age if max_stale_age is None else max_stale_age
        if allow_expired and cap is not None and entry.age_seconds(self.now()) > float(cap):
            return None
        return entry

    def set(self, key, value, ttl=None, ok=True, source=None, session=None, fetched_at=None):
        if not ok:
            self.set_cooldown(key, ttl if ttl is not None else self.failure_ttl)
            return None
        entry = super().set(
            key,
            value,
            ttl=ttl,
            ok=True,
            source=source,
            session=session,
            fetched_at=fetched_at,
        )
        if entry is not None:
            self._write_disk(key, entry)
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

    def coalesce(self, key, loader, timeout=None):
        """同一 key 进程内单飞；跨进程用 flock。timeout 同时约束等待与锁。"""
        timeout = self.lock_timeout if timeout is None else float(timeout)
        with self._inflight_lock:
            box = self._inflight.get(key)
            owner = box is None
            if owner:
                box = _FutureBox()
                self._inflight[key] = box
        if not owner:
            return box.result(timeout=timeout)
        try:
            result = self._with_file_lock(key, loader, timeout=timeout)
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


def bound_stale_age(cfg=None):
    cfg = cfg or get_data_config()
    return max(60, min(int(getattr(cfg.cache, "ttl_stale_max", 259200) or 259200), 7 * 86400))


def bound_lock_timeout(cfg=None):
    cfg = cfg or get_data_config()
    return max(1.0, min(float(getattr(cfg.cache, "lock_timeout", 8) or 8), 30.0))


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
    max_stale_age=None,
    lock_timeout=None,
):
    """
    命中新鲜缓存则返回；并发请求合并；失败短冷却与好数据分离。
    空表/异常不得覆盖最后好缓存；失败命中 fresh=False；陈旧回退受最大年龄门控。
    """
    is_success = is_success or _is_success
    session = session or session_bucket()
    if cache is None:
        cache = get_cache()
    stale_cap = max_stale_age
    if stale_cap is None:
        stale_cap = getattr(cache, "stale_max_age", None) or bound_stale_age()
    lock_wait = lock_timeout
    if lock_wait is None:
        lock_wait = getattr(cache, "lock_timeout", None) or bound_lock_timeout()

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

    def _stale_good():
        if not hasattr(cache, "get_entry"):
            return None
        return cache.get_entry(key, allow_expired=True, max_stale_age=stale_cap)

    def _failure_frame(hit):
        stale = _stale_good()
        if stale is not None and stale.ok:
            return _from_entry(stale, "stale", stale=True)
        if default is not None:
            return stamp_cache_meta(default, hit=hit, stale=False, source=source, session=session)
        return None

    if hasattr(cache, "in_cooldown") and cache.in_cooldown(key):
        cooled = _failure_frame("cooldown")
        if cooled is not None:
            return cooled

    fresh = cache.get_entry(key, allow_expired=False) if hasattr(cache, "get_entry") else None
    if fresh is not None and getattr(fresh, "ok", True):
        return _from_entry(fresh, "fresh", stale=False)

    def _load():
        again = cache.get_entry(key, allow_expired=False) if hasattr(cache, "get_entry") else cache.get(key)
        if again is not None and hasattr(again, "value") and getattr(again, "ok", True):
            return _from_entry(again, "coalesced", stale=False)
        if again is not None and not hasattr(again, "value"):
            return stamp_cache_meta(again, hit="coalesced", source=source, session=session)
        try:
            value = loader()
        except Exception:
            if hasattr(cache, "set_cooldown"):
                cache.set_cooldown(key, failure_ttl)
            good = _stale_good()
            if good is not None and good.ok:
                return _from_entry(good, "stale", stale=True)
            raise
        if value is None:
            value = default
        ok = is_success(value)
        if not ok:
            if hasattr(cache, "set_cooldown"):
                cache.set_cooldown(key, failure_ttl)
            stale = _stale_good()
            if stale is not None and stale.ok:
                return _from_entry(stale, "stale", stale=True)
            return stamp_cache_meta(
                value if value is not None else default,
                hit="failure",
                stale=False,
                source=source,
                session=session,
            )
        setter = getattr(cache, "set")
        setter(key, value, ttl=int(success_ttl), ok=True, source=source, session=session)
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
            return coalesce(key, _load, timeout=lock_wait)
        except TimeoutError:
            labeled = _failure_frame("stale")
            if labeled is not None:
                return labeled
            if default is not None:
                return stamp_cache_meta(default, hit="failure", stale=False, source=source, session=session)
            raise
        except Exception:
            good = _stale_good()
            if good is not None and good.ok:
                return _from_entry(good, "stale", stale=True)
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
                stale_max_age=getattr(cfg.cache, "ttl_stale_max", 259200),
                lock_timeout=getattr(cfg.cache, "lock_timeout", 8),
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
            _CACHE.stale_max_age = getattr(cfg.cache, "ttl_stale_max", 259200)
            _CACHE.lock_timeout = getattr(cfg.cache, "lock_timeout", 8)
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
