"""带超时、有界重试、上游闸门与真实诊断的外部调用封装。"""

from __future__ import annotations

import logging
import os
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

logger = logging.getLogger("biga.data.fetch")

# 东财 push2 / datacenter 与 TuShare *_dc 是同一上游，传输故障不得当独立备用。
SAME_UPSTREAM_EASTMONEY = frozenset(
    {
        "get_market_fund_flow",
        "get_sector_fund_flow",
        "get_stock_fund_flow_rank",
        "get_fund_flow",
    }
)

# 授权/无 token 允许换客户端，但不把同源叫独立源。
_AUTH_PEER_REASONS = frozenset({"permission", "no_token", "unavailable", "auth"})
_TRANSPORT_PEER_REASONS = frozenset(
    {
        "transport",
        "timeout",
        "disconnect",
        "empty",
        "rate_limit_heuristic",
        "http_429",
        "http_5xx",
        "http_4xx",
        "http_403",
        "non_json",
    }
)

_SECRET_RE = re.compile(
    r"(?i)(token|api[_-]?key|secret|password|authorization)\s*[:=]\s*([^\s,;]+)"
)
_BEARER_RE = re.compile(r"(?i)(authorization\s*:\s*(?:bearer|token|basic)\s+)(\S+)")
_HEADER_AUTH_RE = re.compile(r"(?i)((?:x-)?(?:api[_-]?key|access[_-]?token|auth[_-]?token)\s*[:=]\s*)(\S+)")
_LONG_TOKEN_RE = re.compile(r"\b([A-Za-z0-9_-]{24,})\b")

_DISCONNECT_MARKERS = (
    "remotedisconnected",
    "connectionreset",
    "connection aborted",
    "connectionaborted",
    "brokenpipe",
    "connection refused",
    "connectionrefused",
    "connectionerror",
    "protocolerror",
    "disconnected",
    "connection broken",
    "temporarily unavailable",
)
_TIMEOUT_MARKERS = (
    "timeout",
    "timed out",
    "time out",
    "调用超时",
)
_EMPTY_MARKERS = (
    "empty frame",
    "upstream empty",
    "no data",
)
_NON_JSON_MARKERS = (
    "jsondecode",
    "json decode",
    "expecting value",
    "not valid json",
    "unparseable",
    "xmlparse",
)
_PERMISSION_MARKERS = (
    "permission",
    "unauthorized",
    "积分不足",
    "没有权限",
    "无权限",
    "token invalid",
    "invalid token",
    "未配置 tushare_token",
)

EASTMONEY_LIMIT = 2
TUSHARE_LIMIT = 2
GATE_ACQUIRE_TIMEOUT = 12
ISOLATED_MAX_WORKERS = 2


def _limit_from_env(name, default):
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return int(default)
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return int(default)


class DataFetchError(Exception):
    """可重试的数据获取失败。"""

    retryable = True
    category = "unknown"
    http_status = None
    retry_after = None


class EmptyDataError(DataFetchError):
    retryable = False
    category = "empty"


class RateLimitError(DataFetchError):
    """仅在观测到 HTTP 429 时使用。启发式限流文案不得升格为本类。"""

    retryable = False
    category = "http_429"


class FetchCancelled(DataFetchError):
    retryable = False
    category = "timeout"


class InFlightBusy(DataFetchError):
    """同键仍有超时后的后台线程在途，拒绝再开一条。"""

    retryable = False
    category = "timeout"


class GateTimeout(DataFetchError):
    retryable = False
    category = "timeout"


@dataclass
class FetchDiagnostic:
    category: str = "unknown"
    http_status: int | None = None
    retry_after: float | None = None
    elapsed_ms: int = 0
    attempts: int = 0
    cache_source: str | None = None
    label: str = ""
    message: str = ""
    exception_type: str = ""
    hint: str = ""

    def as_issue(self):
        status = self.http_status if self.http_status is not None else "unknown"
        text = f"fetch:{self.category}:http={status}"
        if self.hint:
            text = f"{text}:{self.hint}"
        return text

    def as_dict(self):
        return {
            "category": self.category,
            "http_status": self.http_status,
            "retry_after": self.retry_after,
            "elapsed_ms": int(self.elapsed_ms),
            "attempts": int(self.attempts),
            "cache_source": self.cache_source,
            "label": self.label,
            "message": self.message,
            "exception_type": self.exception_type,
            "hint": self.hint,
        }


