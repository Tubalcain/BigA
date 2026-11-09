"""行情稳定性：缓存合并/过期、失败冷却、有界重试、诊断分类。不打外网。"""

from __future__ import annotations

import os
import sys
import tempfile
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

from src.data.cache import (
    SharedTTLCache,
    cached_load,
    decode_cache_value,
    encode_cache_value,
    make_cache_key,
    stamp_cache_meta,
)
from src.data.calendar import (
    calendar_source,
    expected_daily_data_date,
    is_trading_day,
    session_bucket,
    session_phase,
    set_now_override,
)
from src.data.fetch import (
    SAME_UPSTREAM_EASTMONEY,
    DataFetchError,
    InFlightBusy,
    RateLimitError,
    call_with_timeout,
    classify_exception,
    inflight_alive,
    is_rate_limited,
    last_fetch_diagnostic,
    redact_text,
    reset_upstream_gates,
    safe_fetch,
    same_upstream_peer_allowed,
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

        heuristic = Push2RateLimitError("当前IP被临时限流")
        diag2 = classify_exception(heuristic)
        self.assertEqual(diag2.category, "rate_limit_heuristic")
        self.assertIsNone(diag2.http_status)
        self.assertNotEqual(diag2.category, "http_429")
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
        bearer = redact_text("Authorization: Bearer fake_token_aaaaaaaa")
        self.assertNotIn("fake_token_aaaaaaaa", bearer)
        self.assertIn("<redacted>", bearer)
        chained = RuntimeError("Authorization: Bearer fake_token_bbbbbbbb")
        outer = DataFetchError("TuShare 初始化失败")
        outer.__cause__ = chained
        redacted = redact_text(outer)
        self.assertNotIn("fake_token_bbbbbbbb", redacted)

    def test_http_404_is_4xx_not_retried(self):
        diag = classify_exception(HTTPError(404))
        self.assertEqual(diag.category, "http_4xx")
        self.assertEqual(diag.http_status, 404)
        calls = {"n": 0}

        def boom():
            calls["n"] += 1
            raise HTTPError(404)

        with self.assertRaises(DataFetchError):
            with_retry(boom, retries=3, timeout=0, delay=0, jitter=False, budget=5)
        self.assertEqual(calls["n"], 1)

    def test_http_503_is_5xx_retried(self):
        calls = {"n": 0}

        def boom():
            calls["n"] += 1
            raise HTTPError(503)

        with self.assertRaises(DataFetchError):
            with_retry(boom, retries=3, timeout=0, delay=0, jitter=False, budget=8)
        self.assertEqual(calls["n"], 3)

    def test_retry_after_http_date(self):
        from email.utils import formatdate

        raw = formatdate(timeval=time.time() - 5, usegmt=True)
        diag = classify_exception(HTTPError(429, retry_after=raw))
        self.assertEqual(diag.category, "http_429")
        self.assertIsNotNone(diag.retry_after)
        self.assertGreaterEqual(diag.retry_after, 0)
        calls = {"n": 0}

        def boom():
            calls["n"] += 1
            raise HTTPError(429, retry_after=raw)

        with self.assertRaises(RateLimitError):
            with_retry(boom, retries=3, timeout=0, delay=0, jitter=False, budget=5)
        self.assertEqual(calls["n"], 2)

    def test_success_diagnostic_is_ok(self):
        result = with_retry(lambda: 7, retries=3, timeout=0, delay=0, jitter=False, budget=3)
        self.assertEqual(result, 7)
        diag = last_fetch_diagnostic()
        self.assertEqual(diag.category, "ok")

    def test_heuristic_rate_limit_attempt_one(self):
        calls = {"n": 0}

        def boom():
            calls["n"] += 1
            raise Push2RateLimitError("当前IP被临时限流")

        with self.assertRaises(DataFetchError):
            with_retry(boom, retries=3, timeout=0, delay=0, jitter=False, budget=8)
        self.assertEqual(calls["n"], 1)
        self.assertEqual(last_fetch_diagnostic().category, "rate_limit_heuristic")

    def test_tushare_connect_log_uses_redact(self):
        import inspect

        from src.data.tushare_data import TuShareData

        self.assertIn("redact_text", inspect.getsource(TuShareData._connect))
        self.assertIn("redact_text", inspect.getsource(TuShareData._require))


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
        self.assertNotEqual(first.attrs.get("fresh"), True)
        self.assertNotEqual(second.attrs.get("fresh"), True)
        self.assertNotEqual(second.attrs.get("cache_hit"), "fresh")

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

    def test_empty_then_error_keeps_last_good(self):
        clock = _Clock()
        cache = SharedTTLCache(persist=False, clock=clock, directory=None, stale_max_age=3600)
        cached_load(
            cache,
            "seq",
            lambda: pd.DataFrame({"v": [9], "date": [pd.Timestamp("2026-11-06")]}),
            success_ttl=10,
            failure_ttl=5,
            source="akshare",
        )
        clock.advance(11)
        calls = {"n": 0}

        def empty():
            calls["n"] += 1
            return pd.DataFrame()

        emptied = cached_load(
            cache, "seq", empty, default=pd.DataFrame(), success_ttl=10, failure_ttl=5, source="akshare"
        )
        self.assertFalse(emptied.empty)
        self.assertTrue(emptied.attrs.get("cache_stale"))
        self.assertEqual(int(emptied["v"].iloc[0]), 9)
        self.assertNotEqual(emptied.attrs.get("fresh"), True)
        self.assertEqual(emptied.attrs.get("cache_source"), "akshare")
        clock.advance(6)

        def boom():
            calls["n"] += 1
            raise ConnectionError("RemoteDisconnected")

        after_error = cached_load(
            cache, "seq", boom, default=pd.DataFrame(), success_ttl=10, failure_ttl=5, source="akshare"
        )
        self.assertFalse(after_error.empty)
        self.assertTrue(after_error.attrs.get("cache_stale"))
        self.assertEqual(int(after_error["v"].iloc[0]), 9)
        self.assertNotEqual(after_error.attrs.get("fresh"), True)

    def test_cross_session_key_preserves_last_good(self):
        monday = datetime(2026, 11, 9, 10, 0, tzinfo=SHANGHAI)
        tuesday = datetime(2026, 11, 10, 10, 0, tzinfo=SHANGHAI)
        key1 = make_cache_key("AKShareData", "market_fund_flow")
        key2 = make_cache_key("AKShareData", "market_fund_flow")
        self.assertEqual(key1, key2)
        self.assertNotEqual(session_bucket(monday), session_bucket(tuesday))
        self.assertEqual(expected_daily_data_date(monday).isoformat(), "2026-11-06")
        friday_close = datetime(2026, 11, 6, 15, 30, tzinfo=SHANGHAI)
        self.assertEqual(expected_daily_data_date(friday_close).isoformat(), "2026-11-06")
        clock = _Clock()
        cache = SharedTTLCache(persist=False, clock=clock, directory=None, stale_max_age=172800)
        cached_load(
            cache,
            key1,
            lambda: pd.DataFrame({"v": [3]}),
            success_ttl=10,
            failure_ttl=5,
            source="akshare",
            session=session_bucket(monday),
        )
        clock.advance(11)

        def boom():
            raise ConnectionError("boom")

        out = cached_load(
            cache,
            key2,
            boom,
            success_ttl=10,
            failure_ttl=5,
            source="akshare",
            session=session_bucket(tuesday),
        )
        self.assertTrue(out.attrs.get("cache_stale"))
        self.assertEqual(out.attrs.get("cache_session"), session_bucket(monday))

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

    def test_json_roundtrip_named_index_and_ext_dtypes(self):
        idx = pd.Index(["600000", "000001"], name="code")
        frame = pd.DataFrame(
            {
                "n": pd.Series([1, 2], index=idx, dtype="int64"),
                "flag": pd.Series([True, False], index=idx, dtype="bool"),
                "name": pd.Series(["浦发", "平安"], index=idx, dtype="string"),
                "amt": pd.Series([10, pd.NA], index=idx, dtype="Int64"),
                "day": pd.Series(pd.to_datetime(["2026-09-30", "2026-10-08"]), index=idx),
            },
            index=idx,
        )
        frame.attrs["source"] = "akshare"
        frame.attrs["ok"] = True
        self.assertFalse(frame.drop(columns=["day"]).isna().all().all())
        decoded = decode_cache_value(encode_cache_value(frame))
        self.assertEqual(decoded.index.name, "code")
        self.assertEqual(list(decoded.index), ["600000", "000001"])
        self.assertEqual(int(decoded["n"].iloc[0]), 1)
        self.assertEqual(bool(decoded["flag"].iloc[0]), True)
        self.assertEqual(str(decoded["name"].iloc[0]), "浦发")
        self.assertTrue(pd.isna(decoded["amt"].iloc[1]))
        self.assertEqual(pd.Timestamp(decoded["day"].iloc[0]).date().isoformat(), "2026-09-30")
        self.assertEqual(decoded.attrs.get("source"), "akshare")
        self.assertTrue(decoded.attrs.get("ok"))

        typical = pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-11-06", "2026-11-05"]),
                "main_net_inflow": [1.5, 2.25],
            }
        ).reset_index(drop=True)
        roundtrip = decode_cache_value(encode_cache_value(typical))
        self.assertEqual(float(roundtrip["main_net_inflow"].iloc[0]), 1.5)
        self.assertFalse(roundtrip["main_net_inflow"].isna().any())

    def test_misaligned_named_index_is_already_null_before_encode(self):
        named = pd.Index(["a", "b"], name="code")
        raw = pd.DataFrame(
            {
                "n": pd.Series([1, 2], dtype="int64"),
                "flag": pd.Series([True, False], dtype="bool"),
            },
            index=named,
        )
        self.assertTrue(raw["n"].isna().all())
        self.assertTrue(raw["flag"].isna().all())

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
        self.assertFalse(same_upstream_peer_allowed("get_market_fund_flow", "transport"))
        self.assertTrue(same_upstream_peer_allowed("get_market_fund_flow", "permission"))
        self.assertTrue(same_upstream_peer_allowed("get_market_fund_flow", "no_token"))
        self.assertIsNone(client._try_peer("get_market_fund_flow", reason="transport"))
        self.assertIsNone(client._try_peer("get_sector_fund_flow", reason="transport"))

    def test_tushare_permission_falls_back_to_akshare(self):
        from src.data.config import get_data_config
        from src.data.tushare_data import TuShareData

        cfg = get_data_config(reload=True)
        cfg.tushare.token = ""
        client = TuShareData(cfg)
        self.assertFalse(client.is_available())
        called = {"n": 0}

        class Peer:
            def is_available(self):
                return True

            def get_market_fund_flow(self, *args, **kwargs):
                called["n"] += 1
                frame = pd.DataFrame({"date": [pd.Timestamp("2026-11-06")], "main_net_inflow": [1.0]})
                frame.attrs["source"] = "akshare"
                return frame

        client._peer = lambda: Peer()
        out = client._try_peer("get_market_fund_flow")
        self.assertIsNotNone(out)
        self.assertEqual(called["n"], 1)
        self.assertIn("same_upstream_degrade:eastmoney", out.attrs.get("issues") or [])
        self.assertFalse(out.attrs.get("independent_backup"))
        self.assertIsNone(client._try_peer("get_market_fund_flow", reason="transport"))
        self.assertEqual(called["n"], 1)


