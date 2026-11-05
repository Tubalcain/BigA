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
from src.data.fetch import RateLimitError, is_rate_limited, with_retry
from src.data.config import get_data_config, load_app_config
from src.data.quality import (
    clean_ohlcv,
    infer_board,
    infer_exchange,
    match_exchange,
    normalize_ohlcv,
    normalize_quotes,
    normalize_stock_code,
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
            }
        )
        quotes = normalize_quotes(raw, source="akshare", market_cap_unit="yuan")
        self.assertAlmostEqual(quotes.iloc[0]["market_cap"], 100000.0)
        self.assertEqual(quotes.iloc[0]["price"], 12.3)
        self.assertEqual(quotes.iloc[0]["exchange"], "深圳交易所")


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
        self.assertListEqual(list(hist.columns)[:6], ["date", "open", "high", "low", "close", "volume"])


if __name__ == "__main__":
    unittest.main()