_CONTEXT = threading.local()
_LAST_DIAG = threading.local()
_INFLIGHT = {}
_INFLIGHT_LOCK = threading.Lock()
_GATES = {}
_GATES_LOCK = threading.Lock()

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None


def redact_text(value):
    """脱敏 Authorization/Bearer/API key/token 及异常链。测试只用明显假 token。"""
    if value is None:
        return ""
    if isinstance(value, BaseException):
        parts = []
        for item in _walk_exceptions(value):
            parts.append(str(item))
        text = " | ".join(parts)
    else:
        text = str(value)
    text = _BEARER_RE.sub(r"\1<redacted>", text)
    text = _HEADER_AUTH_RE.sub(r"\1<redacted>", text)
    text = _SECRET_RE.sub(r"\1=<redacted>", text)
    lowered = text.lower()
    if "tushare" in lowered or "token" in lowered or "authorization" in lowered:
        text = _LONG_TOKEN_RE.sub("<redacted>", text)
    return text


def _walk_exceptions(exc):
    seen = set()
    current = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = getattr(current, "__cause__", None) or getattr(current, "__context__", None)


def extract_http_status(exc):
    for item in _walk_exceptions(exc):
        for attr in ("status_code", "status", "code", "http_status"):
            value = getattr(item, attr, None)
            if isinstance(value, int) and 100 <= value <= 599:
                return int(value)
            if isinstance(value, str) and value.isdigit():
                number = int(value)
                if 100 <= number <= 599:
                    return number
        response = getattr(item, "response", None)
        if response is not None:
            code = getattr(response, "status_code", None) or getattr(response, "status", None)
            if isinstance(code, int) and 100 <= code <= 599:
                return int(code)
    return None


def extract_retry_after(exc):
    for item in _walk_exceptions(exc):
        direct = getattr(item, "retry_after", None)
        parsed = _parse_retry_after(direct)
        if parsed is not None:
            return parsed
        response = getattr(item, "response", None)
        headers = getattr(response, "headers", None) if response is not None else None
        if not headers and hasattr(item, "headers"):
            headers = item.headers
        if headers:
            try:
                raw = headers.get("Retry-After") or headers.get("retry-after")
            except Exception:
                raw = None
            parsed = _parse_retry_after(raw)
            if parsed is not None:
                return parsed
    return None


