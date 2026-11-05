"""
统一 A 股数据模式、清洗与校验。

所有适配器在返回给页面之前走这一层，保证：
- 列名英文、类型稳定
- 日期为 Asia/Shanghai 日历日（naive midnight）
- 空值 / 重复 / 明显坏 bar 被处理
- 带 source 归属
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

import numpy as np
import pandas as pd

logger = logging.getLogger("biga.data.quality")

TZ_NAME = "Asia/Shanghai"

OHLCV_COLUMNS = ["date", "open", "high", "low", "close", "volume"]
OHLCV_OPTIONAL = [
    "amount",
    "turnover",
    "change",
    "change_pct",
    "pre_close",
    "code",
    "name",
    "adjust",
    "source",
    "is_outlier",
]

QUOTE_COLUMNS = [
    "code",
    "name",
    "price",
    "open",
    "high",
    "low",
    "pre_close",
    "change",
    "change_pct",
    "volume",
    "amount",
    "turnover",
    "volume_ratio",
    "pe",
    "pb",
    "market_cap",
    "circ_mv",
    "exchange",
    "board",
    "status",
    "source",
]

LIST_COLUMNS = ["code", "name", "exchange", "board", "list_status", "source"]

OVERVIEW_COLUMNS = ["type", "count", "source"]

INDEX_COLUMNS = ["code", "name", "price", "change", "change_pct", "volume", "amount", "source"]

# 排名表（行业 / 个股）。金额统一为万元。
FLOW_COLUMNS = [
    "code",
    "name",
    "flow_type",
    "period",
    "net_inflow",
    "net_inflow_pct",
    "main_net_inflow",
    "super_large_net",
    "large_net",
    "medium_net",
    "small_net",
    "price",
    "change_pct",
    "source",
]

# 个股资金流时间序列。金额统一为万元。
STOCK_FLOW_COLUMNS = [
    "date",
    "code",
    "name",
    "close",
    "change_pct",
    "net_inflow",
    "main_net_inflow",
    "main_net_pct",
    "super_large_net",
    "super_large_pct",
    "large_net",
    "large_pct",
    "medium_net",
    "medium_pct",
    "small_net",
    "small_pct",
    "source",
]

# 北向 / 南向。金额统一为万元。
CROSS_BORDER_COLUMNS = [
    "date",
    "direction",
    "net_inflow",
    "buy_amount",
    "sell_amount",
    "north_inflow",
    "south_inflow",
    "hgt",
    "sgt",
    "source",
]

# 市场级主力资金。金额统一为万元。
MARKET_FLOW_COLUMNS = [
    "date",
    "main_net_inflow",
    "main_net_pct",
    "super_large_net",
    "large_net",
    "medium_net",
    "small_net",
    "sse_close",
    "szse_close",
    "source",
]

FLOW_MONEY_COLUMNS = [
    "net_inflow",
    "main_net_inflow",
    "super_large_net",
    "large_net",
    "medium_net",
    "small_net",
    "buy_amount",
    "sell_amount",
    "north_inflow",
    "south_inflow",
    "hgt",
    "sgt",
]

FLOW_PCT_COLUMNS = [
    "net_inflow_pct",
    "main_net_pct",
    "super_large_pct",
    "large_pct",
    "medium_pct",
    "small_pct",
    "change_pct",
]

COLUMN_ALIASES = {
    "date": ["date", "日期", "trade_date", "datetime", "时间", "day"],
    "open": ["open", "开盘", "开盘价", "今开"],
    "high": ["high", "最高", "最高价"],
    "low": ["low", "最低", "最低价"],
    "close": ["close", "收盘", "收盘价"],
    "price": ["price", "最新价", "现价", "trade", "最新"],
    "volume": ["volume", "vol", "成交量", "成交量(手)"],
    "amount": ["amount", "成交额", "成交额(元)", "成交金额"],
    "turnover": ["turnover", "turnover_rate", "换手率", "换手"],
    "change": ["change", "涨跌额", "涨跌"],
    "change_pct": ["change_pct", "pct_chg", "pct_change", "涨跌幅", "涨跌幅(%)"],
    "pre_close": ["pre_close", "prev_close", "昨收", "昨收价"],
    "code": ["code", "symbol", "ts_code", "股票代码", "代码", "品种代码"],
    "name": ["name", "名称", "股票名称", "品种名称", "指数名称"],
    "pe": ["pe", "pe_ttm", "市盈率", "市盈率-动态", "市盈率(动态)"],
    "pb": ["pb", "市净率"],
    "market_cap": ["market_cap", "total_mv", "总市值", "总市值(万元)"],
    "circ_mv": ["circ_mv", "流通市值", "流通市值(万元)"],
    "volume_ratio": ["volume_ratio", "量比"],
    "net_inflow": ["net_inflow", "净流入", "主力净流入", "净额", "north_money", "当日成交净买额"],
    "main_net_inflow": ["main_net_inflow", "主力净流入-净额", "主力净流入"],
    "main_net_pct": ["main_net_pct", "主力净流入-净占比", "主力净流入净占比"],
    "net_inflow_pct": ["net_inflow_pct", "净占比", "净流入占比"],
    "super_large_net": ["super_large_net", "超大单净流入-净额", "超大单净流入"],
    "super_large_pct": ["super_large_pct", "超大单净流入-净占比"],
    "large_net": ["large_net", "大单净流入-净额", "大单净流入"],
    "large_pct": ["large_pct", "大单净流入-净占比"],
    "medium_net": ["medium_net", "中单净流入-净额", "中单净流入"],
    "medium_pct": ["medium_pct", "中单净流入-净占比"],
    "small_net": ["small_net", "小单净流入-净额", "小单净流入"],
    "small_pct": ["small_pct", "小单净流入-净占比"],
    "buy_amount": ["buy_amount", "买入成交额", "买入金额"],
    "sell_amount": ["sell_amount", "卖出成交额", "卖出金额"],
    "north_inflow": ["north_inflow", "north_money", "北向资金", "北向净流入"],
    "south_inflow": ["south_inflow", "south_money", "南向资金", "南向净流入"],
    "hgt": ["hgt", "沪股通"],
    "sgt": ["sgt", "深股通"],
    "type": ["type", "类型", "item", "项目"],
    "count": ["count", "数量", "家数"],
    "exchange": ["exchange", "交易所", "market"],
    "board": ["board", "板块", "市场"],
    "list_status": ["list_status", "上市状态"],
    "status": ["status", "交易状态", "停牌"],
}

_NUMERIC_COLS = {
    "open",
    "high",
    "low",
    "close",
    "price",
    "volume",
    "amount",
    "turnover",
    "change",
    "change_pct",
    "pre_close",
    "pe",
    "pb",
    "market_cap",
    "circ_mv",
    "volume_ratio",
    "net_inflow",
    "net_inflow_pct",
    "main_net_inflow",
    "main_net_pct",
    "super_large_net",
    "super_large_pct",
    "large_net",
    "large_pct",
    "medium_net",
    "medium_pct",
    "small_net",
    "small_pct",
    "buy_amount",
    "sell_amount",
    "north_inflow",
    "south_inflow",
    "hgt",
    "sgt",
    "count",
}


def empty_ohlcv(source=None, extra=None, error=None, issues=None):
    cols = list(OHLCV_COLUMNS) + ["source", "is_outlier"]
    if extra:
        cols.extend(c for c in extra if c not in cols)
    df = pd.DataFrame(columns=cols)
    return stamp_frame(df, source, error=error, issues=issues)


def empty_quotes(source=None, error=None, issues=None):
    return stamp_frame(pd.DataFrame(columns=QUOTE_COLUMNS), source, error=error, issues=issues)


def empty_list(source=None, error=None, issues=None):
    return stamp_frame(pd.DataFrame(columns=LIST_COLUMNS), source, error=error, issues=issues)


def empty_overview(source=None, error=None, issues=None):
    return stamp_frame(pd.DataFrame(columns=OVERVIEW_COLUMNS), source, error=error, issues=issues)


def empty_index(source=None, error=None, issues=None):
    return stamp_frame(pd.DataFrame(columns=INDEX_COLUMNS), source, error=error, issues=issues)


def empty_flow(source=None, error=None, issues=None):
    return stamp_flow(
        pd.DataFrame(columns=FLOW_COLUMNS),
        source,
        error=error,
        issues=issues,
        flow_type="rank",
    )


def empty_stock_flow(source=None, error=None, issues=None):
    return stamp_flow(
        pd.DataFrame(columns=STOCK_FLOW_COLUMNS),
        source,
        error=error,
        issues=issues,
        flow_type="stock",
    )


def empty_cross_border(source=None, error=None, issues=None, direction="northbound"):
    return stamp_flow(
        pd.DataFrame(columns=CROSS_BORDER_COLUMNS),
        source,
        error=error,
        issues=issues,
        flow_type="cross_border",
        direction=direction,
    )


def empty_market_flow(source=None, error=None, issues=None):
    return stamp_flow(
        pd.DataFrame(columns=MARKET_FLOW_COLUMNS),
        source,
        error=error,
        issues=issues,
        flow_type="market",
    )


def stamp_frame(df, source=None, error=None, issues=None):
    """给 DataFrame 打上来源、时区与失败原因。空表不把 source 写成标量以免弄坏 dtype。"""
    if df is None:
        df = pd.DataFrame()
    else:
        df = df.copy()
    if source:
        if "source" not in df.columns:
            df["source"] = pd.Series(source, index=df.index, dtype="object") if len(df) else pd.Series(dtype="object")
        elif len(df):
            df["source"] = df["source"].fillna(source)
        df.attrs["source"] = source
    else:
        df.attrs["source"] = df.attrs.get("source")
    df.attrs["timezone"] = TZ_NAME
    df.attrs["fetched_at"] = datetime.now().isoformat(timespec="seconds")
    if error:
        df.attrs["error"] = error
    if issues is not None:
        df.attrs["issues"] = issues
    return df


def normalize_stock_code(code):
    """把 000001 / 000001.SZ / sz000001 统一成 6 位数字代码。"""
    if code is None:
        return ""
    text = str(code).strip().upper()
    if not text:
        return ""
    text = text.replace("SZSE", "").replace("SSE", "")
    text = re.sub(r"^(SZ|SH|BJ)\.?", "", text)
    text = text.replace(".SZ", "").replace(".SH", "").replace(".BJ", "")
    text = text.replace("XSHE", "").replace("XSHG", "")
    digits = re.sub(r"\D", "", text)
    # 必须是 6 位，禁止把 "1" 补成 000001
    if len(digits) >= 6:
        return digits[-6:]
    return ""


def to_ts_code(code):
    """6 位代码 -> TuShare ts_code。"""
    symbol = normalize_stock_code(code)
    if not symbol:
        return ""
    if symbol.startswith(("6", "9")):
        return f"{symbol}.SH"
    if symbol.startswith(("8", "4")):
        return f"{symbol}.BJ"
    return f"{symbol}.SZ"


def infer_exchange(code):
    symbol = normalize_stock_code(code)
    if symbol.startswith(("6", "9")):
        return "上海交易所"
    if symbol.startswith(("8", "4")):
        return "北京交易所"
    if symbol.startswith(("0", "2", "3")):
        return "深圳交易所"
    return "未知"


def infer_board(code, name=""):
    symbol = normalize_stock_code(code)
    name = name or ""
    if "ST" in name.upper() or "退" in name:
        prefix = "ST/"
    else:
        prefix = ""
    if symbol.startswith("30"):
        board = "创业板"
    elif symbol.startswith("68"):
        board = "科创板"
    elif symbol.startswith(("8", "4")):
        board = "北交所"
    elif symbol.startswith("60"):
        board = "沪市主板"
    elif symbol.startswith("00"):
        board = "深市主板"
    else:
        board = "未知"
    return prefix + board


def infer_limit_pct(code, name=""):
    """估算涨跌停幅度，用于涨跌停分桶（非交易所官方口径）。"""
    if name and ("ST" in name.upper() or name.startswith("*")):
        return 5.0
    symbol = normalize_stock_code(code)
    if symbol.startswith(("30", "68")):
        return 20.0
    if symbol.startswith(("8", "4")):
        return 30.0
    return 10.0


def match_exchange(code, exchange):
    """判断代码是否属于页面使用的交易所名称。"""
    if not exchange or exchange in ("所有", "全部", "all", "ALL"):
        return True
    actual = infer_exchange(code)
    aliases = {
        "深圳交易所": ("深圳交易所", "深交所", "深圳", "SZ", "SZSE", "sz"),
        "上海交易所": ("上海交易所", "上交所", "上海", "SH", "SSE", "sh"),
        "北京交易所": ("北京交易所", "北交所", "北京", "BJ", "BSE", "bj"),
    }
    wanted = str(exchange).strip()
    for canonical, names in aliases.items():
        if wanted in names or wanted == canonical:
            return actual == canonical
    return actual == wanted


def _first_present(columns, aliases):
    lower_map = {str(c).strip(): c for c in columns}
    lower_lookup = {str(c).strip().lower(): c for c in columns}
    for alias in aliases:
        if alias in lower_map:
            return lower_map[alias]
        if alias.lower() in lower_lookup:
            return lower_lookup[alias]
    return None


def rename_columns(df, extra_aliases=None):
    """按别名表把中英列名映射到标准英文字段。"""
    if df is None or df.empty:
        return df if df is not None else pd.DataFrame()
    aliases = dict(COLUMN_ALIASES)
    if extra_aliases:
        for key, values in extra_aliases.items():
            aliases[key] = list(values) + list(aliases.get(key, []))
    mapping = {}
    used = set()
    for standard, names in aliases.items():
        raw = _first_present(df.columns, names)
        if raw is not None and raw not in used and standard not in df.columns:
            mapping[raw] = standard
            used.add(raw)
    if mapping:
        df = df.rename(columns=mapping)
    return df


def parse_dates(series):
    """把 YYYYMMDD / YYYY-MM-DD / datetime 解析为 naive 日历日。"""
    if series is None:
        return pd.Series(dtype="datetime64[ns]")
    values = series
    if hasattr(values, "dt") and pd.api.types.is_datetime64_any_dtype(values):
        if getattr(values.dt, "tz", None) is not None:
            try:
                values = values.dt.tz_convert(TZ_NAME)
            except (TypeError, AttributeError):
                values = values.dt.tz_localize(TZ_NAME)
            values = values.dt.tz_localize(None)
        return values.dt.normalize()
    text = pd.Series(values).astype(str).str.strip()
    compact = text.str.replace(r"\D", "", regex=True)
    eight = compact.where(compact.str.len() < 8, compact.str.slice(0, 8))
    parsed = pd.to_datetime(eight, format="%Y%m%d", errors="coerce")
    missing = parsed.isna()
    if missing.any():
        parsed.loc[missing] = pd.to_datetime(text[missing], errors="coerce")
    return parsed.dt.normalize()


def to_numeric(series):
    if series is None:
        return pd.Series(dtype="float64")
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce")
    cleaned = (
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("%", "", regex=False)
        .str.replace("—", "", regex=False)
        .str.replace("None", "", regex=False)
        .str.strip()
    )
    return pd.to_numeric(cleaned.replace("", np.nan), errors="coerce")


def coerce_numerics(df, columns=None):
    if df is None or df.empty:
        return df
    df = df.copy()
    for col in columns or _NUMERIC_COLS:
        if col in df.columns:
            df[col] = to_numeric(df[col])
    return df


def normalize_ohlcv(df, source=None, code=None, adjust=None):
    """把任意历史行情表标准化为 date/open/high/low/close/volume。"""
    if df is None or (isinstance(df, pd.DataFrame) and df.empty):
        return empty_ohlcv(source)

    work = df.copy()
    if not isinstance(work, pd.DataFrame):
        return empty_ohlcv(source)

    if work.index.name in ("date", "日期", "trade_date") or (
        isinstance(work.index, pd.DatetimeIndex)
    ):
        work = work.reset_index()

    work = rename_columns(work)
    if "date" not in work.columns:
        for candidate in work.columns:
            if "date" in str(candidate).lower() or "日期" in str(candidate):
                work = work.rename(columns={candidate: "date"})
                break
    if "date" not in work.columns:
        logger.warning("历史数据缺少日期列: %s", list(work.columns))
        return empty_ohlcv(source, issues=["missing date column"])

    work["date"] = parse_dates(work["date"])
    work = coerce_numerics(work)

    if code:
        work["code"] = normalize_stock_code(code)
    elif "code" in work.columns:
        work["code"] = work["code"].map(normalize_stock_code)

    if adjust is not None:
        work["adjust"] = adjust
    if source:
        work["source"] = source

    keep = [c for c in OHLCV_COLUMNS + OHLCV_OPTIONAL if c in work.columns]
    work = work[keep]
    work = stamp_frame(work, source)
    return work


def clean_ohlcv(df, max_abs_return=1.0, drop_outliers=False):
    """清洗空行、重复日期、非法 OHLC，钳制 high/low，并标记异常涨跌幅。"""
    source = None
    if df is not None:
        source = df.attrs.get("source") or (
            df["source"].iloc[0] if "source" in df.columns and len(df) else None
        )
    if df is None or df.empty:
        return empty_ohlcv(source, issues=["empty frame"])

    work = df.copy()
    needed = [c for c in ("date", "open", "high", "low", "close") if c in work.columns]
    work = work.dropna(subset=needed)

    for col in ("open", "high", "low", "close"):
        if col in work.columns:
            work = work[~(work[col] <= 0)]

    if {"open", "high", "low", "close"}.issubset(work.columns) and len(work):
        highs = work[["open", "high", "low", "close"]].max(axis=1)
        lows = work[["open", "high", "low", "close"]].min(axis=1)
        work["high"] = highs
        work["low"] = lows

    if "volume" in work.columns:
        work.loc[work["volume"] < 0, "volume"] = np.nan
        work["volume"] = work["volume"].fillna(0)

    if "date" in work.columns:
        work = work.sort_values("date")
        work = work.drop_duplicates(subset=["date"], keep="last")

    if "close" in work.columns and len(work) >= 2:
        ret = work["close"].pct_change().abs()
        work["is_outlier"] = ret > float(max_abs_return)
        work["is_outlier"] = work["is_outlier"].fillna(False)
        if drop_outliers:
            work = work[~work["is_outlier"]]
    else:
        work["is_outlier"] = False

    work = work.reset_index(drop=True)
    if work.empty:
        return empty_ohlcv(source, issues=["all bars dropped by cleaner"])
    return stamp_frame(work, source)


def validate_ohlcv(df, min_bars=1):
    """返回 (ok, issues)。空表、缺列、坏 bar、重复日期都算失败。"""
    issues = []
    if df is None or df.empty:
        return False, ["empty frame"]
    for col in OHLCV_COLUMNS:
        if col not in df.columns:
            issues.append(f"missing column: {col}")
    if issues:
        return False, issues
    if df["date"].isna().any():
        issues.append("null dates")
    if df["close"].isna().any():
        issues.append("null close")
    for col in ("open", "high", "low", "close"):
        bad = df[col].isna() | (df[col] <= 0)
        if bad.any():
            issues.append(f"invalid {col}")
    if (df["high"] < df["low"]).any():
        issues.append("high < low")
    outside = (df["close"] > df["high"]) | (df["close"] < df["low"])
    if outside.any():
        issues.append("close outside high/low")
    if len(df) != df["date"].nunique():
        issues.append("duplicate dates remain")
    if not df["date"].is_monotonic_increasing:
        issues.append("dates not sorted")
    if len(df) < int(min_bars):
        issues.append(f"fewer than {min_bars} bars")
    return len(issues) == 0, issues


def normalize_quotes(df, source=None, market_cap_unit="yuan"):
    """标准化实时/快照行情。market_cap 统一为万元。"""
    if df is None or (isinstance(df, pd.DataFrame) and df.empty):
        return empty_quotes(source)

    work = rename_columns(df.copy())
    work = coerce_numerics(work)

    if "code" in work.columns:
        work["code"] = work["code"].map(normalize_stock_code)
        work = work[work["code"].astype(str).str.len() == 6]
        if work.empty:
            return empty_quotes(source, issues=["no valid stock codes"])
    if "price" not in work.columns and "close" in work.columns:
        work["price"] = work["close"]

    if "market_cap" in work.columns:
        if market_cap_unit == "yuan":
            work["market_cap"] = work["market_cap"] / 10000.0
        elif market_cap_unit == "yi":
            work["market_cap"] = work["market_cap"] * 10000.0
    if "circ_mv" in work.columns:
        if market_cap_unit == "yuan":
            work["circ_mv"] = work["circ_mv"] / 10000.0
        elif market_cap_unit == "yi":
            work["circ_mv"] = work["circ_mv"] * 10000.0

    if "code" in work.columns:
        work["exchange"] = work["code"].map(infer_exchange)
        names = work["name"] if "name" in work.columns else ""
        work["board"] = [
            infer_board(code, name)
            for code, name in zip(work["code"], names if len(names) else [""] * len(work))
        ]

    if "status" not in work.columns:
        work["status"] = "trading"
        if "price" in work.columns:
            halted = work["price"].isna() | (work["price"] <= 0)
            work.loc[halted, "status"] = "halted"
        if "name" in work.columns:
            work.loc[work["name"].astype(str).str.contains("停牌", na=False), "status"] = "halted"

    if source:
        work["source"] = source

    keep = [c for c in QUOTE_COLUMNS if c in work.columns]
    work = work[keep]
    return stamp_frame(work, source)


def normalize_stock_list(df, source=None):
    if df is None or (isinstance(df, pd.DataFrame) and df.empty):
        return empty_list(source)
    work = rename_columns(df.copy())
    if "code" in work.columns:
        work["code"] = work["code"].map(normalize_stock_code)
        work = work[work["code"].astype(str).str.len() == 6]
        if work.empty:
            return empty_list(source, issues=["no valid stock codes"])
        work["exchange"] = work["code"].map(infer_exchange)
        names = work["name"] if "name" in work.columns else pd.Series([""] * len(work))
        if "board" not in work.columns:
            work["board"] = [
                infer_board(code, name) for code, name in zip(work["code"], names)
            ]
    if "list_status" not in work.columns:
        work["list_status"] = "L"
    if source:
        work["source"] = source
    keep = [c for c in LIST_COLUMNS if c in work.columns]
    quote_extras = [c for c in QUOTE_COLUMNS if c in work.columns and c not in keep]
    return stamp_frame(work[keep + quote_extras], source)


def compact_date(value):
    """任意日期 → YYYYMMDD 字符串；空值返回空串。

    先认 YYYYMMDD，再用 pandas 解析 ``2024-1-2`` / ``2024/01/02``，
    避免只抽数字时把 ``2024-1-2`` 收成 ``202412``。
    """
    if value is None or value == "":
        return ""
    if hasattr(value, "strftime"):
        try:
            return value.strftime("%Y%m%d")
        except (ValueError, OverflowError, TypeError):
            pass
    text = str(value).strip()
    if not text or text.lower() in ("nat", "none", "nan"):
        return ""
    if len(text) == 8 and text.isdigit():
        return text
    ts = pd.to_datetime(text, errors="coerce")
    if pd.notna(ts):
        return pd.Timestamp(ts).strftime("%Y%m%d")
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits[:8] if len(digits) >= 8 else ""


def ordered_date_range(start=None, end=None):
    """返回 (start, end, swapped)，起止均为 YYYYMMDD；颠倒时交换。"""
    start_key = compact_date(start)
    end_key = compact_date(end)
    swapped = bool(start_key and end_key and start_key > end_key)
    if swapped:
        start_key, end_key = end_key, start_key
    return start_key, end_key, swapped


def attach_date_swap(df, swapped):
    """给返回表打上 date_range_swapped，避免改到缓存里的原表。"""
    if df is None or not swapped:
        return df
    work = df.copy()
    work.attrs["date_range_swapped"] = True
    issues = list(work.attrs.get("issues") or [])
    if "start/end dates swapped" not in issues:
        issues.append("start/end dates swapped")
    work.attrs["issues"] = issues
    return work


def normalize_period(period):
    mapping = {
        "daily": "daily",
        "d": "daily",
        "日线": "daily",
        "日": "daily",
        "weekly": "weekly",
        "w": "weekly",
        "周线": "weekly",
        "周": "weekly",
        "monthly": "monthly",
        "m": "monthly",
        "月线": "monthly",
        "月": "monthly",
    }
    if period is None:
        return "daily"
    text = str(period).strip()
    return mapping.get(text.lower(), mapping.get(text, "daily"))


def normalize_adjust(adjust):
    if adjust is None:
        return ""
    text = str(adjust).strip()
    mapping = {
        "": "",
        "none": "",
        "raw": "",
        "nadj": "",
        "qfq": "qfq",
        "hfq": "hfq",
        "前复权": "qfq",
        "后复权": "hfq",
        "不复权": "",
    }
    return mapping.get(text, mapping.get(text.lower(), text))


def filter_date_range(df, start=None, end=None):
    """按日期裁剪；若起止颠倒则交换，并在 attrs['date_range_swapped'] 标记。"""
    if df is None or df.empty or "date" not in df.columns:
        return df
    work = df
    start_key = compact_date(start)
    end_key = compact_date(end)
    start_ts = pd.to_datetime(start_key, format="%Y%m%d", errors="coerce") if start_key else pd.NaT
    end_ts = pd.to_datetime(end_key, format="%Y%m%d", errors="coerce") if end_key else pd.NaT
    swapped = bool(pd.notna(start_ts) and pd.notna(end_ts) and start_ts > end_ts)
    if swapped:
        start_ts, end_ts = end_ts, start_ts
    if pd.notna(start_ts):
        work = work[work["date"] >= start_ts]
    if pd.notna(end_ts):
        work = work[work["date"] <= end_ts]
    if work is not df:
        work = work.reset_index(drop=True)
    if swapped:
        work.attrs["date_range_swapped"] = True
    return work


def enforce_ohlcv_schema(df, source=None):
    """保证返回列齐全、顺序稳定，丢掉未知列。"""
    if df is None:
        df = pd.DataFrame()
    work = df.copy()
    for col in OHLCV_COLUMNS:
        if col not in work.columns:
            work[col] = pd.NaT if col == "date" else pd.Series(dtype="float64")
    if "is_outlier" not in work.columns:
        work["is_outlier"] = False
    if source and "source" not in work.columns and len(work):
        work["source"] = source
    ordered = [c for c in OHLCV_COLUMNS + OHLCV_OPTIONAL if c in work.columns]
    return stamp_frame(work[ordered], source or work.attrs.get("source"))


def prepare_ohlcv(
    df,
    source=None,
    code=None,
    adjust=None,
    start=None,
    end=None,
    max_abs_return=1.0,
    drop_outliers=False,
    error=None,
):
    """适配器共用：标准化 → 清洗 → 日期裁剪 → 校验，失败原因写进 attrs。"""
    if code is not None and not normalize_stock_code(code):
        return empty_ohlcv(
            source,
            error=error or f"invalid stock code: {code!r}",
            issues=["invalid stock code"],
        )
    work = normalize_ohlcv(df, source=source, code=code, adjust=adjust)
    work = clean_ohlcv(
        work,
        max_abs_return=max_abs_return,
        drop_outliers=drop_outliers,
    )
    work = filter_date_range(work, start, end)
    swapped = bool(work.attrs.get("date_range_swapped"))
    work = enforce_ohlcv_schema(work, source=source)
    ok, issues = validate_ohlcv(work)
    issues = list(issues)
    if swapped:
        issues.append("start/end dates swapped")
        work.attrs["date_range_swapped"] = True
    work.attrs["ok"] = ok
    work.attrs["issues"] = issues
    if error:
        work.attrs["error"] = error
    if not ok and work.empty:
        extra = issues or ["empty frame"]
        if swapped:
            extra = ["start/end dates swapped"] + [i for i in extra if i != "start/end dates swapped"]
        return empty_ohlcv(source, error=error, issues=extra)
    return work


def describe_data_problems(df):
    """把 attrs 里的 error / issues 收成一行，给页面空态用。"""
    if df is None:
        return "无数据"
    parts = []
    error = df.attrs.get("error")
    if error:
        parts.append(str(error))
    issues = df.attrs.get("issues") or []
    for item in issues:
        text = str(item)
        if text and text not in parts:
            parts.append(text)
    if not parts and (df.empty if hasattr(df, "empty") else True):
        return "empty frame"
    return "；".join(parts)


def outlier_count(df):
    if df is None or df.empty or "is_outlier" not in df.columns:
        return 0
    return int(pd.Series(df["is_outlier"]).fillna(False).astype(bool).sum())


def attach_meta(df, **meta):
    if df is None:
        return df
    for key, value in meta.items():
        df.attrs[key] = value
    return df


# ---------------------------------------------------------------------------
# 资金流向：列名清洗、单位换算、校验
# ---------------------------------------------------------------------------

_FLOW_PERIOD_PREFIXES = ("今日", "3日", "5日", "10日")

_UNIT_TO_WAN = {
    "yuan": 1 / 10000.0,
    "元": 1 / 10000.0,
    "wan": 1.0,
    "万元": 1.0,
    "yi": 10000.0,
    "亿": 10000.0,
    "亿元": 10000.0,
    "baiwan": 100.0,
    "百万": 100.0,
    "百万元": 100.0,
}

FLOW_EXPLICIT_MAP = {
    "主力净流入-净额": "main_net_inflow",
    "主力净流入-净占比": "main_net_pct",
    "超大单净流入-净额": "super_large_net",
    "超大单净流入-净占比": "super_large_pct",
    "大单净流入-净额": "large_net",
    "大单净流入-净占比": "large_pct",
    "中单净流入-净额": "medium_net",
    "中单净流入-净占比": "medium_pct",
    "小单净流入-净额": "small_net",
    "小单净流入-净占比": "small_pct",
    "净流入-净额": "net_inflow",
    "当日成交净买额": "net_inflow",
    "当日资金流入": "net_inflow",
    "买入成交额": "buy_amount",
    "卖出成交额": "sell_amount",
    "历史累计净买额": "cumulative_net",
    "north_money": "north_inflow",
    "south_money": "south_inflow",
    "net_mf_amount": "net_inflow",
    "net_amount": "main_net_inflow",
    "net_amount_rate": "net_inflow_pct",
    "pct_change": "change_pct",
    "value": "net_inflow",
    "上证-收盘价": "sse_close",
    "深证-收盘价": "szse_close",
}

_BUY_SELL_BUCKETS = (
    ("buy_elg_amount", "sell_elg_amount", "super_large_net"),
    ("buy_lg_amount", "sell_lg_amount", "large_net"),
    ("buy_md_amount", "sell_md_amount", "medium_net"),
    ("buy_sm_amount", "sell_sm_amount", "small_net"),
)


def stamp_flow(
    df,
    source=None,
    error=None,
    issues=None,
    unit="万元",
    flow_type=None,
    period=None,
    direction=None,
):
    """stamp_frame + 资金流元数据（单位 / 类型 / 周期）。"""
    work = stamp_frame(df, source, error=error, issues=issues)
    work.attrs["unit"] = unit or "万元"
    if flow_type:
        work.attrs["flow_type"] = flow_type
    if period:
        work.attrs["period"] = period
    if direction:
        work.attrs["direction"] = direction
    return work


def normalize_flow_indicator(indicator):
    """今日 / 3日 / 5日 / 10日，兼容 1d、daily 等写法。"""
    if indicator is None:
        return "今日"
    text = str(indicator).strip()
    mapping = {
        "今日": "今日",
        "今天": "今日",
        "1日": "今日",
        "1d": "今日",
        "d1": "今日",
        "daily": "今日",
        "day": "今日",
        "3日": "3日",
        "3d": "3日",
        "d3": "3日",
        "5日": "5日",
        "5d": "5日",
        "d5": "5日",
        "10日": "10日",
        "10d": "10日",
        "d10": "10日",
    }
    return mapping.get(text, mapping.get(text.lower(), text or "今日"))


def normalize_sector_type(sector_type):
    """行业资金流 / 概念资金流 / 地域资金流。"""
    if sector_type is None:
        return "行业资金流"
    text = str(sector_type).strip()
    mapping = {
        "行业": "行业资金流",
        "行业资金流": "行业资金流",
        "industry": "行业资金流",
        "概念": "概念资金流",
        "概念资金流": "概念资金流",
        "concept": "概念资金流",
        "地域": "地域资金流",
        "地域资金流": "地域资金流",
        "region": "地域资金流",
        "area": "地域资金流",
    }
    return mapping.get(text, mapping.get(text.lower(), text or "行业资金流"))


def sector_type_short(sector_type):
    full = normalize_sector_type(sector_type)
    return {
        "行业资金流": "行业",
        "概念资金流": "概念",
        "地域资金流": "地域",
    }.get(full, full)


def canonicalize_flow_columns(df):
    """去掉东财排名表的 今日/3日/5日/10日 列名前缀。"""
    if df is None or df.empty:
        return df if df is not None else pd.DataFrame()
    mapping = {}
    for col in df.columns:
        name = str(col).strip()
        stripped = name
        for prefix in _FLOW_PERIOD_PREFIXES:
            if stripped.startswith(prefix):
                stripped = stripped[len(prefix) :]
                break
        if stripped and stripped != name:
            mapping[col] = stripped
    if mapping:
        df = df.rename(columns=mapping)
    return df


def apply_explicit_column_map(df, mapping=None):
    if df is None or df.empty:
        return df if df is not None else pd.DataFrame()
    mapping = mapping or FLOW_EXPLICIT_MAP
    rename = {}
    for raw, standard in mapping.items():
        if raw in df.columns and standard not in df.columns:
            rename[raw] = standard
    return df.rename(columns=rename) if rename else df


def derive_bucket_nets(df):
    """TuShare moneyflow：买卖额差 → 超大/大/中/小单净额，主力 = 超大 + 大。"""
    if df is None or df.empty:
        return df if df is not None else pd.DataFrame()
    work = df.copy()
    for buy, sell, dest in _BUY_SELL_BUCKETS:
        if dest not in work.columns and buy in work.columns and sell in work.columns:
            work[dest] = to_numeric(work[buy]) - to_numeric(work[sell])
    if "main_net_inflow" not in work.columns and {"super_large_net", "large_net"}.issubset(work.columns):
        work["main_net_inflow"] = to_numeric(work["super_large_net"]) + to_numeric(work["large_net"])
    return work


def infer_amount_unit(series, context="generic"):
    """
    根据量级猜测金额单位。北向单日常见量级约数十亿，个股主力常见百万～数十亿（元）。
    适配器能确定单位时应显式传入，不要依赖本函数。
    """
    values = to_numeric(series).replace([np.inf, -np.inf], np.nan).dropna()
    if values.empty:
        return "wan"
    med = float(values.abs().median())
    if context in ("northbound", "southbound", "cross_border"):
        if med >= 1e8:
            return "yuan"
        if med >= 20000:
            return "wan"
        if med >= 1500:
            return "baiwan"
        if med <= 400:
            return "yi"
        return "wan"
    if med >= 1e7:
        return "yuan"
    return "wan"


def scale_to_wan(df, columns, unit="yuan"):
    """把金额列换算为万元。unit=auto 时不处理（先 infer 再调）。"""
    if df is None or df.empty:
        return df
    key = str(unit or "wan").strip()
    factor = _UNIT_TO_WAN.get(key, _UNIT_TO_WAN.get(key.lower(), None))
    if factor is None or factor == 1.0:
        return df
    work = df.copy()
    for col in columns:
        if col in work.columns:
            work[col] = to_numeric(work[col]) * factor
    return work


def _fill_flow_aliases(work):
    if "net_inflow" not in work.columns and "main_net_inflow" in work.columns:
        work["net_inflow"] = work["main_net_inflow"]
    if "main_net_inflow" not in work.columns and "net_inflow" in work.columns:
        work["main_net_inflow"] = work["net_inflow"]
    if "net_inflow_pct" not in work.columns and "main_net_pct" in work.columns:
        work["net_inflow_pct"] = work["main_net_pct"]
    if "main_net_pct" not in work.columns and "net_inflow_pct" in work.columns:
        work["main_net_pct"] = work["net_inflow_pct"]
    return work


def _resolve_amount_unit(work, amount_unit, context, seed_columns):
    if amount_unit not in (None, "", "auto"):
        return amount_unit
    for col in seed_columns:
        if col in work.columns:
            return infer_amount_unit(work[col], context=context)
    return "wan"


def validate_flow_rank(df):
    issues = []
    if df is None or df.empty:
        return False, ["empty frame"]
    if "net_inflow" not in df.columns:
        issues.append("missing column: net_inflow")
    if "name" not in df.columns and "code" not in df.columns:
        issues.append("missing name/code")
    if "net_inflow" in df.columns and df["net_inflow"].notna().sum() == 0:
        issues.append("net_inflow all null")
    return len(issues) == 0, issues


def validate_stock_flow(df):
    issues = []
    if df is None or df.empty:
        return False, ["empty frame"]
    if "date" not in df.columns:
        issues.append("missing column: date")
    money = [c for c in ("net_inflow", "main_net_inflow") if c in df.columns]
    if not money:
        issues.append("missing inflow column")
    elif all(df[c].notna().sum() == 0 for c in money):
        issues.append("inflow all null")
    if "date" in df.columns:
        if df["date"].isna().any():
            issues.append("null dates")
        if len(df) != df["date"].nunique():
            issues.append("duplicate dates remain")
        if not df["date"].is_monotonic_increasing:
            issues.append("dates not sorted")
    return len(issues) == 0, issues


def validate_cross_border(df):
    issues = []
    if df is None or df.empty:
        return False, ["empty frame"]
    if "date" not in df.columns:
        issues.append("missing column: date")
    if "net_inflow" not in df.columns and "north_inflow" not in df.columns:
        issues.append("missing inflow column")
    if "date" in df.columns:
        if df["date"].isna().any():
            issues.append("null dates")
        if len(df) != df["date"].nunique():
            issues.append("duplicate dates remain")
        if not df["date"].is_monotonic_increasing:
            issues.append("dates not sorted")
    return len(issues) == 0, issues


def validate_market_flow(df):
    issues = []
    if df is None or df.empty:
        return False, ["empty frame"]
    if "date" not in df.columns:
        issues.append("missing column: date")
    if "main_net_inflow" not in df.columns and "net_inflow" not in df.columns:
        issues.append("missing inflow column")
    if "date" in df.columns:
        if df["date"].isna().any():
            issues.append("null dates")
        if len(df) != df["date"].nunique():
            issues.append("duplicate dates remain")
        if not df["date"].is_monotonic_increasing:
            issues.append("dates not sorted")
    return len(issues) == 0, issues


def _finalize_flow(work, source, empty_factory, validator, error=None, **meta):
    ok, issues = validator(work)
    issues = list(issues)
    work.attrs["ok"] = ok
    work.attrs["issues"] = issues
    if error:
        work.attrs["error"] = error
    if not ok and work.empty:
        return empty_factory(source, error=error, issues=issues)
    return work


def prepare_flow_rank(
    df,
    source=None,
    period="今日",
    flow_type="sector",
    amount_unit="yuan",
    error=None,
):
    """行业 / 个股资金流排名 → 标准列，金额为万元。"""
    period = normalize_flow_indicator(period)
    if df is None or (isinstance(df, pd.DataFrame) and df.empty):
        return empty_flow(source, error=error, issues=["empty frame"])
    if not isinstance(df, pd.DataFrame):
        return empty_flow(source, error=error, issues=["empty frame"])

    work = canonicalize_flow_columns(df.copy())
    work = rename_columns(work)
    work = apply_explicit_column_map(work)
    work = derive_bucket_nets(work)
    work = coerce_numerics(work)
    work = _fill_flow_aliases(work)

    money_cols = [c for c in FLOW_MONEY_COLUMNS if c in work.columns]
    unit = _resolve_amount_unit(work, amount_unit, flow_type, money_cols)
    work = scale_to_wan(work, money_cols, unit)

    if "code" in work.columns:
        work["code"] = work["code"].map(normalize_stock_code)
        work = work[work["code"].astype(str).str.len().isin((0, 6)) | work["code"].isna()].copy()
    work["flow_type"] = flow_type
    work["period"] = period
    if source:
        work["source"] = source

    keep = [c for c in FLOW_COLUMNS if c in work.columns]
    if not keep:
        return empty_flow(source, error=error, issues=["no usable flow columns"])
    work = stamp_flow(work[keep], source, unit="万元", flow_type=flow_type, period=period)
    return _finalize_flow(work, source, empty_flow, validate_flow_rank, error=error)


def prepare_stock_flow(
    df,
    source=None,
    code=None,
    start=None,
    end=None,
    amount_unit="yuan",
    error=None,
):
    """个股资金流时间序列 → 标准列，金额为万元。"""
    if code is not None and not normalize_stock_code(code):
        return empty_stock_flow(
            source,
            error=error or f"invalid stock code: {code!r}",
            issues=["invalid stock code"],
        )
    if df is None or (isinstance(df, pd.DataFrame) and df.empty):
        return empty_stock_flow(source, error=error, issues=["empty frame"])
    if not isinstance(df, pd.DataFrame):
        return empty_stock_flow(source, error=error, issues=["empty frame"])

    work = df.copy()
    if work.index.name in ("date", "日期", "trade_date") or isinstance(work.index, pd.DatetimeIndex):
        work = work.reset_index()
    work = canonicalize_flow_columns(work)
    work = rename_columns(work)
    work = apply_explicit_column_map(work)
    work = derive_bucket_nets(work)
    if "date" not in work.columns:
        return empty_stock_flow(source, error=error, issues=["missing date column"])
    work["date"] = parse_dates(work["date"])
    work = coerce_numerics(work)
    work = _fill_flow_aliases(work)

    money_cols = [c for c in FLOW_MONEY_COLUMNS if c in work.columns]
    unit = _resolve_amount_unit(work, amount_unit, "stock", money_cols)
    work = scale_to_wan(work, money_cols, unit)

    symbol = normalize_stock_code(code) if code else ""
    if symbol:
        work["code"] = symbol
    elif "code" in work.columns:
        work["code"] = work["code"].map(normalize_stock_code)
    if source:
        work["source"] = source

    work = work.dropna(subset=["date"])
    work = work.sort_values("date").drop_duplicates(subset=["date"], keep="last")
    work = filter_date_range(work, start, end)
    swapped = bool(work.attrs.get("date_range_swapped"))
    keep = [c for c in STOCK_FLOW_COLUMNS if c in work.columns]
    work = stamp_flow(work[keep].reset_index(drop=True), source, unit="万元", flow_type="stock")
    if swapped:
        work.attrs["date_range_swapped"] = True
    out = _finalize_flow(work, source, empty_stock_flow, validate_stock_flow, error=error)
    if swapped:
        issues = list(out.attrs.get("issues") or [])
        if "start/end dates swapped" not in issues:
            issues.append("start/end dates swapped")
        out.attrs["issues"] = issues
        out.attrs["date_range_swapped"] = True
    return out


def prepare_cross_border(
    df,
    source=None,
    direction="northbound",
    amount_unit="auto",
    start=None,
    end=None,
    error=None,
):
    """北向 / 南向时间序列 → 标准列，金额为万元。"""
    if df is None or (isinstance(df, pd.DataFrame) and df.empty):
        return empty_cross_border(source, error=error, issues=["empty frame"], direction=direction)
    if not isinstance(df, pd.DataFrame):
        return empty_cross_border(source, error=error, issues=["empty frame"], direction=direction)

    work = df.copy()
    if work.index.name in ("date", "日期", "trade_date") or isinstance(work.index, pd.DatetimeIndex):
        work = work.reset_index()
    work = rename_columns(work)
    work = apply_explicit_column_map(work)
    if "date" not in work.columns:
        return empty_cross_border(
            source, error=error, issues=["missing date column"], direction=direction
        )
    work["date"] = parse_dates(work["date"])
    work = coerce_numerics(work)

    if "net_inflow" not in work.columns:
        if direction == "southbound" and "south_inflow" in work.columns:
            work["net_inflow"] = work["south_inflow"]
        elif "north_inflow" in work.columns:
            work["net_inflow"] = work["north_inflow"]
        elif "south_inflow" in work.columns:
            work["net_inflow"] = work["south_inflow"]
    if "north_inflow" not in work.columns and direction != "southbound" and "net_inflow" in work.columns:
        work["north_inflow"] = work["net_inflow"]
    if "south_inflow" not in work.columns and direction == "southbound" and "net_inflow" in work.columns:
        work["south_inflow"] = work["net_inflow"]
    # 有的沪深港通接口忽略 symbol，南向会原样返回北向；丢掉重复腿，避免图表画两条一样的线。
    dropped_south = False
    if {"north_inflow", "south_inflow"}.issubset(work.columns):
        both = work[["north_inflow", "south_inflow"]].dropna()
        if len(both) >= 5 and float((both["north_inflow"] == both["south_inflow"]).mean()) >= 0.9:
            work = work.copy()
            work["south_inflow"] = pd.NA
            dropped_south = True

    money_cols = [c for c in FLOW_MONEY_COLUMNS if c in work.columns]
    unit = _resolve_amount_unit(work, amount_unit, "cross_border", money_cols or ["net_inflow"])
    work = scale_to_wan(work, money_cols, unit)
    work["direction"] = direction
    if source:
        work["source"] = source

    work = work.dropna(subset=["date"])
    work = work.sort_values("date").drop_duplicates(subset=["date"], keep="last")
    work = filter_date_range(work, start, end)
    swapped = bool(work.attrs.get("date_range_swapped"))
    keep = [c for c in CROSS_BORDER_COLUMNS if c in work.columns]
    work = stamp_flow(
        work[keep].reset_index(drop=True),
        source,
        unit="万元",
        flow_type="cross_border",
        direction=direction,
    )
    if swapped:
        work.attrs["date_range_swapped"] = True
    out = _finalize_flow(
        work,
        source,
        lambda src, error=None, issues=None: empty_cross_border(
            src, error=error, issues=issues, direction=direction
        ),
        validate_cross_border,
        error=error,
    )
    if dropped_south:
        issues = list(out.attrs.get("issues") or [])
        if "southbound matched northbound; dropped duplicate leg" not in issues:
            issues.append("southbound matched northbound; dropped duplicate leg")
        out.attrs["issues"] = issues
        out.attrs["southbound_dropped"] = True
    if swapped:
        issues = list(out.attrs.get("issues") or [])
        if "start/end dates swapped" not in issues:
            issues.append("start/end dates swapped")
        out.attrs["issues"] = issues
        out.attrs["date_range_swapped"] = True
    return out


def prepare_market_flow(
    df,
    source=None,
    amount_unit="yuan",
    start=None,
    end=None,
    error=None,
):
    """市场主力资金时间序列 → 标准列，金额为万元。"""
    if df is None or (isinstance(df, pd.DataFrame) and df.empty):
        return empty_market_flow(source, error=error, issues=["empty frame"])
    if not isinstance(df, pd.DataFrame):
        return empty_market_flow(source, error=error, issues=["empty frame"])

    work = df.copy()
    if work.index.name in ("date", "日期", "trade_date") or isinstance(work.index, pd.DatetimeIndex):
        work = work.reset_index()
    work = canonicalize_flow_columns(work)
    work = rename_columns(work)
    work = apply_explicit_column_map(work)
    work = derive_bucket_nets(work)
    if "date" not in work.columns:
        return empty_market_flow(source, error=error, issues=["missing date column"])
    work["date"] = parse_dates(work["date"])
    work = coerce_numerics(work)
    work = _fill_flow_aliases(work)
    if "main_net_inflow" not in work.columns and "net_inflow" in work.columns:
        work["main_net_inflow"] = work["net_inflow"]

    money_cols = [c for c in FLOW_MONEY_COLUMNS if c in work.columns]
    unit = _resolve_amount_unit(work, amount_unit, "market", money_cols)
    work = scale_to_wan(work, money_cols, unit)
    if source:
        work["source"] = source

    work = work.dropna(subset=["date"])
    work = work.sort_values("date").drop_duplicates(subset=["date"], keep="last")
    work = filter_date_range(work, start, end)
    swapped = bool(work.attrs.get("date_range_swapped"))
    keep = [c for c in MARKET_FLOW_COLUMNS if c in work.columns]
    work = stamp_flow(work[keep].reset_index(drop=True), source, unit="万元", flow_type="market")
    if swapped:
        work.attrs["date_range_swapped"] = True
    out = _finalize_flow(work, source, empty_market_flow, validate_market_flow, error=error)
    if swapped:
        issues = list(out.attrs.get("issues") or [])
        if "start/end dates swapped" not in issues:
            issues.append("start/end dates swapped")
        out.attrs["issues"] = issues
        out.attrs["date_range_swapped"] = True
    return out