def _cache_proc_worker(directory, key, delay, counter_path, result_path, start_wait):
    if start_wait:
        time.sleep(float(start_wait))
    cache = SharedTTLCache(persist=True, directory=directory, lock_timeout=8)
    def loader():
        with open(counter_path, "a", encoding="utf-8") as handle:
            handle.write("x")
        time.sleep(float(delay))
        return pd.DataFrame({"v": [42]})

    out = cached_load(cache, key, loader, success_ttl=60, failure_ttl=5, source="akshare")
    Path(result_path).write_text(
        f"{int(out['v'].iloc[0])},{out.attrs.get('cache_hit')}",
        encoding="utf-8",
    )


def _cache_lock_holder(directory, key, hold, result_path):
    cache = SharedTTLCache(persist=True, directory=directory, lock_timeout=8)

    def hang():
        time.sleep(float(hold))
        return pd.DataFrame({"v": [1]})

    try:
        cache._with_file_lock(key, hang, timeout=hold + 1)
        Path(result_path).write_text("held", encoding="utf-8")
    except Exception as exc:
        Path(result_path).write_text(f"err:{exc}", encoding="utf-8")


class CrossProcessCacheTests(unittest.TestCase):
    def test_second_process_coalesces(self):
        import multiprocessing

        with tempfile.TemporaryDirectory() as tmp:
            counter = str(Path(tmp) / "n.txt")
            Path(counter).write_text("", encoding="utf-8")
            r1 = str(Path(tmp) / "a.txt")
            r2 = str(Path(tmp) / "b.txt")
            ctx = multiprocessing.get_context("fork")
            p1 = ctx.Process(target=_cache_proc_worker, args=(tmp, "shared", 0.6, counter, r1, 0))
            p2 = ctx.Process(target=_cache_proc_worker, args=(tmp, "shared", 0.6, counter, r2, 0.15))
            p1.start()
            p2.start()
            p1.join(timeout=8)
            p2.join(timeout=8)
            self.assertEqual(p1.exitcode, 0)
            self.assertEqual(p2.exitcode, 0)
            self.assertEqual(Path(counter).read_text(encoding="utf-8").count("x"), 1)
            self.assertTrue(Path(r1).read_text(encoding="utf-8").startswith("42,"))
            self.assertTrue(Path(r2).read_text(encoding="utf-8").startswith("42,"))

    def test_lock_timeout_does_not_block_forever(self):
        import multiprocessing

        with tempfile.TemporaryDirectory() as tmp:
            held = str(Path(tmp) / "held.txt")
            ctx = multiprocessing.get_context("fork")
            holder = ctx.Process(target=_cache_lock_holder, args=(tmp, "slow", 2.5, held))
            holder.start()
            time.sleep(0.2)
            cache = SharedTTLCache(persist=True, directory=tmp, lock_timeout=0.4)
            started = time.monotonic()
            with self.assertRaises(TimeoutError):
                cache._with_file_lock("slow", lambda: None, timeout=0.4)
            self.assertLess(time.monotonic() - started, 1.5)
            holder.terminate()
            holder.join(timeout=3)

    def test_pickle_payload_is_rejected(self):
        import pickle

        with tempfile.TemporaryDirectory() as tmp:
            cache = SharedTTLCache(persist=True, directory=tmp, clock=_Clock())
            path = cache._disk_path("evil")
            path.write_bytes(pickle.dumps({"format": 2, "ok": True, "value": "nope"}))
            self.assertIsNone(cache.get_entry("evil"))
            self.assertFalse(path.exists())

    def test_stale_max_age_drops_ancient_good(self):
        clock = _Clock()
        cache = SharedTTLCache(persist=False, clock=clock, directory=None, stale_max_age=30)
        cached_load(cache, "old", lambda: pd.DataFrame({"v": [1]}), success_ttl=5, failure_ttl=3)
        clock.advance(40)

        def boom():
            raise ConnectionError("x")

        with self.assertRaises(ConnectionError):
            cached_load(cache, "old", boom, success_ttl=5, failure_ttl=3)