def _parse_retry_after(raw):
    if raw is None or raw is False:
        return None
    if isinstance(raw, (int, float)):
        if float(raw) >= 0:
            return float(raw)
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        value = float(text)
        if value >= 0:
            return value
    except (TypeError, ValueError):
        pass
    try:
        parsed = parsedate_to_datetime(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        delta = (parsed - datetime.now(timezone.utc)).total_seconds()
        return max(0.0, float(delta))
    except (TypeError, ValueError, OverflowError):
        return None
    return None


def classify_exception(exc):
    """
    按实际能观测到的信号分类。
    Push2RateLimitError / 文案「限流」在无 HTTP 码时是 rate_limit_heuristic，不是 429。
    有明确 RemoteDisconnected cause 仍记 disconnect。
    """
    if exc is None:
        return FetchDiagnostic(category="unknown")
    if isinstance(exc, FetchDiagnostic):
        return exc

    status = extract_http_status(exc)
    retry_after = extract_retry_after(exc)
    names = " ".join(type(item).__name__ for item in _walk_exceptions(exc))
    messages = " ".join(str(item) for item in _walk_exceptions(exc))
    blob = f"{names} {messages}".lower()
    hint = ""

    category = "unknown"
    if status == 429:
        category = "http_429"
    elif status == 403:
        category = "http_403"
    elif status == 401:
        category = "permission"
    elif status == 408:
        category = "timeout"
        hint = "http_408"
    elif status is not None and 500 <= int(status) <= 599:
        category = "http_5xx"
        hint = f"http_{status}"
    elif status is not None and 400 <= int(status) < 500:
        category = "http_4xx"
        hint = f"http_{status}"
    elif isinstance(exc, GateTimeout):
        category = "timeout"
        hint = "upstream_gate"
    elif isinstance(exc, InFlightBusy):
        category = "timeout"
        hint = "inflight"
    elif isinstance(exc, (TimeoutError, FutureTimeout, FetchCancelled)) or any(
        marker in blob for marker in _TIMEOUT_MARKERS
    ):
        category = "timeout"
    elif any(marker in blob for marker in _DISCONNECT_MARKERS):
        category = "disconnect"
    elif any(marker in blob for marker in _NON_JSON_MARKERS):
        category = "non_json"
    elif isinstance(exc, EmptyDataError) or any(marker in blob for marker in _EMPTY_MARKERS):
        category = "empty"
    elif any(marker in blob for marker in _PERMISSION_MARKERS):
        category = "permission"
    else:
        category = "unknown"

    heuristic = "push2ratelimiterror" in blob or ("限流" in messages and status != 429)
    if heuristic:
        hint = hint or "upstream_rate_limit_heuristic"
        if category == "unknown":
            if any(marker in blob for marker in _DISCONNECT_MARKERS):
                category = "disconnect"
            else:
                category = "rate_limit_heuristic"

    diag = FetchDiagnostic(
        category=category,
        http_status=status,
        retry_after=retry_after,
        message=redact_text(messages)[:400],
        exception_type=type(exc).__name__,
        hint=hint,
    )
    return diag


def is_rate_limited(exc):
    """只有观测到 HTTP 429 才算限流。"""
    if isinstance(exc, RateLimitError):
        return True
    return extract_http_status(exc) == 429


def same_upstream_peer_allowed(method, reason=None):
    """
    同源东财：传输故障拒绝备用（避免双打）；授权/无 token 允许换客户端。
    允许时仍须标明 same_upstream_degrade，不得称为独立源。
    """
    if method not in SAME_UPSTREAM_EASTMONEY:
        return True
    if reason in _AUTH_PEER_REASONS:
        return True
    if reason in _TRANSPORT_PEER_REASONS:
        return False
    if reason is None:
        diag = last_fetch_diagnostic()
        if diag is not None and diag.category in ("permission",):
            return True
        if diag is None:
            return False
        return diag.category in ("permission",)
    return False


def infer_peer_reason(*, available=True, has_token=True, frame=None, exc=None):
    if not available:
        return "no_token" if not has_token else "unavailable"
    if exc is not None:
        category = classify_exception(exc).category
        if category == "permission":
            return "permission"
        return "transport"
    blob_parts = []
    if frame is not None and hasattr(frame, "attrs"):
        blob_parts.extend(str(item) for item in (frame.attrs.get("issues") or []))
        blob_parts.append(str(frame.attrs.get("error") or ""))
    blob = " ".join(blob_parts)
    if any(marker in blob for marker in _PERMISSION_MARKERS) or "积分" in blob:
        return "permission"
    diag = last_fetch_diagnostic()
    if diag is not None and diag.category == "permission":
        return "permission"
    if diag is not None and diag.category in _TRANSPORT_PEER_REASONS:
        return "transport"
    return "transport"


def mark_same_upstream_degrade(frame, method):
    if frame is None or method not in SAME_UPSTREAM_EASTMONEY or not hasattr(frame, "attrs"):
        return frame
    issues = list(frame.attrs.get("issues") or [])
    marker = "same_upstream_degrade:eastmoney"
    if marker not in issues:
        issues.append(marker)
    frame.attrs["issues"] = issues
    frame.attrs["independent_backup"] = False
    return frame


def current_deadline():
    return getattr(_CONTEXT, "deadline", None)


def current_cancelled():
    return getattr(_CONTEXT, "cancelled", None)


def fetch_cancelled():
    flag = current_cancelled()
    if flag is not None and flag.is_set():
        return True
    deadline = current_deadline()
    return bool(deadline is not None and time.monotonic() >= deadline)


def raise_if_cancelled():
    if fetch_cancelled():
        raise FetchCancelled("fetch cancelled after timeout/budget")


def last_fetch_diagnostic():
    return getattr(_LAST_DIAG, "value", None)


def set_last_fetch_diagnostic(diag):
    _LAST_DIAG.value = diag
    return diag


def _push_context(deadline, cancelled):
    prev = (getattr(_CONTEXT, "deadline", None), getattr(_CONTEXT, "cancelled", None))
    _CONTEXT.deadline = deadline
    _CONTEXT.cancelled = cancelled
    return prev


def _pop_context(prev):
    _CONTEXT.deadline, _CONTEXT.cancelled = prev


def _gate_directory():
    try:
        from .config import cache_dir

        return cache_dir()
    except Exception:
        return Path(os.environ.get("BIGA_CACHE_DIR") or "data/cache")


class GateLease:
    """闸门占用覆盖真实 worker 存活；超时返回后仍持有直到线程结束。进程退出由 OS 回收。"""

    def __init__(self, local, handle, name):
        self._local = local
        self._handle = handle
        self.name = name
        self._worker = None
        self._released = False
        self._lock = threading.Lock()

    def attach_worker(self, thread):
        self._worker = thread

    def release(self):
        with self._lock:
            if self._released:
                return
            self._released = True
            handle = self._handle
            self._handle = None
            if handle is not None:
                try:
                    if fcntl is not None:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
                try:
                    handle.close()
                except OSError:
                    pass
            try:
                self._local.release()
            except ValueError:
                pass

    def release_when_idle(self):
        worker = self._worker
        if worker is not None and worker.is_alive():
            def _reap():
                worker.join()
                self.release()

            threading.Thread(target=_reap, name=f"biga-gate-reap-{self.name}", daemon=True).start()
            return
        self.release()


class _FileSemaphore:
    """跨进程有界并发。崩溃由 OS 释放 flock；挂起的 owner 只阻塞到 timeout。"""

    def __init__(self, name, limit, timeout=GATE_ACQUIRE_TIMEOUT, directory=None):
        self.name = name
        self.limit = max(1, int(limit))
        self.timeout = float(timeout)
        self.directory = Path(directory) if directory is not None else _gate_directory()
        self._local = threading.BoundedSemaphore(self.limit)
        self._held = threading.local()

    def acquire(self, timeout=None):
        timeout = self.timeout if timeout is None else float(timeout)
        deadline = time.monotonic() + max(0.0, timeout)
        wait = max(0.0, deadline - time.monotonic())
        if not self._local.acquire(timeout=wait):
            raise GateTimeout(f"upstream gate busy: {self.name}")
        try:
            handle = self._acquire_slot(deadline)
            lease = GateLease(self._local, handle, self.name)
            self._held.lease = lease
            return lease
        except Exception:
            self._local.release()
            raise

    def _acquire_slot(self, deadline):
        if fcntl is None:
            return None
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            return None
        while True:
            for index in range(self.limit):
                path = self.directory / f"gate-{self.name}-{index}.lock"
                handle = path.open("a+")
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    try:
                        handle.seek(0)
                        handle.truncate()
                        handle.write(str(os.getpid()))
                        handle.flush()
                    except OSError:
                        pass
                    return handle
                except BlockingIOError:
                    try:
                        handle.close()
                    except OSError:
                        pass
                    continue
                except OSError:
                    try:
                        handle.close()
                    except OSError:
                        pass
                    continue
            if time.monotonic() >= deadline:
                raise GateTimeout(f"upstream gate timeout: {self.name}")
            time.sleep(0.05)

    def release(self):
        lease = getattr(self._held, "lease", None)
        if lease is not None:
            lease.release()
            self._held.lease = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, exc_type, exc, tb):
        lease = getattr(self._held, "lease", None)
        if lease is not None:
            lease.release_when_idle()
            self._held.lease = None
        return False


