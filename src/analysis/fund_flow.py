"""
资金流向分析：排名、主力/散户、趋势、北向状态、量价背离。

输入是 quality.prepare_* 之后的标准表（金额单位：万元）。
页面只做展示，计算放在这里。
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


def format_wan(value, na="-"):
    """万元 → 可读字符串：1.23亿 / 4500.00万。"""
    if value is None or (isinstance(value, float) and (math.isnan(value) or math.isinf(value))):
        return na
    try:
        if pd.isna(value):
            return na
    except (TypeError, ValueError):
        return na
    number = float(value)
    sign = "-" if number < 0 else ""
    abs_value = abs(number)
    if abs_value >= 10000:
        return f"{sign}{abs_value / 10000:.2f}亿"
    return f"{sign}{abs_value:.2f}万"


def unit_caption(df, fallback_source=""):
    if df is None:
        return "无数据"
    source = df.attrs.get("source") or fallback_source or ""
    unit = df.attrs.get("unit") or "万元"
    period = df.attrs.get("period")
    parts = []
    if source:
        parts.append(f"数据来源: {source}")
    parts.append(f"金额单位: {unit}")
    if period:
        parts.append(f"周期: {period}")
    return " | ".join(parts)


def _ready(df, columns=None):
    if df is None or df.empty:
        return False
    if columns:
        return all(col in df.columns for col in columns)
    return True


def rank_inflow(df, n=20, column="net_inflow"):
    """净流入从大到小。"""
    if not _ready(df, [column]):
        return df if df is not None else pd.DataFrame()
    work = df.dropna(subset=[column]).sort_values(column, ascending=False)
    return work.head(int(n)).reset_index(drop=True)


def rank_outflow(df, n=20, column="net_inflow"):
    """净流出（最负）排前。"""
    if not _ready(df, [column]):
        return df if df is not None else pd.DataFrame()
    work = df.dropna(subset=[column]).sort_values(column, ascending=True)
    return work.head(int(n)).reset_index(drop=True)


def extreme_rows(df, n=15, column="net_inflow"):
    """流入榜 + 流出榜，供对称柱状图。"""
    if not _ready(df, [column]):
        return df if df is not None else pd.DataFrame()
    top = rank_inflow(df, n=n, column=column)
    bottom = rank_outflow(df, n=n, column=column)
    if top is None or top.empty:
        return bottom
    if bottom is None or bottom.empty:
        return top
    keys = [c for c in ("code", "name") if c in df.columns]
    combined = pd.concat([bottom, top], ignore_index=True)
    if keys:
        combined = combined.drop_duplicates(subset=keys, keep="first")
    else:
        combined = combined.drop_duplicates()
    return combined.sort_values(column, ascending=True).reset_index(drop=True)


def summarize_rank(df, n=8, column="net_inflow"):
    """排名表一句话摘要：合计、家数、最强/最弱名称。"""
    empty = {
        "total_net_inflow": 0.0,
        "inflow_count": 0,
        "outflow_count": 0,
        "top_inflow": [],
        "top_outflow": [],
        "source": None,
        "unit": "万元",
        "period": None,
    }
    if not _ready(df, [column]):
        return empty
    values = pd.to_numeric(df[column], errors="coerce")
    names = df["name"] if "name" in df.columns else df.get("code", pd.Series([""] * len(df)))
    ranked = df.assign(_flow=values, _label=names.astype(str))
    ranked = ranked.dropna(subset=["_flow"])
    top = ranked.nlargest(int(n), "_flow")
    bottom = ranked.nsmallest(int(n), "_flow")
    return {
        "total_net_inflow": float(values.fillna(0).sum()),
        "inflow_count": int((values > 0).sum()),
        "outflow_count": int((values < 0).sum()),
        "top_inflow": [
            {"name": row["_label"], "net_inflow": float(row["_flow"])}
            for _, row in top.iterrows()
        ],
        "top_outflow": [
            {"name": row["_label"], "net_inflow": float(row["_flow"])}
            for _, row in bottom.iterrows()
        ],
        "source": df.attrs.get("source"),
        "unit": df.attrs.get("unit") or "万元",
        "period": df.attrs.get("period"),
    }


def main_vs_retail(df, main_col="main_net_inflow", retail_col="small_net"):
    """
    主力 vs 小单（散户近似）。
    对排名表按列求和；对时间序列取最近一行，并带 5 日合计。
    """
    result = {
        "main_net_inflow": None,
        "retail_net_inflow": None,
        "main_dominates": None,
        "note": "缺少主力或小单字段",
    }
    if df is None or df.empty:
        return result
    has_main = main_col in df.columns
    has_retail = retail_col in df.columns
    if not has_main and not has_retail:
        return result

    if "date" in df.columns and len(df) >= 1:
        last = df.iloc[-1]
        main = float(last[main_col]) if has_main and pd.notna(last.get(main_col)) else None
        retail = float(last[retail_col]) if has_retail and pd.notna(last.get(retail_col)) else None
        window = df.tail(5)
        main_5 = (
            float(pd.to_numeric(window[main_col], errors="coerce").sum()) if has_main else None
        )
        retail_5 = (
            float(pd.to_numeric(window[retail_col], errors="coerce").sum()) if has_retail else None
        )
    else:
        main = float(pd.to_numeric(df[main_col], errors="coerce").sum()) if has_main else None
        retail = float(pd.to_numeric(df[retail_col], errors="coerce").sum()) if has_retail else None
        main_5 = main
        retail_5 = retail

    dominates = None
    if main is not None and retail is not None:
        dominates = abs(main) >= abs(retail)
    note = _main_retail_note(main, retail)
    result.update(
        {
            "main_net_inflow": main,
            "retail_net_inflow": retail,
            "main_5d": main_5,
            "retail_5d": retail_5,
            "main_dominates": dominates,
            "note": note,
        }
    )
    return result


def _main_retail_note(main, retail):
    if main is None and retail is None:
        return "缺少主力或小单字段"
    if main is None:
        return f"散户(小单)净流入 {format_wan(retail)}"
    if retail is None:
        return f"主力净流入 {format_wan(main)}"
    if main > 0 and retail < 0:
        return "主力净流入、散户净流出（资金向主力集中）"
    if main < 0 and retail > 0:
        return "主力净流出、散户净流入（散户接盘）"
    if main > 0 and retail > 0:
        return "主力与散户同时净流入"
    if main < 0 and retail < 0:
        return "主力与散户同时净流出"
    return "主力与散户方向接近中性"


def flow_trend_stats(df, value_col="main_net_inflow", windows=(1, 5, 10, 20)):
    """时间序列窗口合计与连续同向天数。"""
    stats = {
        "latest": None,
        "streak": 0,
        "windows": {},
        "value_col": value_col,
    }
    if not _ready(df, [value_col]):
        return stats
    series = pd.to_numeric(df[value_col], errors="coerce")
    if "date" in df.columns:
        order = df.sort_values("date")
        series = pd.to_numeric(order[value_col], errors="coerce")
    latest = series.iloc[-1] if len(series) else np.nan
    stats["latest"] = float(latest) if pd.notna(latest) else None
    for window in windows:
        chunk = series.tail(int(window))
        stats["windows"][int(window)] = float(chunk.sum()) if chunk.notna().any() else None

    streak = 0
    if pd.notna(latest) and latest != 0:
        sign = 1 if latest > 0 else -1
        for value in reversed(series.tolist()):
            if pd.isna(value) or value == 0 or (1 if value > 0 else -1) != sign:
                break
            streak += 1
        stats["streak"] = streak * sign
    return stats


def northbound_regime(df, window=5, value_col="net_inflow"):
    """北向近 N 日合计：inflow / outflow / mixed。"""
    result = {
        "latest": None,
        "window_sum": None,
        "window": int(window),
        "regime": "unknown",
        "note": "北向数据不可用",
    }
    if not _ready(df, [value_col]):
        return result
    work = df
    if "date" in df.columns:
        work = df.sort_values("date")
    series = pd.to_numeric(work[value_col], errors="coerce")
    latest = series.iloc[-1] if len(series) else np.nan
    window_sum = series.tail(int(window)).sum()
    result["latest"] = float(latest) if pd.notna(latest) else None
    result["window_sum"] = float(window_sum) if pd.notna(window_sum) else None
    if result["window_sum"] is None:
        return result
    if result["window_sum"] > 0 and (result["latest"] or 0) >= 0:
        result["regime"] = "inflow"
        result["note"] = f"近{window}日北向净流入 {format_wan(result['window_sum'])}"
    elif result["window_sum"] < 0 and (result["latest"] or 0) <= 0:
        result["regime"] = "outflow"
        result["note"] = f"近{window}日北向净流出 {format_wan(result['window_sum'])}"
    else:
        result["regime"] = "mixed"
        result["note"] = f"近{window}日北向净额 {format_wan(result['window_sum'])}，方向不一致"
    return result


def price_flow_divergence(price_df, flow_df, window=5, flow_col="main_net_inflow"):
    """
    价涨资金出 / 价跌资金进。返回对齐后的明细表（只保留有信号的日期也可由页面再筛）。
    """
    columns = [
        "date",
        "close",
        "price_chg",
        "flow_sum",
        "divergence",
        "note",
    ]
    if price_df is None or price_df.empty or flow_df is None or flow_df.empty:
        return pd.DataFrame(columns=columns)
    if "date" not in price_df.columns or "close" not in price_df.columns:
        return pd.DataFrame(columns=columns)
    if "date" not in flow_df.columns or flow_col not in flow_df.columns:
        alt = "net_inflow" if "net_inflow" in flow_df.columns else None
        if alt is None:
            return pd.DataFrame(columns=columns)
        flow_col = alt

    price = price_df[["date", "close"]].copy()
    price["date"] = pd.to_datetime(price["date"], errors="coerce").dt.normalize()
    flow = flow_df[["date", flow_col]].copy()
    flow["date"] = pd.to_datetime(flow["date"], errors="coerce").dt.normalize()
    merged = pd.merge(price, flow, on="date", how="inner").dropna(subset=["date"])
    if merged.empty:
        return pd.DataFrame(columns=columns)
    merged = merged.sort_values("date").drop_duplicates("date", keep="last")
    merged["price_chg"] = merged["close"].pct_change(int(window))
    merged["flow_sum"] = pd.to_numeric(merged[flow_col], errors="coerce").rolling(int(window)).sum()

    def _note(row):
        price_chg, flow_sum = row["price_chg"], row["flow_sum"]
        if pd.isna(price_chg) or pd.isna(flow_sum):
            return ""
        if price_chg > 0 and flow_sum < 0:
            return "价涨资金出（可能派发）"
        if price_chg < 0 and flow_sum > 0:
            return "价跌资金进（可能吸筹）"
        if price_chg > 0 and flow_sum > 0:
            return "价量齐升"
        if price_chg < 0 and flow_sum < 0:
            return "价量齐跌"
        return ""

    merged["note"] = merged.apply(_note, axis=1)
    merged["divergence"] = merged["note"].isin(["价涨资金出（可能派发）", "价跌资金进（可能吸筹）"])
    out = merged[["date", "close", "price_chg", "flow_sum", "divergence", "note"]].reset_index(drop=True)
    return out


def latest_stock_snapshot(df):
    """个股资金流最近一行 + 趋势，给股票分析 / 交易决策用。"""
    value_col = "net_inflow"
    if df is not None and "main_net_inflow" in getattr(df, "columns", []):
        value_col = "main_net_inflow"
    stats = flow_trend_stats(df, value_col=value_col)
    vs = main_vs_retail(df)
    last_date = None
    if df is not None and not df.empty and "date" in df.columns:
        last_date = df.iloc[-1]["date"]
    return {
        "date": last_date,
        "latest_main": stats.get("latest"),
        "sum_5d": (stats.get("windows") or {}).get(5),
        "sum_10d": (stats.get("windows") or {}).get(10),
        "streak": stats.get("streak") or 0,
        "main_vs_retail": vs,
        "note": vs.get("note") or "",
    }


def stock_flow_notes(df, north_df=None):
    """给交易页的短备注，不改评分模型。"""
    notes = []
    if df is not None and not df.empty:
        snap = latest_stock_snapshot(df)
        if snap["latest_main"] is not None:
            notes.append(f"最新主力净流入 {format_wan(snap['latest_main'])}")
        if snap["sum_5d"] is not None:
            notes.append(f"近5日主力合计 {format_wan(snap['sum_5d'])}")
        streak = snap["streak"]
        if streak:
            direction = "流入" if streak > 0 else "流出"
            notes.append(f"主力连续{abs(int(streak))}日净{direction}")
        if snap["note"]:
            notes.append(snap["note"])
    if north_df is not None and not north_df.empty:
        regime = northbound_regime(north_df)
        if regime.get("note") and regime.get("regime") != "unknown":
            notes.append(regime["note"])
    return notes


def enrich_sector_flow(flow, boards):
    """板块行情缺涨跌幅时，用行业表按名称补一列。"""
    if flow is None or flow.empty:
        return flow
    if "change_pct" in flow.columns and flow["change_pct"].notna().any():
        return flow
    if boards is None or boards.empty or "name" not in boards.columns:
        return flow
    if "name" not in flow.columns:
        return flow
    chg_col = "change_pct" if "change_pct" in boards.columns else None
    if chg_col is None:
        return flow
    lookup = boards.dropna(subset=["name"]).drop_duplicates("name")[["name", chg_col]]
    merged = flow.merge(lookup, on="name", how="left", suffixes=("", "_board"))
    if "change_pct_board" in merged.columns:
        if "change_pct" not in merged.columns:
            merged["change_pct"] = merged["change_pct_board"]
        else:
            merged["change_pct"] = merged["change_pct"].fillna(merged["change_pct_board"])
        merged = merged.drop(columns=["change_pct_board"])
    merged.attrs.update(flow.attrs)
    return merged


class FundFlowAnalyzer:
    """可选的薄封装，方便页面一次传入多张表。"""

    def __init__(self, rank_df=None, stock_df=None, north_df=None, market_df=None):
        self.rank_df = rank_df
        self.stock_df = stock_df
        self.north_df = north_df
        self.market_df = market_df

    def rank_summary(self, n=8):
        return summarize_rank(self.rank_df, n=n)

    def stock_snapshot(self):
        return latest_stock_snapshot(self.stock_df)

    def north_regime(self, window=5):
        return northbound_regime(self.north_df, window=window)

    def notes(self):
        return stock_flow_notes(self.stock_df, self.north_df)
