"""离线测试：资金流 schema / 单位 / 分析助手。不访问外网。"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from src.analysis.fund_flow import (
    actual_period_label,
    actual_sector_label,
    apply_fund_flow_bias,
    divergence_reading,
    enrich_sector_flow,
    extreme_rows,
    flow_acceleration,
    format_wan,
    fund_flow_bias,
    latest_stock_snapshot,
    main_vs_retail,
    northbound_regime,
    price_flow_divergence,
    rank_inflow,
    rank_outflow,
    scope_fallback_note,
    sector_rotation_stats,
    stock_flow_notes,
    summarize_rank,
    unit_caption,
)
from src.data.quality import (
    attach_rank_scope,
    canonicalize_flow_columns,
    derive_bucket_nets,
    empty_flow,
    infer_amount_unit,
    normalize_flow_indicator,
    normalize_sector_type,
    prepare_cross_border,
    prepare_flow_rank,
    prepare_market_flow,
    prepare_stock_flow,
    scale_to_wan,
    validate_flow_rank,
    validate_stock_flow,
)


class FlowQualityTests(unittest.TestCase):
    def test_indicator_and_sector_aliases(self):
        self.assertEqual(normalize_flow_indicator("1d"), "今日")
        self.assertEqual(normalize_flow_indicator("5d"), "5日")
        self.assertEqual(normalize_flow_indicator(None), "今日")
        self.assertEqual(normalize_sector_type("industry"), "行业资金流")
        self.assertEqual(normalize_sector_type("概念"), "概念资金流")

    def test_canonicalize_period_prefix(self):
        raw = pd.DataFrame(
            {
                "名称": ["银行"],
                "今日主力净流入-净额": [1.2e8],
                "今日涨跌幅": [1.5],
                "今日超大单净流入-净额": [8e7],
                "今日小单净流入-净额": [-2e7],
            }
        )
        work = canonicalize_flow_columns(raw)
        self.assertIn("主力净流入-净额", work.columns)
        self.assertIn("涨跌幅", work.columns)
        df = prepare_flow_rank(raw, source="test", period="今日", amount_unit="yuan")
        self.assertFalse(df.empty)
        self.assertAlmostEqual(df.iloc[0]["net_inflow"], 12000.0)
        self.assertAlmostEqual(df.iloc[0]["super_large_net"], 8000.0)
        self.assertAlmostEqual(df.iloc[0]["small_net"], -2000.0)
        self.assertEqual(df.attrs.get("unit"), "万元")
        self.assertEqual(df.attrs.get("source"), "test")
        ok, issues = validate_flow_rank(df)
        self.assertTrue(ok, issues)

    def test_prepare_stock_flow_from_tushare_moneyflow(self):
        raw = pd.DataFrame(
            {
                "trade_date": ["20240103", "20240102", "20240104"],
                "ts_code": ["000001.SZ"] * 3,
                "net_mf_amount": [1000.0, 800.0, 1200.0],
                "buy_elg_amount": [3000, 2000, 3500],
                "sell_elg_amount": [1000, 1500, 1000],
                "buy_lg_amount": [800, 600, 900],
                "sell_lg_amount": [400, 500, 300],
                "buy_sm_amount": [100, 200, 150],
                "sell_sm_amount": [500, 100, 400],
            }
        )
        derived = derive_bucket_nets(raw)
        self.assertAlmostEqual(derived.iloc[0]["super_large_net"], 2000)
        df = prepare_stock_flow(raw, source="tushare", code="000001", amount_unit="wan")
        self.assertEqual(len(df), 3)
        self.assertTrue(df["date"].is_monotonic_increasing)
        self.assertIn("main_net_inflow", df.columns)
        self.assertEqual(df.iloc[-1]["code"], "000001")
        ok, issues = validate_stock_flow(df)
        self.assertTrue(ok, issues)

    def test_prepare_stock_flow_rejects_short_code(self):
        df = prepare_stock_flow(pd.DataFrame(), source="test", code="1")
        self.assertTrue(df.empty)
        self.assertIn("invalid stock code", df.attrs.get("issues", []))

    def test_prepare_stock_flow_filters_dates(self):
        raw = pd.DataFrame(
            {
                "日期": ["20240101", "20240102", "20240103"],
                "主力净流入-净额": [1e8, 2e8, 3e8],
            }
        )
        df = prepare_stock_flow(
            raw, source="akshare", code="000001", start="20240102", end="20240103", amount_unit="yuan"
        )
        self.assertEqual(len(df), 2)
        self.assertEqual(df["date"].min(), pd.Timestamp("2024-01-02"))

    def test_northbound_unit_inference_yi(self):
        raw = pd.DataFrame(
            {
                "日期": ["20240101", "20240102", "20240103"],
                "当日成交净买额": [20.0, -15.0, 30.0],
            }
        )
        self.assertEqual(infer_amount_unit(raw["当日成交净买额"], "northbound"), "yi")
        df = prepare_cross_border(raw, source="test", amount_unit="auto")
        self.assertAlmostEqual(df.iloc[-1]["net_inflow"], 300000.0)
        self.assertEqual(df.attrs.get("unit"), "万元")

    def test_duplicate_south_leg_is_dropped(self):
        raw = pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=6, freq="D"),
                "north_inflow": [10.0, 20.0, -5.0, 8.0, 12.0, 9.0],
                "south_inflow": [10.0, 20.0, -5.0, 8.0, 12.0, 9.0],
            }
        )
        df = prepare_cross_border(raw, source="test", amount_unit="wan")
        self.assertTrue(df["south_inflow"].isna().all())
        self.assertIn("southbound matched northbound; dropped duplicate leg", df.attrs.get("issues", []))

    def test_northbound_tushare_baiwan(self):
        raw = pd.DataFrame(
            {
                "trade_date": ["20240101", "20240102"],
                "north_money": [2000.0, -800.0],
                "south_money": [500.0, 100.0],
            }
        )
        df = prepare_cross_border(raw, source="tushare", amount_unit="baiwan")
        self.assertAlmostEqual(df.iloc[0]["north_inflow"], 200000.0)
        self.assertAlmostEqual(df.iloc[0]["south_inflow"], 50000.0)
        self.assertAlmostEqual(df.iloc[0]["net_inflow"], 200000.0)

    def test_market_flow_and_scale(self):
        raw = pd.DataFrame(
            {
                "日期": ["20240101"],
                "主力净流入-净额": [5e9],
                "小单净流入-净额": [-1e9],
            }
        )
        df = prepare_market_flow(raw, source="akshare", amount_unit="yuan")
        self.assertAlmostEqual(df.iloc[0]["main_net_inflow"], 500000.0)
        scaled = scale_to_wan(pd.DataFrame({"net_inflow": [10000.0]}), ["net_inflow"], "wan")
        self.assertAlmostEqual(scaled.iloc[0]["net_inflow"], 10000.0)

    def test_attach_rank_scope_records_period_and_sector_fallback(self):
        raw = pd.DataFrame(
            {
                "名称": ["银行", "地产"],
                "主力净流入-净额": [10000.0, -2000.0],
            }
        )
        df = prepare_flow_rank(raw, source="test", period="今日", amount_unit="wan")
        scoped = attach_rank_scope(
            df,
            requested_period="5日",
            actual_period="今日",
            requested_sector="概念资金流",
            actual_sector="行业资金流",
        )
        self.assertEqual(scoped.attrs.get("actual_period"), "今日")
        self.assertEqual(scoped.attrs.get("requested_period"), "5日")
        self.assertEqual(scoped.attrs.get("actual_sector"), "行业资金流")
        self.assertIn("period_fallback:5日→今日", scoped.attrs.get("issues", []))
        self.assertIn("sector_fallback:概念资金流→行业资金流", scoped.attrs.get("issues", []))
        self.assertTrue((scoped["period"] == "今日").all())
        self.assertEqual(actual_period_label(scoped, "5日"), "今日")
        self.assertEqual(actual_sector_label(scoped, "概念"), "行业")
        note = scope_fallback_note(scoped, requested_period="5日", requested_sector="概念")
        self.assertIn("5日→今日", note)
        caption = unit_caption(scoped, requested_period="5日")
        self.assertIn("周期: 今日", caption)
        self.assertIn("请求周期: 5日", caption)

    def test_all_zero_and_bucket_consistency(self):
        zeros = prepare_flow_rank(
            pd.DataFrame({"名称": ["A", "B"], "主力净流入-净额": [0.0, 0.0]}),
            source="test",
            amount_unit="wan",
        )
        self.assertIn("all-zero amounts", zeros.attrs.get("issues", []))
        self.assertFalse(zeros.attrs.get("ok"))

        inconsistent = pd.DataFrame(
            {
                "name": ["a", "b", "c", "d"],
                "net_inflow": [100.0, 100.0, 100.0, 100.0],
                "main_net_inflow": [100.0, 100.0, 100.0, 100.0],
                "super_large_net": [10.0, 10.0, 10.0, 10.0],
                "large_net": [10.0, 10.0, 10.0, 10.0],
            }
        )
        ok, issues = validate_flow_rank(inconsistent)
        self.assertTrue(ok)
        self.assertTrue(any("main_net inconsistent" in i for i in issues))

    def test_spike_flags_on_stock_flow(self):
        raw = pd.DataFrame(
            {
                "日期": pd.date_range("2024-01-01", periods=8, freq="D"),
                "主力净流入-净额": [100.0, 110.0, 90.0, 105.0, 95.0, 100.0, 80.0, 20000.0],
            }
        )
        df = prepare_stock_flow(raw, source="test", code="000001", amount_unit="wan")
        self.assertIn("is_spike", df.columns)
        self.assertTrue(bool(df["is_spike"].iloc[-1]))
        self.assertTrue(any(str(i).startswith("spike_flags:") for i in df.attrs.get("issues", [])))
        self.assertTrue(df.attrs.get("ok"))

    def test_explicit_wrong_unit_falls_back_via_sanity(self):
        raw = pd.DataFrame(
            {
                "日期": pd.date_range("2024-01-01", periods=10, freq="D"),
                "当日成交净买额": [20.0, -15.0, 30.0, 18.0, 22.0, 25.0, 19.0, 21.0, 17.0, 23.0],
            }
        )
        df = prepare_cross_border(raw, source="test", amount_unit="wan")
        self.assertAlmostEqual(df.iloc[-1]["net_inflow"], 230000.0)
        self.assertTrue(any("unit_fallback:wan→yi" in i for i in df.attrs.get("issues", [])))

    def test_empty_flow_has_schema_and_issues(self):
        empty = empty_flow("akshare", error="akshare unavailable", issues=["akshare unavailable"])
        self.assertTrue(empty.empty)
        self.assertIn("net_inflow", empty.columns)
        self.assertIn("akshare unavailable", empty.attrs.get("issues", []))
        self.assertEqual(empty.attrs.get("unit"), "万元")


class FlowAnalysisTests(unittest.TestCase):
    def _rank(self):
        return pd.DataFrame(
            {
                "name": ["银行", "地产", "半导体", "煤炭"],
                "net_inflow": [8000.0, -3000.0, 12000.0, -9000.0],
                "main_net_inflow": [8000.0, -3000.0, 12000.0, -9000.0],
                "small_net": [-2000.0, 1500.0, -4000.0, 1000.0],
            }
        )

    def test_format_wan(self):
        self.assertEqual(format_wan(12345), "1.23亿")
        self.assertEqual(format_wan(-2500), "-2500.00万")
        self.assertEqual(format_wan(None), "-")

    def test_rank_and_summary(self):
        df = self._rank()
        top = rank_inflow(df, n=2)
        self.assertEqual(list(top["name"]), ["半导体", "银行"])
        bottom = rank_outflow(df, n=1)
        self.assertEqual(bottom.iloc[0]["name"], "煤炭")
        summary = summarize_rank(df, n=2)
        self.assertEqual(summary["inflow_count"], 2)
        self.assertEqual(summary["outflow_count"], 2)
        self.assertEqual(summary["top_inflow"][0]["name"], "半导体")
        extremes = extreme_rows(df, n=1)
        self.assertEqual(set(extremes["name"]), {"半导体", "煤炭"})
        self.assertEqual(summary["total_net_inflow"], 8000.0)
        concept = df.copy()
        concept.attrs["actual_sector"] = "概念资金流"
        concept_summary = summarize_rank(concept, n=2)
        self.assertTrue(concept_summary["overlapping"])
        self.assertIsNone(concept_summary["total_net_inflow"])
        vs = main_vs_retail(concept)
        self.assertTrue(vs.get("overlapping"))
        self.assertIn("不能当作全市场", vs.get("note", ""))

    def test_main_vs_retail_and_notes(self):
        df = self._rank()
        vs = main_vs_retail(df)
        self.assertTrue(vs["main_dominates"])
        self.assertIn("主力", vs["note"])
        series = pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=6, freq="D"),
                "main_net_inflow": [100, 200, 150, 80, 90, 120],
                "small_net": [-50, -40, -30, -20, -10, -15],
            }
        )
        snap = latest_stock_snapshot(series)
        self.assertEqual(snap["latest_main"], 120)
        self.assertEqual(snap["streak"], 6)
        notes = stock_flow_notes(series)
        self.assertTrue(any("主力" in n for n in notes))

    def test_northbound_regime(self):
        df = pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=6, freq="D"),
                "net_inflow": [100, 200, 150, 80, 90, 120],
            }
        )
        regime = northbound_regime(df, window=5)
        self.assertEqual(regime["regime"], "inflow")
        out = northbound_regime(
            pd.DataFrame({"net_inflow": [-10, -20, -30]}),
            window=3,
        )
        self.assertEqual(out["regime"], "outflow")

    def test_price_flow_divergence(self):
        dates = pd.date_range("2024-01-01", periods=8, freq="D")
        price = pd.DataFrame({"date": dates, "close": [10, 10.2, 10.5, 11, 11.4, 11.8, 12.2, 12.6]})
        flow = pd.DataFrame({"date": dates, "main_net_inflow": [100, 80, -50, -80, -90, -100, -120, -150]})
        result = price_flow_divergence(price, flow, window=3, min_abs_pct=0.02, min_abs_flow=50)
        self.assertTrue(result["divergence"].any())
        self.assertTrue((result.loc[result["divergence"], "note"] == "价涨资出").any())
        self.assertFalse(result["note"].str.contains("派发|吸筹|价量").any())
        quiet = price_flow_divergence(price, flow, window=3, min_abs_pct=0.5, min_abs_flow=50)
        self.assertFalse(quiet["divergence"].any())

    def test_enrich_sector_flow(self):
        flow = pd.DataFrame({"name": ["银行", "地产"], "net_inflow": [1.0, -1.0]})
        boards = pd.DataFrame({"name": ["银行"], "change_pct": [1.2]})
        merged = enrich_sector_flow(flow, boards)
        self.assertAlmostEqual(merged.loc[merged["name"] == "银行", "change_pct"].iloc[0], 1.2)

    def test_unit_caption(self):
        df = prepare_flow_rank(
            pd.DataFrame({"名称": ["A"], "主力净流入-净额": [10000]}),
            source="akshare",
            amount_unit="wan",
        )
        text = unit_caption(df)
        self.assertIn("akshare", text)
        self.assertIn("万元", text)


class FlowBiasTests(unittest.TestCase):
    def _series(self, values, col="main_net_inflow"):
        return pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=len(values), freq="D"),
                col: values,
            }
        )

    def test_aligned_legs_are_bullish(self):
        market = self._series([80, 90, 100, 110, 120, 130])
        north = self._series([50, 60, 70, 80, 90, 100], col="net_inflow")
        stock = self._series([20, 30, 40, 50, 60, 70])
        industry = pd.DataFrame({"name": ["银行", "半导体", "煤炭"], "net_inflow": [800, 600, -50]})
        industry.attrs["actual_sector"] = "行业资金流"
        bias = fund_flow_bias(
            market_df=market, north_df=north, sector_rank=industry, stock_flow=stock
        )
        self.assertEqual(bias["bias"], "偏多")
        self.assertEqual(bias["horizon"], "1-5日")
        self.assertGreater(bias["score_delta"], 0)
        self.assertGreater(bias["confidence"], 0.5)
        self.assertTrue(bias["quality_ok"])
        self.assertEqual(bias["components"]["sector"]["sign"], 1)
        self.assertTrue(bias["components"]["sector"]["usable_for_rotation"])

    def test_conflict_is_split_with_zero_delta(self):
        market = self._series([80, 90, 100, 110, 120, 130])
        north = self._series([-50, -60, -70, -80, -90, -100], col="net_inflow")
        bias = fund_flow_bias(market_df=market, north_df=north)
        self.assertEqual(bias["bias"], "分化")
        self.assertEqual(bias["score_delta"], 0)
        self.assertLess(bias["confidence"], 0.5)
        self.assertTrue(any("冲突" in line or "分化" in line for line in bias["evidence"]))

    def test_overlapping_sector_is_not_market_total(self):
        concept = pd.DataFrame(
            {"name": ["人工智能", "ChatGPT", "算力"], "net_inflow": [9000, 8000, 7000]}
        )
        concept.attrs["actual_sector"] = "概念资金流"
        rot = sector_rotation_stats(concept)
        self.assertTrue(rot["overlapping"])
        self.assertFalse(rot["usable_for_rotation"])
        self.assertIsNone(rot["total_net_inflow"])
        self.assertEqual(rot["sign"], 0)
        bias = fund_flow_bias(sector_rank=concept)
        self.assertEqual(bias["bias"], "中性")
        self.assertEqual(bias["score_delta"], 0)
        self.assertEqual(bias["components"]["sector"]["sign"], 0)
        blob = " ".join(bias["evidence"])
        self.assertIn("重叠", blob)
        self.assertNotIn("派发", blob)
        self.assertTrue(any("不计入市场合计" in line or "重叠" in line for line in bias["evidence"]))
        self.assertFalse(any("全市场净流入" in line for line in bias["evidence"]))

    def test_bad_quality_zeroes_score_delta(self):
        market = self._series([80, 90, 100, 110, 120, 130])
        stock = self._series([20, 30, 40, 50, 60, 70])
        stock.attrs["ok"] = False
        stock.attrs["issues"] = ["all-zero amounts"]
        bias = fund_flow_bias(market_df=market, stock_flow=stock)
        self.assertFalse(bias["quality_ok"])
        self.assertEqual(bias["score_delta"], 0)
        self.assertTrue(any("质量" in line for line in bias["evidence"]))

    def test_missing_inputs_are_neutral(self):
        bias = fund_flow_bias()
        self.assertEqual(bias["bias"], "中性")
        self.assertEqual(bias["score_delta"], 0)
        self.assertEqual(bias["confidence"], 0)

    def test_acceleration_and_divergence_reading(self):
        accel_in = flow_acceleration(self._series([10, 10, 10, 10, 10, 80, 90, 100, 110, 120]), window=5)
        self.assertEqual(accel_in["label"], "加速流入")
        self.assertEqual(accel_in["sign"], 1)
        accel_out = flow_acceleration(self._series([-10, -10, -10, -10, -10, -80, -90, -100, -110, -120]), window=5)
        self.assertEqual(accel_out["label"], "加速流出")
        reading = divergence_reading("价涨资出", streak=3)
        self.assertIn("追高风险", reading)
        self.assertIn("连续3日净流入", reading)
        self.assertNotIn("派发", reading)
        self.assertNotIn("吸筹", reading)
        rebound = divergence_reading("价跌资进")
        self.assertIn("关注反弹条件", rebound)
        self.assertNotIn("吸筹", rebound)

    def test_apply_fund_flow_bias_soft_score(self):
        rec = {
            "score": 4,
            "recommendation": "持有",
            "action": "HOLD",
            "confidence": "中等",
            "reason": "信号不明确",
            "analysis_notes": ["技术面：持有"],
        }
        bull = fund_flow_bias(
            market_df=self._series([80, 90, 100, 110, 120, 130]),
            north_df=self._series([50, 60, 70, 80, 90, 100], col="net_inflow"),
            stock_flow=self._series([20, 30, 40, 50, 60, 70]),
        )
        out = apply_fund_flow_bias(rec, bull, strong_buy=10, buy=5, hold_floor=0, sell_floor=-5)
        self.assertEqual(out["score_raw"], 4)
        self.assertGreater(out["fund_score_delta"], 0)
        self.assertEqual(out["score"], 4 + out["fund_score_delta"])
        self.assertEqual(out["action"], "BUY")
        self.assertTrue(any("资金面倾向" in n for n in out["analysis_notes"]))
        bad = dict(bull)
        bad["quality_ok"] = False
        bad["score_delta"] = 2
        zeroed = apply_fund_flow_bias(rec, bad)
        self.assertEqual(zeroed["fund_score_delta"], 0)
        self.assertEqual(zeroed["score"], 4)


class FlowAdapterEmptyTests(unittest.TestCase):
    def test_disabled_akshare_flow_methods(self):
        from src.data.akshare_data import AKShareData
        from src.data.config import get_data_config

        cfg = get_data_config(reload=True)
        previous = cfg.akshare.enabled
        try:
            cfg.akshare.enabled = False
            client = AKShareData(cfg)
            sector = client.get_sector_fund_flow(allow_fallback=False)
            self.assertTrue(sector.empty)
            self.assertIn("akshare unavailable", sector.attrs.get("issues", []))
            rank = client.get_stock_fund_flow_rank(allow_fallback=False)
            self.assertTrue(rank.empty)
            stock = client.get_stock_fund_flow("1", allow_fallback=False)
            self.assertIn("invalid stock code", stock.attrs.get("issues", []))
            stock_ok_code = client.get_stock_fund_flow("000001", allow_fallback=False)
            self.assertTrue(stock_ok_code.empty)
            self.assertIn("akshare unavailable", stock_ok_code.attrs.get("issues", []))
            market = client.get_market_fund_flow(allow_fallback=False)
            self.assertTrue(market.empty)
            north = client.get_northbound_flow(allow_fallback=False)
            self.assertTrue(north.empty)
        finally:
            cfg.akshare.enabled = previous

    def test_tushare_without_token_flow_methods(self):
        import os

        from src.data.config import get_data_config, load_app_config
        from src.data.tushare_data import TuShareData

        load_app_config.cache_clear()
        os.environ.pop("TUSHARE_TOKEN", None)
        cfg = get_data_config(reload=True)
        cfg.tushare.token = ""
        client = TuShareData(cfg)
        self.assertFalse(client.is_available())
        sector = client.get_sector_fund_flow(allow_fallback=False)
        self.assertTrue(sector.empty)
        self.assertIn("tushare unavailable", sector.attrs.get("issues", []))
        stock = client.get_stock_fund_flow("000001", allow_fallback=False)
        self.assertTrue(stock.empty)
        north = client.get_northbound_flow(allow_fallback=False)
        self.assertTrue(north.empty)
        multi = client.get_sector_fund_flow(indicator="5日", allow_fallback=False)
        self.assertTrue(multi.empty)
        self.assertTrue(any("daily only" in i for i in multi.attrs.get("issues", [])))
        self.assertNotEqual(multi.attrs.get("actual_period"), "5日")
        self.assertNotEqual(multi.attrs.get("period"), "5日")
        rank_multi = client.get_stock_fund_flow_rank(indicator="5日", allow_fallback=False)
        self.assertTrue(rank_multi.empty)
        self.assertTrue(any("daily only" in i for i in rank_multi.attrs.get("issues", [])))

    def test_akshare_sector_fallback_stamps_actual_scope(self):
        from src.data.akshare_data import AKShareData
        from src.data.config import get_data_config

        cfg = get_data_config(reload=True)
        client = AKShareData(cfg)
        client.is_available = lambda: True

        class FakeAK:
            def stock_sector_fund_flow_rank(self, **kwargs):
                return pd.DataFrame()

        client._client = lambda: FakeAK()

        def fake_fetch(fn, default=None, label="", retries=1):
            if label.endswith("今日:行业资金流"):
                return pd.DataFrame(
                    {
                        "名称": ["银行"],
                        "主力净流入-净额": [1.2e8],
                    }
                )
            return pd.DataFrame()

        client._fetch = fake_fetch
        df = client.get_sector_fund_flow(
            indicator="5日", sector_type="概念", allow_fallback=False
        )
        self.assertFalse(df.empty)
        self.assertEqual(df.attrs.get("actual_period"), "今日")
        self.assertEqual(df.attrs.get("requested_period"), "5日")
        self.assertEqual(df.attrs.get("actual_sector"), "行业资金流")
        self.assertIn("period_fallback:5日→今日", df.attrs.get("issues", []))
        self.assertIn("sector_fallback:概念资金流→行业资金流", df.attrs.get("issues", []))
        self.assertTrue((df["period"] == "今日").all())


if __name__ == "__main__":
    unittest.main()