def upstream_gate(name="eastmoney", limit=None, timeout=None, directory=None):
    key = str(name or "other")
    if key in ("eastmoney", "akshare"):
        cap = _limit_from_env("BIGA_EASTMONEY_LIMIT", EASTMONEY_LIMIT) if limit is None else int(limit)
        key = "eastmoney"
    elif key == "tushare":
        cap = _limit_from_env("BIGA_TUSHARE_LIMIT", TUSHARE_LIMIT) if limit is None else int(limit)
    else:
        cap = 4 if limit is None else int(limit)
    with _GATES_LOCK:
        gate = _GATES.get(key)
        if gate is None or (directory is not None and Path(directory) != gate.directory):
            gate = _FileSemaphore(
                key,
                cap,
                timeout=GATE_ACQUIRE_TIMEOUT if timeout is None else timeout,
                directory=directory,
            )
            _GATES[key] = gate
        elif timeout is not None:
            gate.timeout = float(timeout)
        return gate


def reset_upstream_gates():
    with _GATES_LOCK:
        _GATES.clear()


def call_with_timeout(func, timeout, *args, inflight_key=None, gate_lease=None, **kwargs):
    """
    在 daemon 线程中执行调用。timeout<=0 表示不限时。

    无法强制终止第三方（AKShare 分页）线程：超时后立刻把错误返回给调用方。
    同 inflight_key 在途时拒绝再开一条，避免叠加。进程退出不因这些线程卡住
    （daemon）。threading.local 的 cancel 不会传到 worker，不要宣称能停上游分页。
    """
    if not timeout or timeout <= 0:
        raise_if_cancelled()
        return func(*args, **kwargs)
    key = inflight_key or None
    if key:
        with _INFLIGHT_LOCK:
            existing = _INFLIGHT.get(key)
            if existing is not None and existing.is_alive():
                raise InFlightBusy(f"in-flight {key}: skip stacked call")
    cancelled = current_cancelled() or threading.Event()
    deadline = time.monotonic() + float(timeout)
    prev = _push_context(deadline, cancelled)
    box = {"value": None, "error": None}

    def runner():
        try:
            box["value"] = func(*args, **kwargs)
        except Exception as exc:
            box["error"] = exc

    thread = threading.Thread(
        target=runner,
        name=f"biga-fetch-{key or getattr(func, '__name__', 'anon')}",
        daemon=True,
    )
    if key:
        with _INFLIGHT_LOCK:
            current = _INFLIGHT.get(key)
            if current is not None and current.is_alive():
                raise InFlightBusy(f"in-flight {key}: skip stacked call")
            _INFLIGHT[key] = thread
    thread.start()
    if gate_lease is not None:
        gate_lease.attach_worker(thread)
    try:
        thread.join(timeout)
        if thread.is_alive():
            cancelled.set()
            raise DataFetchError(f"调用超时（{timeout}s）: {func}")
        if box["error"] is not None:
            raise box["error"]
        return box["value"]
    finally:
        if key and not thread.is_alive():
            with _INFLIGHT_LOCK:
                if _INFLIGHT.get(key) is thread:
                    _INFLIGHT.pop(key, None)
        _pop_context(prev)