class InFlightTimeoutTests(unittest.TestCase):
    def test_timeout_does_not_stack_same_key(self):
        def slow():
            time.sleep(0.4)
            return "done"

        with self.assertRaises(DataFetchError):
            call_with_timeout(slow, 0.05, inflight_key="ak:page")
        self.assertTrue(inflight_alive("ak:page"))
        with self.assertRaises(InFlightBusy):
            call_with_timeout(slow, 0.05, inflight_key="ak:page")
        workers = [
            thread
            for thread in threading.enumerate()
            if thread.name.startswith("biga-fetch-ak:page")
        ]
        self.assertEqual(len(workers), 1)
        deadline = time.time() + 2
        while inflight_alive("ak:page") and time.time() < deadline:
            time.sleep(0.05)
        self.assertFalse(inflight_alive("ak:page"))


def _gate_hang_worker(directory, limit, label, sleep_s, timeout_s, result_path, linger_s):
    os.environ["BIGA_CACHE_DIR"] = directory
    os.environ["BIGA_EASTMONEY_LIMIT"] = str(limit)
    from src.data.config import get_data_config
    from src.data.fetch import reset_upstream_gates, safe_fetch

    get_data_config(reload=True)
    reset_upstream_gates()

    def hang():
        time.sleep(float(sleep_s))
        return "ok"

    started = time.monotonic()
    out = safe_fetch(
        hang,
        retries=1,
        timeout=float(timeout_s),
        default="timed_out",
        label=label,
        upstream="eastmoney",
        budget=float(timeout_s) + 0.4,
    )
    Path(result_path).write_text(
        f"{out}:{time.monotonic() - started:.3f}",
        encoding="utf-8",
    )
    time.sleep(float(linger_s))


