"""带超时与重试的外部调用封装。"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

logger = logging.getLogger("biga.data.fetch")


class DataFetchError(Exception):
    """可重试的数据获取失败。"""

    retryable = True


class EmptyDataError(DataFetchError):
    retryable = False


class RateLimitError(DataFetchError):
    retryable = False


_RATE_LIMIT_MARKERS = (
    "限流",
    "频繁",
    "访问过快",
    "too many",
    "rate limit",
    "rate-limit",
    "429",
)


def is_rate_limited(exc):
    message = str(exc)
    lowered = message.lower()
    return any(token in message or token in lowered for token in _RATE_LIMIT_MARKERS)


def call_with_timeout(func, timeout, *args, **kwargs):
    """
    在独立线程中执行调用。timeout<=0 表示不限时。

    注意：底层线程无法被强制杀掉；超时后用 wait=False 立即把错误返回给调用方，
    避免 ThreadPoolExecutor 上下文退出时再阻塞等任务跑完。
    """
    if not timeout or timeout <= 0:
        return func(*args, **kwargs)
    pool = ThreadPoolExecutor(max_workers=1)
    future = pool.submit(func, *args, **kwargs)
    try:
        return future.result(timeout=timeout)
    except FutureTimeout as exc:
        raise DataFetchError(f"调用超时（{timeout}s）: {func}") from exc
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def with_retry(func, retries=3, timeout=30, delay=0.8, retry_exceptions=None):
    """
    执行 func()，失败则指数退避重试。
    EmptyDataError / 限流 不会重试（避免把东财封得更久）。
    """
    retry_exceptions = retry_exceptions or (DataFetchError, TimeoutError, ConnectionError, OSError)
    attempts = max(int(retries), 1)
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            return call_with_timeout(func, timeout)
        except EmptyDataError:
            raise
        except RateLimitError:
            raise
        except Exception as exc:
            if is_rate_limited(exc):
                raise RateLimitError(str(exc)) from exc
            last_error = exc
            retryable = isinstance(exc, retry_exceptions)
            message = str(exc).lower()
            maybe_network = any(
                token in message
                for token in ("timeout", "timed out", "connection", "temporarily", "max retries")
            )
            if (not retryable and not maybe_network) or attempt >= attempts:
                if isinstance(exc, DataFetchError):
                    raise
                raise DataFetchError(str(exc)) from exc
            logger.warning("数据请求失败（%s/%s）: %s", attempt, attempts, exc)
            time.sleep(delay * (2 ** (attempt - 1)))
    raise DataFetchError(str(last_error)) from last_error


def safe_fetch(func, retries=3, timeout=30, default=None, label=""):
    """捕获全部异常，失败时返回 default，供页面侧优雅降级。"""
    try:
        return with_retry(func, retries=retries, timeout=timeout)
    except Exception as exc:
        logger.warning("safe_fetch %s 失败: %s", label or getattr(func, "__name__", func), exc)
        return default