def inflight_alive(key):
    with _INFLIGHT_LOCK:
        thread = _INFLIGHT.get(key)
        return bool(thread is not None and thread.is_alive())


def _retryable_category(category, status=None):
    if category in (
        "http_429",
        "http_403",
        "http_4xx",
        "permission",
        "empty",
        "non_json",
        "timeout",
        "rate_limit_heuristic",
    ):
        return False
    if category in ("disconnect", "http_5xx"):
        return True
    if status is not None and 500 <= int(status) <= 599:
        return True
    if status is not None and 400 <= int(status) < 500:
        return False
    return category == "unknown"


def _backoff_seconds(delay, attempt, jitter=True):
    base = float(delay) * (2 ** max(attempt - 1, 0))
    if jitter:
        base *= 0.5 + random.random()
    return max(0.0, base)


def with_retry(
    func,
    retries=3,
    timeout=30,
    delay=0.8,
    retry_exceptions=None,
    budget=None,
    jitter=True,
    label="",
    inflight_key=None,
    gate_lease=None,
):
    """
    执行 func()，失败则有界退避。总时间受 budget 约束。
    超时/启发式限流/4xx 不重试。HTTP 429 最多尊重一次 Retry-After（数字或 HTTP-date）。
    无法杀掉第三方线程；同键在途则跳过叠加。
    """
    retry_exceptions = retry_exceptions or (
        DataFetchError,
        TimeoutError,
        ConnectionError,
        OSError,
    )
    attempts = max(int(retries), 1)
    timeout = float(timeout or 0)
    started = time.monotonic()
    if budget is None:
        budget = timeout * attempts + float(delay) * max(attempts - 1, 0) + 1.0
    budget = float(budget)
    deadline = started + budget
    cancelled = threading.Event()
    prev = _push_context(deadline, cancelled)
    last_error = None
    last_diag = FetchDiagnostic(label=label)
    respected_retry_after = False
    key = inflight_key or label or None
    try:
        for attempt in range(1, attempts + 1):
            raise_if_cancelled()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                last_diag.category = "timeout"
                last_diag.hint = "budget_exhausted"
                last_diag.attempts = attempt - 1
                last_diag.elapsed_ms = int((time.monotonic() - started) * 1000)
                set_last_fetch_diagnostic(last_diag)
                raise DataFetchError("retry budget exhausted")
            attempt_timeout = timeout if timeout > 0 else remaining
            if timeout > 0:
                attempt_timeout = min(timeout, remaining)
            try:
                result = call_with_timeout(
                    func, attempt_timeout, inflight_key=key, gate_lease=gate_lease
                )
                last_diag.attempts = attempt
                last_diag.elapsed_ms = int((time.monotonic() - started) * 1000)
                last_diag.category = "ok"
                last_diag.hint = ""
                last_diag.message = ""
                set_last_fetch_diagnostic(last_diag)
                return result
            except EmptyDataError:
                raise
            except RateLimitError as exc:
                last_diag = classify_exception(exc)
                last_diag.attempts = attempt
                last_diag.elapsed_ms = int((time.monotonic() - started) * 1000)
                last_diag.label = label
                set_last_fetch_diagnostic(last_diag)
                raise
            except FetchCancelled:
                raise
            except InFlightBusy as exc:
                last_diag = classify_exception(exc)
                last_diag.attempts = attempt
                last_diag.elapsed_ms = int((time.monotonic() - started) * 1000)
                last_diag.label = label
                set_last_fetch_diagnostic(last_diag)
                raise
            except Exception as exc:
                last_error = exc
                diag = classify_exception(exc)
                diag.attempts = attempt
                diag.elapsed_ms = int((time.monotonic() - started) * 1000)
                diag.label = label
                last_diag = diag
                set_last_fetch_diagnostic(diag)
                if diag.category == "http_429" or is_rate_limited(exc):
                    wait = diag.retry_after
                    if wait is not None and not respected_retry_after:
                        remaining = deadline - time.monotonic()
                        if wait >= 0 and wait <= remaining:
                            respected_retry_after = True
                            logger.warning(
                                "HTTP 429，等待 Retry-After %.1fs（%s）",
                                wait,
                                redact_text(label),
                            )
                            time.sleep(wait)
                            continue
                    wrapped = RateLimitError(redact_text(exc))
                    wrapped.http_status = 429
                    wrapped.retry_after = diag.retry_after
                    raise wrapped from exc
                if diag.category == "timeout":
                    cancelled.set()
                    if isinstance(exc, DataFetchError):
                        raise
                    raise DataFetchError(redact_text(exc)) from exc
                if diag.category == "rate_limit_heuristic":
                    if isinstance(exc, DataFetchError):
                        raise
                    raise DataFetchError(redact_text(exc)) from exc
                retryable = diag.category == "disconnect" or (
                    _retryable_category(diag.category, diag.http_status)
                    and (isinstance(exc, retry_exceptions) or diag.category in ("unknown", "http_5xx"))
                )
                if (not retryable) or attempt >= attempts:
                    if isinstance(exc, DataFetchError):
                        raise
                    raise DataFetchError(redact_text(exc)) from exc
                sleep_for = _backoff_seconds(delay, attempt, jitter=jitter)
                remaining = deadline - time.monotonic()
                if sleep_for > remaining:
                    cancelled.set()
                    raise DataFetchError(redact_text(exc)) from exc
                logger.warning(
                    "数据请求失败（%s/%s, category=%s, http=%s）: %s",
                    attempt,
                    attempts,
                    diag.category,
                    diag.http_status if diag.http_status is not None else "unknown",
                    redact_text(exc),
                )
                if sleep_for:
                    time.sleep(sleep_for)
        raise DataFetchError(redact_text(last_error)) from last_error
    finally:
        last_diag.elapsed_ms = int((time.monotonic() - started) * 1000)
        set_last_fetch_diagnostic(last_diag)
        _pop_context(prev)