def _gate_acquire_worker(directory, limit, wait_s, result_path):
    os.environ["BIGA_CACHE_DIR"] = directory
    os.environ["BIGA_EASTMONEY_LIMIT"] = str(limit)
    from src.data.config import get_data_config
    from src.data.fetch import GateTimeout, reset_upstream_gates, upstream_gate

    get_data_config(reload=True)
    reset_upstream_gates()
    gate = upstream_gate("eastmoney", limit=int(limit), timeout=float(wait_s), directory=directory)
    started = time.monotonic()
    try:
        lease = gate.acquire(timeout=float(wait_s))
        lease.release()
        Path(result_path).write_text(
            f"acquired:{time.monotonic() - started:.3f}",
            encoding="utf-8",
        )
    except GateTimeout:
        Path(result_path).write_text(
            f"timeout:{time.monotonic() - started:.3f}",
            encoding="utf-8",
        )


def _cooldown_empty_worker(directory, key, counter_path, result_path):
    cache = SharedTTLCache(persist=True, directory=directory, lock_timeout=8)

    def loader():
        with open(counter_path, "a", encoding="utf-8") as handle:
            handle.write("x")
        return pd.DataFrame()

    out = cached_load(
        cache,
        key,
        loader,
        default=pd.DataFrame({"v": pd.Series(dtype="float64")}),
        success_ttl=60,
        failure_ttl=12,
        source="akshare",
    )
    Path(result_path).write_text(
        f"{out.attrs.get('cache_hit')}:{cache.cooldown_remaining(key):.3f}",
        encoding="utf-8",
    )


