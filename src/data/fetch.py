"""带超时、有界重试与真实诊断的外部调用封装。"""

from __future__ import annotations

import logging
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass

logger = logging.getLogger("biga.data.fetch")

# 东财 push2 / datacenter 与 TuShare *_dc 是同一上游，不能当独立备用。
SAME_UPSTREAM_EASTMONEY = frozenset(
    {
        "get_market_fund_flow",
        "get_sector_fund_flow",
        "get_stock_fund_flow_rank",
        "get_fund_flow",
    }
)

_SECRET_RE = re.compile(
    r"(?i)(token|api[_-]?key|secret|password|authorization)\s*[:=]\s*([^\s,;]+)"
)
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


def redact_text(value):
    if value is None:
        return ""
    text = str(value)
    text = _SECRET_RE.sub(r"\1=<redacted>", text)
    if "tushare" in text.lower() and _LONG_TOKEN_RE.search(text):
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
    try:
        value = float(raw)
        if value >= 0:
            return value
    except (TypeError, ValueError):
        return None
    return None


def classify_exception(exc):
    """
    按实际能观测到的信号分类。取不到 HTTP 状态码就是 unknown。
    Push2RateLimitError / 文案里的「限流」不是已证实的 HTTP 429。
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
    elif status is not None:
        category = "unknown"
        hint = f"http_{status}"
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

    if "push2ratelimiterror" in blob or ("限流" in messages and status != 429):
        hint = hint or "upstream_rate_limit_heuristic"
        if category == "unknown" and any(marker in blob for marker in _DISCONNECT_MARKERS):
            category = "disconnect"

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


def call_with_timeout(func, timeout, *args, **kwargs):
    """
    在独立线程中执行调用。timeout<=0 表示不限时。

    底层线程无法被强制杀掉；超时后立刻把错误返回，并置位 cancelled，
    调用方不得再开新的分页/重试。后台线程若仍在跑，不再跟新请求。
    """
    if not timeout or timeout <= 0:
        raise_if_cancelled()
        return func(*args, **kwargs)
    cancelled = current_cancelled() or threading.Event()
    deadline = time.monotonic() + float(timeout)
    prev = _push_context(deadline, cancelled)
    pool = ThreadPoolExecutor(max_workers=1)
    future = pool.submit(func, *args, **kwargs)
    try:
        return future.result(timeout=timeout)
    except FutureTimeout as exc:
        cancelled.set()
        raise DataFetchError(f"调用超时（{timeout}s）: {func}") from exc
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
        _pop_context(prev)


def _retryable_category(category, status=None):
    if category in ("http_429", "http_403", "permission", "empty", "non_json", "timeout"):
        return False
    if category == "disconnect":
        return True
    if status is not None and 500 <= int(status) <= 599:
        return True
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
):
    """
    执行 func()，失败则有界退避。总时间受 budget 约束。
    超时不重试（避免后台分页叠加）。HTTP 429 最多尊重一次 Retry-After。
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
                result = call_with_timeout(func, attempt_timeout)
                last_diag.attempts = attempt
                last_diag.elapsed_ms = int((time.monotonic() - started) * 1000)
                last_diag.category = last_diag.category or "ok"
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
                retryable = diag.category == "disconnect" or (
                    _retryable_category(diag.category, diag.http_status)
                    and (isinstance(exc, retry_exceptions) or diag.category == "unknown")
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


def safe_fetch(func, retries=3, timeout=30, default=None, label="", budget=None, delay=0.8):
    """捕获全部异常，失败时返回 default，供页面侧优雅降级。"""
    try:
        return with_retry(
            func,
            retries=retries,
            timeout=timeout,
            delay=delay,
            budget=budget,
            label=label,
        )
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


def run_isolated(jobs, timeout=None):
    """
    并行执行互不依赖的任务，单腿超时互不影响。
    返回 {name: result}；失败腿为 None，诊断在 last job attrs / 日志。
    """
    jobs = dict(jobs or {})
    if not jobs:
        return {}
    results = {name: None for name in jobs}

    def _run(name, func):
        raise_if_cancelled()
        if timeout and timeout > 0:
            return call_with_timeout(func, timeout)
        return func()

    workers = min(len(jobs), 4)
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
