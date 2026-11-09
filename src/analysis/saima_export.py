"""
Saima 阶段 0：市场级资金流偏向快照。

把 `market_fund_bias` 的原生字段落成 JSON，供外部治理仓
`adapt_biga(native)` 零改口消费。这是 1–5 日资金面倾向，不是涨跌预测。

单腿网络超时 / 无 Token / 空表各自降级，三腿全挂也输出合法 JSON：
bias=中性、quality_ok=False、score_delta=0。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from src.analysis.fund_flow import (
    actual_sector_label,
    frame_quality_ok,
    market_fund_bias,
    rank_inflow,
    scope_fallback_note,
)
from src.data.quality import TZ_NAME, describe_data_problems, sector_type_short

KIND = "fund_flow_snapshot"
SHANGHAI = ZoneInfo(TZ_NAME)
SECTOR_LEADERS_MAX = 5
NATIVE_BIAS_KEYS = (
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
    "scope",
    "legs_used",
    "insufficient",
)
_LEG_SPECS = (
    ("market", "市场主力资金流", "get_market_fund_flow"),
    ("north", "北向资金流", "get_northbound_flow"),
    ("sector", "行业板块资金榜", "get_sector_fund_flow"),
)


def shanghai_now(now=None):
    """当前 Asia/Shanghai 时间；naive datetime 按上海时区解释。"""
    if now is None:
        return datetime.now(SHANGHAI)
    if now.tzinfo is None:
        return now.replace(tzinfo=SHANGHAI)
    return now.astimezone(SHANGHAI)


def resolve_as_of_date(as_of_date=None, now=None):
    """顶层 as_of_date：快照请求日（上海日历），不是行情数据日。"""
    if as_of_date is None or str(as_of_date).strip() == "":
        return shanghai_now(now).date().isoformat()
    text = str(as_of_date).strip()
    datetime.strptime(text, "%Y-%m-%d")
    return text


def format_generated_at(now=None):
    """ISO-8601 秒级时间戳，固定 +08:00。"""
    dt = shanghai_now(now).replace(microsecond=0)
    return dt.isoformat(timespec="seconds")


def to_jsonable(value):
    """递归转成 json.dumps(..., allow_nan=False) 可接受的 Python 原生类型。"""
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, pd.DataFrame):
        return to_jsonable(value.to_dict(orient="records"))
    if isinstance(value, pd.Series):
        return to_jsonable(value.tolist())
    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return None
        if value.tzinfo is not None:
            return value.isoformat(timespec="seconds")
        return value.strftime("%Y-%m-%d")
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(SHANGHAI).replace(microsecond=0).isoformat(timespec="seconds")
        return value.replace(microsecond=0).isoformat(timespec="seconds")
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        number = float(value)
        if not math.isfinite(number):
            return None
        return number
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return value
    if isinstance(value, (str, int, bool)):
        return value
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item") and callable(value.item):
        try:
            return to_jsonable(value.item())
        except (ValueError, AttributeError):
            pass
    return str(value)


def _frame_has_rows(df):
    return df is not None and not getattr(df, "empty", True)


def _leg_usable(df):
    return _frame_has_rows(df) and frame_quality_ok(df)


def _frame_latest_date(df):
    if not _frame_has_rows(df) or "date" not in df.columns:
        return None
    series = pd.to_datetime(df["date"], errors="coerce")
    if not series.notna().any():
        return None
    stamp = series.max()
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert(SHANGHAI)
    return stamp.strftime("%Y-%m-%d")


def _latest_trade_date(*frames):
    dates = [item for item in (_frame_latest_date(frame) for frame in frames) if item]
    return max(dates) if dates else None


def extract_sector_leaders(sector_rank, n=SECTOR_LEADERS_MAX):
    """行业榜可用且质量合格时，取净流入 Top 3–5 名称；否则 []。"""
    if not _leg_usable(sector_rank):
        return []
    short = sector_type_short(actual_sector_label(sector_rank) or "")
    if short in ("概念", "地域"):
        return []
    ranked = rank_inflow(sector_rank, n=int(n), column="net_inflow")
    if ranked is None or ranked.empty or "name" not in ranked.columns:
        return []
    names = []
    for raw in ranked["name"].tolist():
        label = str(raw).strip()
        if label and label.lower() != "nan" and label not in names:
            names.append(label)
        if len(names) >= int(n):
            break
    return names


def _leg_gaps(label, df, error=None):
    gaps = []
    if error is not None:
        gaps.append(f"{label}不可用：{error}")
        return gaps
    if not _frame_has_rows(df):
        reason = describe_data_problems(df) if df is not None else "无数据"
        gaps.append(f"{label}不可用：{reason}")
        return gaps
    if not frame_quality_ok(df):
        reason = describe_data_problems(df) or "数据质量不足"
        gaps.append(f"{label}数据质量不足，已剔除：{reason}")
    note = scope_fallback_note(df)
    if note:
        gaps.append(f"{label}：{note}")
    for item in list(getattr(df, "attrs", {}).get("issues") or []):
        text = str(item)
        if "fallback" in text.lower() or "回退" in text:
            line = f"{label}：{text}"
            if line not in gaps:
                gaps.append(line)
    return gaps


def _dedupe(items):
    seen = set()
    out = []
    for item in items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _default_fetcher(client, method_name):
    if client is None:
        def _missing():
            raise RuntimeError("数据源不可用")

        return _missing
    method = getattr(client, method_name, None)
    if method is None:
        def _absent():
            raise AttributeError(f"client has no {method_name}")

        return _absent
    if method_name == "get_sector_fund_flow":
        return lambda: method(indicator="今日", sector_type="行业资金流")
    return method


def _resolve_client(client=None):
    if client is not None:
        return client, []
    try:
        from src.data import get_active_client

        return get_active_client(), []
    except Exception as exc:
        return None, [f"数据源不可用：{exc}"]


def _fetch_leg(label, fetcher):
    try:
        frame = fetcher()
        return frame, _leg_gaps(label, frame)
    except Exception as exc:
        return None, _leg_gaps(label, None, error=exc)


def format_archive_line(as_of_date, bias, quality_ok, path):
    flag = "true" if quality_ok else "false"
    return (
        f"BigA fund_flow {as_of_date} archived "
        f"bias={bias} quality_ok={flag} path={path}"
    )


def resolve_output_path(as_of_date, output=None, inbox_dir=None):
    if output:
        return Path(output)
    if inbox_dir:
        return Path(inbox_dir) / f"{as_of_date}.json"
    return Path(f"{as_of_date}.json")


def write_saima_snapshot(snapshot, path):
    """UTF-8 JSON，同目录临时文件后原子替换。不执行任何 git 命令。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(snapshot, ensure_ascii=False, indent=2, allow_nan=False)
    if not payload.endswith("\n"):
        payload += "\n"
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=str(target.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, target)
    except Exception:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise
    return target