def safe_fetch(
    func,
    retries=3,
    timeout=30,
    default=None,
    label="",
    budget=None,
    delay=0.8,
    upstream=None,
):
    """捕获全部异常，失败时返回 default，供页面侧优雅降级。"""

    def _call(gate_lease=None):
        return with_retry(
            func,
            retries=retries,
            timeout=timeout,
            delay=delay,
            budget=budget,
            label=label,
            inflight_key=label or None,
            gate_lease=gate_lease,
        )

    lease = None
    try:
        if upstream:
            remaining = None
            if budget:
                remaining = float(budget)
            gate = upstream_gate(
                upstream, timeout=min(GATE_ACQUIRE_TIMEOUT, remaining or GATE_ACQUIRE_TIMEOUT)
            )
            lease = gate.acquire()
            return _call(gate_lease=lease)
        return _call()
    except Exception as exc:
        diag = last_fetch_diagnostic() or classify_exception(exc)
        diag.label = label or diag.label
        diag.message = redact_text(diag.message or exc)
        set_last_fetch_diagnostic(diag)
        logger.warning(
            "safe_fetch %s 失败 category=%s http=%s attempts=%s elapsed_ms=%s: %s",
            redact_text(label or getattr(func, "__name__", func)),
            diag.category,
            diag.http_status if diag.http_status is not None else "unknown",
            diag.attempts,
            diag.elapsed_ms,
            redact_text(exc),
        )
        if default is not None and hasattr(default, "attrs"):
            try:
                default = default.copy()
                default.attrs["fetch_diagnostic"] = diag.as_dict()
                issues = list(default.attrs.get("issues") or [])
                issue = diag.as_issue()
                if issue not in issues:
                    issues.append(issue)
                default.attrs["issues"] = issues
            except Exception:
                pass
        return default
    finally:
        if lease is not None:
            lease.release_when_idle()


def run_isolated(jobs, timeout=None, max_workers=None):
    """
    并行执行互不依赖的任务，单腿超时互不影响。
    默认最多 2 个 worker，再叠加上游闸门，避免 Web 5 路 / CLI 3 路齐打同一东财。
    不靠加大 timeout。其它数据源走独立闸门，避免交叉锁死。
    """
    jobs = dict(jobs or {})
    if not jobs:
        return {}
    results = {name: None for name in jobs}

    def _run(name, func):
        raise_if_cancelled()
        if timeout and timeout > 0:
            return call_with_timeout(func, timeout, inflight_key=f"isolated:{name}")
        return func()

    workers = min(len(jobs), ISOLATED_MAX_WORKERS if max_workers is None else int(max_workers))
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futs = {pool.submit(_run, name, func): name for name, func in jobs.items()}
        for fut in as_completed(futs):
            name = futs[fut]
            try:
                results[name] = fut.result()
            except Exception as exc:
                diag = classify_exception(exc)
                logger.warning(
                    "isolated %s 失败 category=%s http=%s: %s",
                    name,
                    diag.category,
                    diag.http_status if diag.http_status is not None else "unknown",
                    redact_text(exc),
                )
                results[name] = None
    return results