class CalendarHolidayTests(unittest.TestCase):
    def tearDown(self):
        set_now_override(None)

    def test_national_day_2026_uses_sep30(self):
        noon = datetime(2026, 10, 1, 10, 0, tzinfo=SHANGHAI)
        self.assertEqual(session_phase(noon), "holiday")
        self.assertFalse(is_trading_day("2026-10-01"))
        self.assertTrue(is_trading_day("2026-09-30"))
        expected = expected_daily_data_date(noon)
        self.assertEqual(expected.isoformat(), "2026-09-30")
        self.assertEqual(session_bucket(noon), "2026-10-01:holiday")

    def test_sse_2026_notice_22_boundaries(self):
        close = datetime(2026, 9, 30, 15, 30, tzinfo=SHANGHAI)
        self.assertEqual(session_phase(close), "closed")
        self.assertEqual(expected_daily_data_date(close).isoformat(), "2026-09-30")
        sunday = datetime(2026, 9, 20, 10, 0, tzinfo=SHANGHAI)
        self.assertEqual(session_phase(sunday), "weekend")
        self.assertFalse(is_trading_day("2026-09-20"))
        self.assertEqual(expected_daily_data_date(sunday).isoformat(), "2026-09-18")
        self.assertTrue(is_trading_day("2026-09-28"))
        self.assertFalse(is_trading_day("2026-09-25"))
        self.assertFalse(is_trading_day("2026-10-10"))
        self.assertEqual(
            expected_daily_data_date(datetime(2026, 10, 10, 10, 0, tzinfo=SHANGHAI)).isoformat(),
            "2026-10-09",
        )
        self.assertEqual(calendar_source("2026-09-30"), "bundled_sse_notice")
        self.assertEqual(calendar_source("2027-03-15"), "weekday_fallback")
        self.assertTrue(is_trading_day("2027-03-15"))
        self.assertFalse(is_trading_day("2027-03-14"))


