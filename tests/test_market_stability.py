"""行情稳定性：缓存合并/过期、失败冷却、有界重试、诊断分类。不打外网。"""

from __future__ import annotations

import sys
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from src.data.cache import SharedTTLCache, cached_load, make_cache_key, stamp_cache_meta
from src.data.calendar import expected_daily_data_date, session_bucket
from src.data.fetch import (
    SAME_UPSTREAM_EASTMONEY,
    DataFetchError,
    RateLimitError,
    classify_exception,
    is_rate_limited,
    redact_text,
    with_retry,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


class _Clock:
    def __init__(self, start=1_000.0):
        self.value = float(start)

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += float(seconds)


class Push2RateLimitError(Exception):
    pass


class RemoteDisconnected(Exception):
    pass


class HTTPError(Exception):
    def __init__(self, status, retry_after=None, text=""):
        self.status_code = status
        headers = {}
        if retry_after is not None:
            headers["Retry-After"] = str(retry_after)
        self.response = type("R", (), {"status_code": status, "headers": headers})()
        super().__init__(text or f"HTTP {status}")


class DiagnosticTests(unittest.TestCase):
    def test_push2_heuristic_is_unknown_or_disconnect_not_429(self):
        wrapped = Push2RateLimitError("提示临时限流")
        wrapped.__cause__ = RemoteDisconnected("Remote end closed connection without response")
        diag = classify_exception(wrapped)
        self.assertNotEqual(diag.category, "http_429")
        self.assertIsNone(diag.http_status)
        self.assertEqual(diag.category, "disconnect")
        self.assertIn("heuristic", diag.hint)
        self.assertFalse(is_rate_limited(wrapped))

        heuristic = Push2RateLimitError("当前 IP 被临时限流")
        diag2 = classify_exception(heuristic)
        self.assertEqual(diag2.category, "unknown")
        self.assertIsNone(diag2.http_status)
        self.assertFalse(is_rate_limited(heuristic))

    def test_http_429_and_403_are_explicit(self):
        d429 = classify_exception(HTTPError(429, retry_after=1.5))
        self.assertEqual(d429.category, "http_429")
        self.assertEqual(d429.http_status, 429)
        self.assertEqual(d429.retry_after, 1.5)
        self.assertTrue(is_rate_limited(HTTPError(429)))
        d403 = classify_exception(HTTPError(403))
        self.assertEqual(d403.category, "http_403")
        self.assertEqual(d403.http_status, 403)

    def test_timeout_empty_non_json_permission(self):
        self.assertEqual(classify_exception(TimeoutError("调用超时（30s）")).category, "timeout")
        self.assertEqual(classify_exception(ValueError("Expecting value: line 1")).category, "non_json")
        self.assertEqual(classify_exception(RuntimeError("积分不足，没有权限")).category, "permission")
        self.assertEqual(classify_exception(RuntimeError("upstream empty")).category, "empty")

    def test_redact_token_like_text(self):
        text = redact_text("token=abcdefghijklmnopqrstuvwxyz012345")
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz012345", text)
        self.assertIn("<redacted>", text)


class RetryBudgetTests(unittest.TestCase):
    def test_disconnect_retries_with_bound(self):
        calls = {"n": 0}

        def boom():
            calls["n"] += 1
            raise ConnectionError("RemoteDisconnected")

        with self.assertRaises(DataFetchError):
            with_retry(boom, retries=3, timeout=0, delay=0, jitter=False, budget=5)
        self.assertEqual(calls["n"], 3)

    def test_timeout_is_not_retried(self):
        calls = {"n": 0}

        def boom():
            calls["n"] += 1
            raise DataFetchError("调用超时（30s）: stock_market_fund_flow")

        with self.assertRaises(DataFetchError):
            with_retry(boom, retries=4, timeout=0, delay=0, jitter=False, budget=8)
        self.assertEqual(calls["n"], 1)

    def test_retry_after_respected_once(self):
        calls = {"n": 0}

        def boom():
            calls["n"] += 1
            raise HTTPError(429, retry_after=0)

        with self.assertRaises(RateLimitError):
            with_retry(boom, retries=3, timeout=0, delay=0, jitter=False, budget=5)
        self.assertEqual(calls["n"], 2)

    def test_eastmoney_not_independent_backup(self):
        self.assertIn("get_market_fund_flow", SAME_UPSTREAM_EASTMONEY)
        self.assertIn("get_sector_fund_flow", SAME_UPSTREAM_EASTMONEY)


class CacheCoalesceTests(unittest.TestCase):
    def test_concurrent_requests_merge(self):
        clock = _Clock()
        cache = SharedTTLCache(
            max_size=10, default_ttl=60, persist=False, clock=clock, directory=None
        )
        calls = {"n": 0}
        started = threading.Event()
        release = threading.Event()

        def loader():
            calls["n"] += 1
            started.set()
            release.wait(timeout=2)
            return pd.DataFrame({"v": [1]})

        results = []

        def worker():
            results.append(
                cached_load(cache, "k1", loader, success_ttl=60, failure_ttl=10, source="akshare")
            )

        threads = [threading.Thread(target=worker) for _ in range(6)]
        for thread in threads:
            thread.start()
        self.assertTrue(started.wait(timeout=2))
        release.set()
        for thread in threads:
            thread.join(timeout=2)
        self.assertEqual(calls["n"], 1)
        self.assertEqual(len(results), 6)
        self.assertTrue(all(not frame.empty for frame in results))

    def test_failure_cooldown_skips_loader(self):
        clock = _Clock()
        cache = SharedTTLCache(persist=False, clock=clock, directory=None)
        calls = {"n": 0}

        def loader():
            calls["n"] += 1
            return pd.DataFrame()

        first = cached_load(cache, "fail", loader, default=pd.DataFrame(), success_ttl=300, failure_ttl=45)
        second = cached_load(cache, "fail", loader, default=pd.DataFrame(), success_ttl=300, failure_ttl=45)
        self.assertEqual(calls["n"], 1)
        self.assertTrue(first.empty)
        self.assertTrue(second.empty)

    def test_intraday_expiry_refreshes(self):
        clock = _Clock()
        cache = SharedTTLCache(persist=False, clock=clock, directory=None, realtime_ttl=30)
        calls = {"n": 0}

        def loader():
            calls["n"] += 1
            return pd.DataFrame({"v": [calls["n"]]})

        cached_load(cache, "rt", loader, success_ttl=30, failure_ttl=5, kind="flow")
        cached_load(cache, "rt", loader, success_ttl=30, failure_ttl=5, kind="flow")
        self.assertEqual(calls["n"], 1)
        clock.advance(31)
        cached_load(cache, "rt", loader, success_ttl=30, failure_ttl=5, kind="flow")
        self.assertEqual(calls["n"], 2)

    def test_stale_cache_is_labeled(self):
        clock = _Clock()
        cache = SharedTTLCache(persist=False, clock=clock, directory=None)
        cached_load(
            cache,
            "stale",
            lambda: pd.DataFrame({"v": [1]}),
            success_ttl=10,
            failure_ttl=5,
            source="akshare",
        )
        clock.advance(11)

        def boom():
            raise ConnectionError("RemoteDisconnected")

        out = cached_load(cache, "stale", boom, success_ttl=10, failure_ttl=5, source="akshare")
        self.assertFalse(out.empty)
        self.assertTrue(out.attrs.get("cache_stale"))
        self.assertEqual(out.attrs.get("cache_hit"), "stale")
        self.assertIn("stale_cache", out.attrs.get("issues") or [])
        self.assertEqual(out.attrs.get("cache_source"), "akshare")
        self.assertNotEqual(out.attrs.get("fresh"), True)

    def test_cross_session_key_does_not_look_fresh(self):
        monday = datetime(2026, 11, 9, 10, 0, tzinfo=SHANGHAI)
        tuesday = datetime(2026, 11, 10, 10, 0, tzinfo=SHANGHAI)
        key1 = make_cache_key("AKShareData", session_bucket(monday), "market_fund_flow")
        key2 = make_cache_key("AKShareData", session_bucket(tuesday), "market_fund_flow")
        self.assertNotEqual(key1, key2)
        self.assertEqual(expected_daily_data_date(monday).isoformat(), "2026-11-06")
        friday_close = datetime(2026, 11, 6, 15, 30, tzinfo=SHANGHAI)
        self.assertEqual(expected_daily_data_date(friday_close).isoformat(), "2026-11-06")

    def test_persistent_roundtrip(self):
        import tempfile

        clock = _Clock()
        with tempfile.TemporaryDirectory() as tmp:
            cache = SharedTTLCache(persist=True, directory=tmp, clock=clock, max_size=8)
            frame = pd.DataFrame({"v": [9]})
            cache.set("disk", frame, ttl=60, ok=True, source="akshare")
            other = SharedTTLCache(persist=True, directory=tmp, clock=clock, max_size=8)
            hit = other.get("disk")
            self.assertIsNotNone(hit)
            self.assertEqual(int(hit["v"].iloc[0]), 9)

    def test_stamp_does_not_pretend_fresh(self):
        frame = pd.DataFrame({"v": [1]})
        labeled = stamp_cache_meta(frame, hit="stale", stale=True, source="akshare", fetched_at="old")
        self.assertTrue(labeled.attrs.get("cache_stale"))
        self.assertIn("stale_cache", labeled.attrs.get("issues"))


class SameUpstreamSkipTests(unittest.TestCase):
    def test_akshare_skips_tushare_dc_peer(self):
        from src.data.akshare_data import AKShareData
        from src.data.config import get_data_config

        cfg = get_data_config(reload=True)
        client = AKShareData(cfg)
        self.assertIsNone(client._try_peer("get_market_fund_flow"))
        self.assertIsNone(client._try_peer("get_sector_fund_flow"))


if __name__ == "__main__":
    unittest.main()
