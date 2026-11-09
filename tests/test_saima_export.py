"""离线测试：Saima 阶段 0 资金流快照导出。不访问外网。"""

import io
import json
import math
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from src.analysis.saima_export import (
    KIND,
    build_saima_snapshot,
    extract_sector_leaders,
    format_archive_line,
    format_generated_at,
    main,
    resolve_as_of_date,
    resolve_output_path,
    to_jsonable,
    write_saima_snapshot,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
REQUIRED_NATIVE = (
    "bias",
    "horizon",
    "confidence",
    "confidence_label",
    "score_delta",
    "quality_ok",
    "components",
    "dropped_legs",
    "evidence",
    "net_vote",
    "label",
    "disclaimer",
)


FROZEN_SESSION = datetime(2026, 11, 9, 10, 0, tzinfo=SHANGHAI)


def _series(values, col="main_net_inflow", end=None):
    from src.data.calendar import expected_daily_data_date

    end = pd.Timestamp(end or expected_daily_data_date())
    return pd.DataFrame(
        {
            "date": pd.bdate_range(end=end, periods=len(values)),
            col: values,
        }
    )


def _industry_rank():
    frame = pd.DataFrame(
        {
            "name": ["半导体", "软件开发", "银行", "有色金属", "煤炭", "医药"],
            "net_inflow": [900.0, 800.0, 700.0, 120.0, -50.0, -80.0],
        }
    )
    frame.attrs["actual_sector"] = "行业资金流"
    frame.attrs["ok"] = True
    return frame


def _good_market():
    return _series([80, 90, 100, 110, 120, 130])


def _good_north():
    return _series([50, 60, 70, 80, 90, 100], col="net_inflow")


def _assert_json_plain(testcase, value, path=""):
    if isinstance(value, dict):
        for key, item in value.items():
            testcase.assertIsInstance(key, str, path)
            _assert_json_plain(testcase, item, f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _assert_json_plain(testcase, item, f"{path}[{index}]")
        return
    testcase.assertNotIsInstance(value, (np.generic, pd.Timestamp, pd.DataFrame, pd.Series), path)
    testcase.assertIn(type(value), (str, int, float, bool, type(None)), msg=f"{path}: {type(value)}")
    if isinstance(value, float):
        testcase.assertTrue(math.isfinite(value), path)


class SaimaExportHelperTests(unittest.TestCase):
    def test_as_of_date_and_generated_at(self):
        now = datetime(2026, 11, 6, 17, 15, 0, tzinfo=SHANGHAI)
        self.assertEqual(resolve_as_of_date(None, now=now), "2026-11-06")
        self.assertEqual(resolve_as_of_date("2026-11-05"), "2026-11-05")
        self.assertEqual(format_generated_at(now), "2026-11-06T17:15:00+08:00")

    def test_to_jsonable_strips_numpy_and_nan(self):
        payload = to_jsonable(
            {
                "ok": np.bool_(True),
                "score": np.float64(1.5),
                "count": np.int64(3),
                "missing": np.nan,
                "inf": np.inf,
                "when": pd.Timestamp("2026-11-06"),
            }
        )
        self.assertIs(payload["ok"], True)
        self.assertEqual(payload["score"], 1.5)
        self.assertEqual(payload["count"], 3)
        self.assertIsNone(payload["missing"])
        self.assertIsNone(payload["inf"])
        self.assertEqual(payload["when"], "2026-11-06")
        json.dumps(payload, ensure_ascii=False, allow_nan=False)

    def test_archive_line_uses_lowercase_bool(self):
        line = format_archive_line("2026-11-06", "偏多", True, "/tmp/2026-11-06.json")
        self.assertEqual(
            line,
            "BigA fund_flow 2026-11-06 archived bias=偏多 quality_ok=true path=/tmp/2026-11-06.json",
        )
        self.assertIn("quality_ok=false", format_archive_line("2026-11-06", "中性", False, "x.json"))


class SaimaSnapshotTests(unittest.TestCase):
    def setUp(self):
        from src.data.calendar import set_now_override

        set_now_override(FROZEN_SESSION)

    def tearDown(self):
        from src.data.calendar import set_now_override

        set_now_override(None)

    def test_three_legs_export_fields_json_and_leaders(self):
        now = datetime(2026, 11, 6, 17, 15, 0, tzinfo=SHANGHAI)
        snapshot = build_saima_snapshot(
            as_of_date="2026-11-06",
            now=now,
            fetch_market=_good_market,
            fetch_north=_good_north,
            fetch_sector=_industry_rank,
        )
        self.assertEqual(snapshot["as_of_date"], "2026-11-06")
        self.assertEqual(snapshot["generated_at"], "2026-11-06T17:15:00+08:00")
        self.assertEqual(snapshot["kind"], KIND)
        self.assertEqual(snapshot["kind"], "fund_flow_snapshot")
        for key in REQUIRED_NATIVE:
            self.assertIn(key, snapshot)
        self.assertEqual(snapshot["horizon"], "1-5日")
        self.assertIn(snapshot["bias"], {"偏多", "偏空", "中性", "分化"})
        self.assertEqual(snapshot["bias"], "偏多")
        self.assertTrue(snapshot["quality_ok"])
        self.assertIsInstance(snapshot["quality_ok"], bool)
        self.assertGreater(snapshot["score_delta"], 0)
        self.assertGreaterEqual(snapshot["score_delta"], -2)
        self.assertLessEqual(snapshot["score_delta"], 2)
        self.assertIsInstance(snapshot["components"], dict)
        self.assertIsInstance(snapshot["dropped_legs"], list)
        self.assertIsInstance(snapshot["evidence"], list)
        self.assertIsInstance(snapshot["disclaimer"], str)
        self.assertEqual(snapshot["divergences"], [])
        self.assertEqual(snapshot["watches"], [])
        self.assertIsInstance(snapshot["known_gaps"], list)
        self.assertEqual(
            snapshot["sector_leaders"],
            ["半导体", "软件开发", "银行", "有色金属", "煤炭"],
        )
        from src.data.calendar import expected_daily_data_date

        self.assertEqual(snapshot["latest_trade_date"], expected_daily_data_date(now).isoformat())
        encoded = json.dumps(snapshot, ensure_ascii=False, allow_nan=False)
        self.assertNotIn("NaN", encoded)
        self.assertNotIn("Infinity", encoded)
        _assert_json_plain(self, snapshot)
        line = format_archive_line(
            snapshot["as_of_date"],
            snapshot["bias"],
            snapshot["quality_ok"],
            "/workspace/Saima/inbox/biga/2026-11-06.json",
        )
        self.assertEqual(
            line,
            "BigA fund_flow 2026-11-06 archived bias=偏多 quality_ok=true "
            "path=/workspace/Saima/inbox/biga/2026-11-06.json",
        )

    def test_bad_leg_dropped_still_exports(self):
        north = _good_north()
        north.attrs["ok"] = False
        north.attrs["issues"] = ["all-zero amounts"]
        snapshot = build_saima_snapshot(
            as_of_date="2026-11-06",
            fetch_market=_good_market,
            fetch_north=lambda: north,
            fetch_sector=_industry_rank,
        )
        self.assertIn("north", snapshot["dropped_legs"])
        self.assertTrue(snapshot["quality_ok"])
        self.assertEqual(snapshot["bias"], "偏多")
        self.assertGreater(snapshot["score_delta"], 0)
        self.assertTrue(snapshot["known_gaps"])
        self.assertTrue(any("北向" in item for item in snapshot["known_gaps"]))
        json.dumps(snapshot, ensure_ascii=False, allow_nan=False)

    def test_all_legs_failed_is_insufficient(self):
        empty = pd.DataFrame()
        bad = _good_market()
        bad.attrs["ok"] = False
        bad.attrs["issues"] = ["all-zero amounts"]

        def boom():
            raise TimeoutError("akshare timeout")

        cases = {
            "empty": (lambda: empty, lambda: empty, lambda: empty),
            "exceptions": (boom, boom, boom),
            "bad": (lambda: bad, lambda: bad, lambda: bad),
        }
        for name, (market, north, sector) in cases.items():
            with self.subTest(name=name):
                snapshot = build_saima_snapshot(
                    as_of_date="2026-11-06",
                    fetch_market=market,
                    fetch_north=north,
                    fetch_sector=sector,
                )
                self.assertEqual(snapshot["bias"], "中性")
                self.assertFalse(snapshot["quality_ok"])
                self.assertEqual(snapshot["score_delta"], 0)
                self.assertEqual(snapshot["kind"], "fund_flow_snapshot")
                self.assertEqual(snapshot["as_of_date"], "2026-11-06")
                self.assertIsInstance(snapshot["known_gaps"], list)
                json.dumps(snapshot, ensure_ascii=False, allow_nan=False)

    def test_sector_leaders_empty_when_unusable(self):
        self.assertEqual(extract_sector_leaders(pd.DataFrame()), [])
        concept = pd.DataFrame({"name": ["人工智能", "算力"], "net_inflow": [9, 8]})
        concept.attrs["actual_sector"] = "概念资金流"
        self.assertEqual(extract_sector_leaders(concept), [])
        bad = _industry_rank()
        bad.attrs["ok"] = False
        self.assertEqual(extract_sector_leaders(bad), [])

    def test_only_zero_north_export_is_insufficient(self):
        north = _series([0, 0, 0, 0, 0, 0], col="net_inflow")
        snapshot = build_saima_snapshot(
            as_of_date="2026-11-09",
            now=FROZEN_SESSION,
            fetch_market=lambda: pd.DataFrame(),
            fetch_north=lambda: north,
            fetch_sector=lambda: pd.DataFrame(),
        )
        self.assertEqual(snapshot["as_of_date"], "2026-11-09")
        self.assertEqual(snapshot["bias"], "中性")
        self.assertFalse(snapshot["quality_ok"])
        self.assertTrue(snapshot.get("insufficient"))
        self.assertEqual(snapshot["score_delta"], 0)
        self.assertEqual(snapshot["confidence"], 0)
        from src.data.calendar import expected_daily_data_date

        self.assertEqual(
            snapshot["latest_trade_date"],
            expected_daily_data_date(FROZEN_SESSION).isoformat(),
        )
        self.assertEqual(snapshot["latest_trade_date"], "2026-11-06")
        self.assertNotEqual(snapshot["as_of_date"], snapshot["latest_trade_date"])
        json.dumps(snapshot, ensure_ascii=False, allow_nan=False)


class SaimaCliTests(unittest.TestCase):
    def test_write_and_cli_inbox_dir(self):
        now = datetime(2026, 11, 6, 17, 15, 0, tzinfo=SHANGHAI)
        snapshot = build_saima_snapshot(
            as_of_date="2026-11-06",
            now=now,
            fetch_market=_good_market,
            fetch_north=_good_north,
            fetch_sector=_industry_rank,
        )
        with tempfile.TemporaryDirectory() as tmp:
            inbox = Path(tmp) / "Saima" / "inbox" / "biga"
            target = resolve_output_path("2026-11-06", inbox_dir=inbox)
            write_saima_snapshot(snapshot, target)
            self.assertTrue(target.exists())
            loaded = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(loaded["as_of_date"], "2026-11-06")
            self.assertEqual(loaded["kind"], "fund_flow_snapshot")
            leftover = list(inbox.glob("*.tmp"))
            self.assertEqual(leftover, [])

            fake = dict(snapshot)
            stdout = io.StringIO()
            with mock.patch("src.analysis.saima_export.build_saima_snapshot", return_value=fake):
                with mock.patch("sys.stdout", stdout):
                    code = main(["--date", "2026-11-06", "--inbox-dir", str(inbox)])
            self.assertEqual(code, 0)
            line = stdout.getvalue().strip()
            self.assertEqual(
                line,
                format_archive_line("2026-11-06", fake["bias"], fake["quality_ok"], target),
            )
            self.assertIn("quality_ok=true", line)
            self.assertTrue(line.startswith("BigA fund_flow 2026-11-06 archived"))


if __name__ == "__main__":
    unittest.main()
