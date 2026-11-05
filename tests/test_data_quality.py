"""离线测试：模式清洗、代码转换、缓存、配置覆盖。不访问外网。"""

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from src.data.cache import TTLCache, make_cache_key
from src.data.fetch import DataFetchError, RateLimitError, call_with_timeout, is_rate_limited, with_retry
from src.data.config import get_data_config, load_app_config
from src.data.quality import (
    attach_date_swap,
    clean_ohlcv,
    compact_date,
    describe_data_problems,
    empty_ohlcv,
    infer_board,
    infer_exchange,
    match_exchange,
    normalize_adjust,
    normalize_ohlcv,
    normalize_period,
    normalize_quotes,
    normalize_stock_code,
    ordered_date_range,
    outlier_count,
    prepare_ohlcv,
    to_ts_code,
    validate_ohlcv,
)


class QualityTests(unittest.TestCase):
    def test_code_normalization(self):
        self.assertEqual(normalize_stock_code("000001.SZ"), "000001")
        self.assertEqual(normalize_stock_code("sz000001"), "000001")
        self.assertEqual(normalize_stock_code("600519.SH"), "600519")
        self.assertEqual(to_ts_code("000001"), "000001.SZ")
        self.assertEqual(to_ts_code("600000"), "600000.SH")
        self.assertEqual(to_ts_code("688001"), "688001.SH")
        self.assertEqual(infer_exchange("000001"), "深圳交易所")
        self.assertEqual(infer_exchange("600519"), "上海交易所")
        self.assertEqual(infer_board("300015"), "创业板")
        self.assertTrue(match_exchange("000001", "深圳交易所"))
        self.assertFalse(match_exchange("000001", "上海交易所"))
        self.assertTrue(match_exchange("000001", "所有"))
        self.assertEqual(normalize_stock_code("1"), "")
        self.assertEqual(normalize_stock_code("00001"), "")
        self.assertEqual(to_ts_code("1"), "")
        self.assertEqual(compact_date("2024-01-02"), "20240102")
        self.assertEqual(compact_date("2024-1-2"), "20240102")
        self.assertEqual(compact_date("2024/01/02"), "20240102")
        self.assertEqual(compact_date("20240102"), "20240102")
        start, end, swapped = ordered_date_range("20240110", "20240101")
        self.assertEqual((start, end, swapped), ("20240101", "20240110", True))
        start, end, swapped = ordered_date_range("2024-1-2", "2024/01/05")
        self.assertEqual((start, end, swapped), ("20240102", "20240105", False))
        self.assertEqual(normalize_period("周线"), "weekly")
        self.assertEqual(normalize_adjust("前复权"), "qfq")

    def test_normalize_chinese_ohlcv(self):
        raw = pd.DataFrame(
            {
                "日期": ["20240102", "20240103", "20240103", "20240104"],
                "开盘": [10, 10.2, 10.3, 10.1],
                "收盘": [10.2, 10.5, 10.4, 10.0],
                "最高": [10.3, 10.6, 10.5, 9.8],  # last bar high < low -> swap
                "最低": [9.9, 10.1, 10.2, 10.2],
                "成交量": [1000, 1100, 1200, 900],
            }
        )
        df = clean_ohlcv(normalize_ohlcv(raw, source="test", code="000001"))
        ok, issues = validate_ohlcv(df)
        self.assertTrue(ok, issues)
        self.assertEqual(len(df), 3)  # duplicate 20240103 dropped
        self.assertIn("open", df.columns)
        self.assertEqual(df.attrs.get("source"), "test")
        self.assertEqual(df.attrs.get("timezone"), "Asia/Shanghai")
        last = df.iloc[-1]
        self.assertGreaterEqual(last["high"], last["low"])
        self.assertGreaterEqual(last["high"], last["close"])
        self.assertLessEqual(last["low"], last["close"])

    def test_outlier_flag(self):
        raw = pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=3, freq="D"),
                "open": [10, 10, 10],
                "high": [11, 11, 40],
                "low": [9, 9, 9],
                "close": [10, 10.1, 30],
                "volume": [100, 100, 100],
            }
        )
        df = clean_ohlcv(normalize_ohlcv(raw, source="test"), max_abs_return=0.5)
        self.assertTrue(bool(df["is_outlier"].iloc[-1]))

    def test_quote_market_cap_unit(self):
        raw = pd.DataFrame(
            {
                "代码": ["000001"],
                "名称": ["平安银行"],
                "最新价": [12.3],
                "涨跌幅": [1.5],
                "成交量": [10000],
                "总市值": [1_000_000_000],  # 元
                "买入": [12.2],
            }
        )
        quotes = normalize_quotes(raw, source="akshare", market_cap_unit="yuan")
        self.assertAlmostEqual(quotes.iloc[0]["market_cap"], 100000.0)
        self.assertEqual(quotes.iloc[0]["price"], 12.3)
        self.assertEqual(quotes.iloc[0]["exchange"], "深圳交易所")
        self.assertNotIn("买入", quotes.columns)

    def test_quotes_drop_empty_and_short_codes(self):
        raw = pd.DataFrame(
            {
                "code": ["1", "", "000001", "000002.SZ"],
                "name": ["x", "y", "平安银行", "万科A"],
                "price": [1.0, 2.0, 10.0, 11.0],
            }
        )
        quotes = normalize_quotes(raw, source="test")
        self.assertEqual(list(quotes["code"]), ["000001", "000002"])
        empty = normalize_quotes(
            pd.DataFrame({"code": ["1", ""], "price": [1.0, 2.0]}),
            source="test",
        )
        self.assertTrue(empty.empty)
        self.assertIn("no valid stock codes", empty.attrs.get("issues", []))

    def test_missing_date_column_is_reported(self):
        df = normalize_ohlcv(pd.DataFrame({"open": [1], "close": [1]}), source="test")
        self.assertTrue(df.empty)
        self.assertIn("missing date column", df.attrs.get("issues", []))

    def test_attach_date_swap_does_not_mutate_cache(self):
        raw = pd.DataFrame(
            {
                "date": ["20240102"],
                "open": [10],
                "high": [11],
                "low": [9],
                "close": [10.5],
                "volume": [1],
            }
        )
        df = prepare_ohlcv(raw, source="test")
        marked = attach_date_swap(df, True)
        self.assertTrue(marked.attrs.get("date_range_swapped"))
        self.assertFalse(df.attrs.get("date_range_swapped"))
        self.assertIn("start/end dates swapped", marked.attrs.get("issues", []))

    def test_short_code_does_not_pad_to_pingan(self):
        df = prepare_ohlcv(pd.DataFrame(), source="test", code="1")
        self.assertTrue(df.empty)
        self.assertIn("invalid stock code", df.attrs.get("issues", []))

    def test_prepare_ohlcv_filters_dates_and_reports_issues(self):
        raw = pd.DataFrame(
            {
                "date": ["20240101", "20240102", "20240103", "20240105"],
                "open": [10, 10, 10, 10],
                "high": [11, 11, 11, 11],
                "low": [9, 9, 9, 9],
                "close": [10, 10.2, 10.1, 10.3],
                "volume": [1, 1, 1, 1],
                "junk": [1, 2, 3, 4],
            }
        )
        df = prepare_ohlcv(raw, source="test", code="000001", start="20240102", end="20240103")
        self.assertTrue(df.attrs.get("ok"))
        self.assertEqual(len(df), 2)
        self.assertNotIn("junk", df.columns)
        self.assertEqual(df["date"].min(), pd.Timestamp("2024-01-02"))
        self.assertEqual(df["date"].max(), pd.Timestamp("2024-01-03"))

    def test_prepare_ohlcv_swaps_inverted_dates(self):
        raw = pd.DataFrame(
            {
                "date": ["20240101", "20240102", "20240103"],
                "open": [10, 10, 10],
                "high": [11, 11, 11],
                "low": [9, 9, 9],
                "close": [10, 10.2, 10.1],
                "volume": [1, 1, 1],
            }
        )
        df = prepare_ohlcv(raw, source="test", start="20240103", end="20240101")
        self.assertFalse(df.empty)
        self.assertEqual(len(df), 3)
        self.assertTrue(df.attrs.get("date_range_swapped"))
        self.assertIn("start/end dates swapped", df.attrs.get("issues", []))
        self.assertTrue(df.attrs.get("ok"))

    def test_describe_data_problems_and_outliers(self):
        empty = empty_ohlcv("akshare", error="akshare unavailable", issues=["akshare unavailable"])
        text = describe_data_problems(empty)
        self.assertIn("akshare unavailable", text)
        self.assertEqual(describe_data_problems(None), "无数据")
        raw = pd.DataFrame(
            {
                "date": ["20240101", "20240102"],
                "open": [10, 10],
                "high": [11, 30],
                "low": [9, 9],
                "close": [10, 25],
                "volume": [1, 1],
            }
        )
        df = prepare_ohlcv(raw, source="test")
        self.assertGreaterEqual(outlier_count(df), 1)

    def test_validate_detects_dirty_bars(self):
        dirty = pd.DataFrame(
            {
                "date": pd.to_datetime(["2024-01-03", "2024-01-01", "2024-01-01"]),
                "open": [10, 10, 10],
                "high": [9, 11, 11],
                "low": [11, 9, 9],
                "close": [12, 10, 10],
                "volume": [1, 1, 1],
            }
        )
        ok, issues = validate_ohlcv(dirty)
        self.assertFalse(ok)
        self.assertTrue(any("high < low" in i or "duplicate" in i or "sorted" in i or "outside" in i for i in issues))