class CalendarFrozenClockTests(unittest.TestCase):
    def tearDown(self):
        set_now_override(None)

    def test_session_close_weekend_holiday_bounds(self):
        cases = (
            (datetime(2026, 11, 9, 10, 0, tzinfo=SHANGHAI), "open", "2026-11-06"),
            (datetime(2026, 11, 9, 15, 30, tzinfo=SHANGHAI), "closed", "2026-11-09"),
            (datetime(2026, 11, 7, 11, 0, tzinfo=SHANGHAI), "weekend", "2026-11-06"),
            (datetime(2026, 10, 1, 10, 0, tzinfo=SHANGHAI), "holiday", "2026-09-30"),
            (datetime(2026, 9, 30, 10, 0, tzinfo=SHANGHAI), "open", "2026-09-29"),
            (datetime(2026, 9, 30, 15, 30, tzinfo=SHANGHAI), "closed", "2026-09-30"),
            (datetime(2026, 9, 20, 12, 0, tzinfo=SHANGHAI), "weekend", "2026-09-18"),
            (datetime(2025, 10, 8, 10, 0, tzinfo=SHANGHAI), "holiday", "2025-09-30"),
            (datetime(2024, 10, 7, 10, 0, tzinfo=SHANGHAI), "holiday", "2024-09-30"),
        )
        for now, phase, expected in cases:
            with self.subTest(now=now.isoformat(), phase=phase):
                set_now_override(now)
                self.assertEqual(session_phase(), phase)
                self.assertEqual(expected_daily_data_date().isoformat(), expected)
                self.assertEqual(expected_daily_data_date(now).isoformat(), expected)