def build_saima_snapshot(
    as_of_date=None,
    *,
    client=None,
    now=None,
    fetch_market=None,
    fetch_north=None,
    fetch_sector=None,
):
    """
    拉取大盘主力 / 北向 / 行业板块榜，调用 market_fund_bias，返回可 JSON 序列化的快照。

    每条腿独立 try/except。三腿全挂时仍返回合法字典：
    bias="中性", quality_ok=False, score_delta=0。
    """
    as_of = resolve_as_of_date(as_of_date, now=now)
    generated_at = format_generated_at(now)
    need_client = any(fn is None for fn in (fetch_market, fetch_north, fetch_sector))
    client_gaps = []
    if client is None and need_client:
        client, client_gaps = _resolve_client(None)
    fetchers = {
        "market": fetch_market or _default_fetcher(client, "get_market_fund_flow"),
        "north": fetch_north or _default_fetcher(client, "get_northbound_flow"),
        "sector": fetch_sector or _default_fetcher(client, "get_sector_fund_flow"),
    }

    from concurrent.futures import ThreadPoolExecutor, as_completed

    frames = {}
    known_gaps = list(client_gaps)
    # 三腿并行、超时隔离：一条腿卡住不阻塞另外两条开工。
    with ThreadPoolExecutor(max_workers=3) as pool:
        futs = {
            pool.submit(_fetch_leg, label, fetchers[name]): (name, label)
            for name, label, _method in _LEG_SPECS
        }
        for fut in as_completed(futs):
            name, label = futs[fut]
            try:
                frame, gaps = fut.result()
            except Exception as exc:
                frame, gaps = None, _leg_gaps(label, None, error=exc)
            frames[name] = frame
            known_gaps.extend(gaps)

    bias = market_fund_bias(
        market_df=frames.get("market"),
        north_df=frames.get("north"),
        sector_rank=frames.get("sector"),
    )
    native = to_jsonable(bias) or {}
    payload = {key: native.get(key) for key in NATIVE_BIAS_KEYS}
    payload["components"] = payload.get("components") or {}
    payload["dropped_legs"] = list(payload.get("dropped_legs") or [])
    payload["evidence"] = list(payload.get("evidence") or [])
    if payload.get("net_vote") is None:
        payload["net_vote"] = 0.0
    if payload.get("score_delta") is None:
        payload["score_delta"] = 0
    payload["quality_ok"] = bool(payload.get("quality_ok"))
    payload["insufficient"] = bool(native.get("insufficient") or not payload["quality_ok"])

    usable_any = any(_leg_usable(frames.get(name)) for name, _label, _method in _LEG_SPECS)
    if not usable_any:
        payload["quality_ok"] = False
        payload["score_delta"] = 0
        payload["insufficient"] = True

    snapshot = {
        "as_of_date": as_of,
        "generated_at": generated_at,
        "kind": KIND,
        **payload,
        "sector_leaders": extract_sector_leaders(frames.get("sector")),
        "divergences": [],
        "watches": [],
        "known_gaps": _dedupe(known_gaps),
    }
    latest = _latest_trade_date(frames.get("market"), frames.get("north"))
    if latest:
        snapshot["latest_trade_date"] = latest
    # as_of_date 是快照请求日；行情日以 latest_trade_date / components.*.data_date 为准。
    return to_jsonable(snapshot)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Export BigA market fund-flow bias snapshot for the Saima inbox."
    )
    parser.add_argument(
        "--date",
        dest="as_of_date",
        metavar="YYYY-MM-DD",
        default=None,
        help="Snapshot as_of_date (default: Asia/Shanghai today)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Write this JSON file (UTF-8, atomic replace)",
    )
    parser.add_argument(
        "--inbox-dir",
        default=None,
        help="Write <inbox-dir>/<as_of_date>.json; parent dirs are created",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    snapshot = build_saima_snapshot(as_of_date=args.as_of_date)
    as_of = snapshot["as_of_date"]
    path = resolve_output_path(as_of, output=args.output, inbox_dir=args.inbox_dir)
    write_saima_snapshot(snapshot, path)
    print(
        format_archive_line(as_of, snapshot.get("bias"), snapshot.get("quality_ok"), path),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