class CacheConfigTests(unittest.TestCase):
    def test_ttl_cache_expiry(self):
        cache = TTLCache(max_size=2, default_ttl=60, enabled=True)
        cache.set("a", 1, ttl=60)
        self.assertEqual(cache.get("a"), 1)
        cache.set("a", 1, ttl=0)
        self.assertIsNone(cache.get("a"))

    def test_cache_disabled(self):
        cache = TTLCache(enabled=False)
        cache.set("k", 2)
        self.assertIsNone(cache.get("k"))

    def test_make_cache_key_stable(self):
        self.assertEqual(make_cache_key("h", 1), make_cache_key("h", 1))
        self.assertNotEqual(make_cache_key("h", 1), make_cache_key("h", 2))

    def test_config_loads_and_env_override(self):
        load_app_config.cache_clear()
        os.environ["TUSHARE_TOKEN"] = "demo-token-not-real"
        os.environ["BIGA_DATA_PRIMARY"] = "tushare"
        try:
            cfg = get_data_config(reload=True)
            self.assertEqual(cfg.tushare.token, "demo-token-not-real")
            self.assertEqual(cfg.primary, "tushare")
            self.assertTrue(cfg.fallback)
            self.assertGreater(cfg.cache.ttl, 0)
        finally:
            os.environ.pop("TUSHARE_TOKEN", None)
            os.environ.pop("BIGA_DATA_PRIMARY", None)
            load_app_config.cache_clear()
            get_data_config(reload=True)

    def test_rate_limit_is_not_retried(self):
        self.assertTrue(is_rate_limited(RuntimeError("东方财富 当前 IP 被临时限流")))
        calls = {"n": 0}

        def boom():
            calls["n"] += 1
            raise RuntimeError("请求过于频繁，请稍后再试")

        with self.assertRaises(RateLimitError):
            with_retry(boom, retries=4, timeout=0, delay=0)
        self.assertEqual(calls["n"], 1)

    def test_timeout_returns_without_waiting_for_worker(self):
        import time

        def slow():
            time.sleep(2)
            return "done"

        started = time.monotonic()
        with self.assertRaises(DataFetchError):
            call_with_timeout(slow, 0.2)
        self.assertLess(time.monotonic() - started, 1.0)

    def test_get_data_source_does_not_silently_swap(self):
        from src.data import get_data_source
        from src.data.akshare_data import AKShareData
        from src.data.tushare_data import TuShareData

        os.environ.pop("TUSHARE_TOKEN", None)
        load_app_config.cache_clear()
        get_data_config(reload=True)
        ak = get_data_source("akshare")
        ts = get_data_source("tushare")
        self.assertIsInstance(ak, AKShareData)
        self.assertEqual(ak.name, "akshare")
        self.assertIsInstance(ts, TuShareData)
        self.assertEqual(ts.name, "tushare")
        self.assertFalse(ts.is_available())

    def test_get_active_client_falls_back_when_tushare_unavailable(self):
        from src.data import get_active_client, get_data_source
        from src.data.akshare_data import AKShareData

        os.environ.pop("TUSHARE_TOKEN", None)
        load_app_config.cache_clear()
        get_data_config(reload=True)
        client = get_active_client("tushare")
        ak = get_data_source("akshare")
        if ak.is_available():
            self.assertIsInstance(client, AKShareData)
        else:
            self.assertEqual(client.name, "tushare")

        from src.data import source_switch_note
        from types import SimpleNamespace

        self.assertEqual(source_switch_note("tushare", SimpleNamespace(name="akshare")), "数据源 tushare 不可用，已切换为 akshare")
        self.assertEqual(source_switch_note("akshare", SimpleNamespace(name="akshare")), "")

    def test_get_active_client_falls_back_to_tushare_when_akshare_down(self):
        from src.data import get_active_client
        from src.data.akshare_data import AKShareData
        from src.data.tushare_data import TuShareData

        original_ak = AKShareData.is_available
        original_ts = TuShareData.is_available
        try:
            AKShareData.is_available = lambda self: False
            TuShareData.is_available = lambda self: True
            client = get_active_client("akshare")
            self.assertIsInstance(client, TuShareData)
        finally:
            AKShareData.is_available = original_ak
            TuShareData.is_available = original_ts

    def test_tushare_unavailable_without_token(self):
        from src.data.tushare_data import TuShareData

        load_app_config.cache_clear()
        os.environ.pop("TUSHARE_TOKEN", None)
        cfg = get_data_config(reload=True)
        cfg.tushare.token = ""
        client = TuShareData(cfg)
        self.assertFalse(client.is_available())
        hist = client.get_history_data("000001", "20240101", "20240110", allow_fallback=False)
        self.assertTrue(hist.empty)
        self.assertIn("tushare unavailable", hist.attrs.get("issues", []))
        self.assertListEqual(list(hist.columns)[:6], ["date", "open", "high", "low", "close", "volume"])
        quote = client.get_realtime_quote("1")
        self.assertTrue(quote.empty)
        self.assertIn("invalid stock code", quote.attrs.get("issues", []))
        bad = client.get_history_data("1", "20240101", "20240110", allow_fallback=True)
        self.assertTrue(bad.empty)
        self.assertIn("invalid stock code", bad.attrs.get("issues", []))
        overview = client.get_market_overview(light=True, allow_fallback=False)
        self.assertTrue(overview.empty)
        self.assertIn("tushare unavailable", overview.attrs.get("issues", []))

    def test_disabled_akshare_returns_empty_not_raise(self):
        from src.data.akshare_data import AKShareData

        cfg = get_data_config(reload=True)
        previous = cfg.akshare.enabled
        try:
            cfg.akshare.enabled = False
            client = AKShareData(cfg)
            self.assertFalse(client.is_available())
            hist = client.get_history_data("000001", "20240101", "20240110", allow_fallback=False)
            self.assertTrue(hist.empty)
            self.assertIn("akshare unavailable", hist.attrs.get("issues", []))
            quote = client.get_realtime_quote("1")
            self.assertTrue(quote.empty)
            self.assertIn("invalid stock code", quote.attrs.get("issues", []))
            quote2 = client.get_realtime_quote("000001")
            self.assertIsNotNone(quote2)
            overview = client.get_market_overview(light=True, allow_fallback=False)
            self.assertTrue(overview.empty)
            self.assertIn("akshare unavailable", overview.attrs.get("issues", []))
            flow = client.get_fund_flow(allow_fallback=False)
            self.assertTrue(flow.empty)
            self.assertIn("akshare unavailable", flow.attrs.get("issues", []))
        finally:
            cfg.akshare.enabled = previous


if __name__ == "__main__":
    unittest.main()