class UpstreamGateTests(unittest.TestCase):
    def tearDown(self):
        reset_upstream_gates()
        os.environ.pop("BIGA_EASTMONEY_LIMIT", None)
        os.environ.pop("BIGA_CACHE_DIR", None)

    def test_gate_times_out_instead_of_deadlock(self):
        reset_upstream_gates()
        with tempfile.TemporaryDirectory() as tmp:
            from src.data.fetch import GateTimeout, upstream_gate

            gate = upstream_gate("eastmoney", limit=1, timeout=0.3, directory=tmp)
            acquired = threading.Event()
            release = threading.Event()

            def hold():
                with gate:
                    acquired.set()
                    release.wait(timeout=3)

            thread = threading.Thread(target=hold)
            thread.start()
            self.assertTrue(acquired.wait(timeout=2))
            waiter = upstream_gate("eastmoney", limit=1, timeout=0.3, directory=tmp)
            started = time.monotonic()
            with self.assertRaises(GateTimeout):
                waiter.acquire(timeout=0.3)
            self.assertLess(time.monotonic() - started, 1.5)
            release.set()
            thread.join(timeout=3)
        reset_upstream_gates()

    def test_timeout_holds_slot_until_worker_ends_same_process_two_labels(self):
        from src.data.config import get_data_config
        from src.data.fetch import GateTimeout, upstream_gate

        reset_upstream_gates()
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["BIGA_CACHE_DIR"] = tmp
            os.environ["BIGA_EASTMONEY_LIMIT"] = "1"
            get_data_config(reload=True)
            reset_upstream_gates()
            running = {"n": 0, "peak": 0}
            lock = threading.Lock()

            def hang():
                with lock:
                    running["n"] += 1
                    running["peak"] = max(running["peak"], running["n"])
                time.sleep(1.1)
                with lock:
                    running["n"] -= 1
                return "ok"

            first = safe_fetch(
                hang,
                retries=1,
                timeout=0.15,
                default="timed_out",
                label="stock_flow",
                upstream="eastmoney",
                budget=0.4,
            )
            self.assertEqual(first, "timed_out")
            gate = upstream_gate("eastmoney", limit=1, timeout=0.35, directory=tmp)
            started = time.monotonic()
            with self.assertRaises(GateTimeout):
                gate.acquire(timeout=0.35)
            self.assertLess(time.monotonic() - started, 1.2)
            second = safe_fetch(
                hang,
                retries=1,
                timeout=0.15,
                default="blocked",
                label="northbound",
                upstream="eastmoney",
                budget=0.4,
            )
            self.assertEqual(second, "blocked")
            self.assertEqual(running["peak"], 1)
            deadline = time.monotonic() + 3
            while running["n"] > 0 and time.monotonic() < deadline:
                time.sleep(0.05)
            recovered = upstream_gate("eastmoney", limit=1, timeout=1.5, directory=tmp)
            lease = recovered.acquire(timeout=1.5)
            lease.release()
        reset_upstream_gates()

    def test_second_process_cannot_bypass_limit_after_timeout(self):
        import multiprocessing

        reset_upstream_gates()
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["BIGA_CACHE_DIR"] = tmp
            os.environ["BIGA_EASTMONEY_LIMIT"] = "1"
            r1 = str(Path(tmp) / "a.txt")
            r2 = str(Path(tmp) / "b.txt")
            r3 = str(Path(tmp) / "c.txt")
            ctx = multiprocessing.get_context("fork")
            p1 = ctx.Process(
                target=_gate_hang_worker,
                args=(tmp, 1, "stock_flow", 2.2, 0.2, r1, 2.4),
            )
            p1.start()
            deadline = time.monotonic() + 3
            while not Path(r1).exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertTrue(Path(r1).exists())
            self.assertTrue(Path(r1).read_text(encoding="utf-8").startswith("timed_out"))
            p2 = ctx.Process(target=_gate_acquire_worker, args=(tmp, 1, 0.4, r2))
            p2.start()
            p2.join(timeout=4)
            self.assertEqual(p2.exitcode, 0)
            self.assertTrue(Path(r2).read_text(encoding="utf-8").startswith("timeout"))
            p1.join(timeout=6)
            self.assertEqual(p1.exitcode, 0)
            p3 = ctx.Process(target=_gate_acquire_worker, args=(tmp, 1, 1.2, r3))
            p3.start()
            p3.join(timeout=4)
            self.assertEqual(p3.exitcode, 0)
            self.assertTrue(Path(r3).read_text(encoding="utf-8").startswith("acquired"))
        reset_upstream_gates()


class CrossProcessCooldownTests(unittest.TestCase):
    def test_second_process_skips_loader_during_shared_cooldown(self):
        import multiprocessing

        with tempfile.TemporaryDirectory() as tmp:
            counter = str(Path(tmp) / "loads.txt")
            Path(counter).write_text("", encoding="utf-8")
            r1 = str(Path(tmp) / "a.txt")
            r2 = str(Path(tmp) / "b.txt")
            ctx = multiprocessing.get_context("fork")
            p1 = ctx.Process(target=_cooldown_empty_worker, args=(tmp, "flow:empty", counter, r1))
            p1.start()
            p1.join(timeout=8)
            self.assertEqual(p1.exitcode, 0)
            first = Path(r1).read_text(encoding="utf-8")
            self.assertTrue(first.startswith("failure:"))
            remaining = float(first.split(":")[1])
            self.assertGreater(remaining, 0)
            p2 = ctx.Process(target=_cooldown_empty_worker, args=(tmp, "flow:empty", counter, r2))
            p2.start()
            p2.join(timeout=8)
            self.assertEqual(p2.exitcode, 0)
            second = Path(r2).read_text(encoding="utf-8")
            self.assertTrue(second.startswith("cooldown:"))
            self.assertEqual(Path(counter).read_text(encoding="utf-8").count("x"), 1)


if __name__ == "__main__":
    unittest.main()
