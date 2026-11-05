"""
资金流向分析：排名、主力/散户、趋势、北向状态、价资背离、短周期倾向。

输入是 quality.prepare_* 之后的标准表（金额单位：万元）。
页面只做展示，计算放在这里。
资金面倾向是 1–5 日方向，不是涨跌预测。
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from src.data.quality import sector_type_short


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


def actual_period_label(df, requested=None):
    if df is not None:
        actual = df.attrs.get("actual_period") or df.attrs.get("period")
        if actual:
            return actual
    return requested or ""


def actual_sector_label(df, requested=None):
    raw = None
    if df is not None:
        raw = df.attrs.get("actual_sector") or df.attrs.get("requested_sector")
    raw = raw or requested or ""
    return sector_type_short(raw) if raw else ""


def scope_fallback_note(df, requested_period=None, requested_sector=None):
    """请求与实际不一致时的短提示。"""
    if df is None:
        return ""
    actual_p = actual_period_label(df, requested_period)
    requested_p = df.attrs.get("requested_period") or requested_period
    actual_s = actual_sector_label(df, requested_sector)
    requested_s = None
    if df.attrs.get("requested_sector"):
        requested_s = sector_type_short(df.attrs.get("requested_sector"))
    elif requested_sector:
        requested_s = sector_type_short(requested_sector)
    parts = []
    if requested_p and actual_p and requested_p != actual_p:
        parts.append(f"周期已回退 {requested_p}→{actual_p}")
    if requested_s and actual_s and requested_s != actual_s:
        parts.append(f"板块已回退 {requested_s}→{actual_s}")
    return "；".join(parts)


def unit_caption(df, fallback_source="", requested_period=None, requested_sector=None):
    if df is None:
        return "无数据"
    source = df.attrs.get("source") or fallback_source or ""
    unit = df.attrs.get("unit") or "万元"
    period = actual_period_label(df, requested_period)
    sector = actual_sector_label(df, requested_sector)
    parts = []
    if source:
        parts.append(f"数据来源: {source}")
    parts.append(f"金额单位: {unit}")
    if period:
        parts.append(f"周期: {period}")
        requested_p = df.attrs.get("requested_period") or requested_period
        if requested_p and requested_p != period:
            parts.append(f"请求周期: {requested_p}")
    if sector:
        parts.append(f"板块: {sector}")
    return " | ".join(parts)


def _is_overlapping_rank(df):
    if df is None:
        return False
    sector = df.attrs.get("actual_sector") or df.attrs.get("requested_sector")
    if not sector:
        return False
    return sector_type_short(sector) in ("概念", "地域")


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
        "total_net_inflow": None,
        "overlapping": False,
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
    overlapping = _is_overlapping_rank(df)
    total = None if overlapping else float(values.fillna(0).sum())
    return {
        "total_net_inflow": total,
        "overlapping": overlapping,
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
    overlapping = "date" not in getattr(df, "columns", []) and _is_overlapping_rank(df)
    if overlapping:
        note = (note + "；" if note else "") + "概念/地域互相重叠，合计不能当作全市场"
    result.update(
        {
            "main_net_inflow": main,
            "retail_net_inflow": retail,
            "main_5d": main_5,
            "retail_5d": retail_5,
            "main_dominates": dominates,
            "overlapping": overlapping,
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


def price_flow_divergence(
    price_df,
    flow_df,
    window=5,
    flow_col="main_net_inflow",
    min_abs_pct=0.02,
    min_abs_flow=100.0,
):
    """
    价资背离：价涨资出 / 价跌资进。只描述方向，不下派发/吸筹结论。
    min_abs_pct / min_abs_flow 过滤过小波动。
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
        if abs(float(price_chg)) < float(min_abs_pct):
            return ""
        if abs(float(flow_sum)) < float(min_abs_flow or 0):
            return ""
        if price_chg > 0 and flow_sum < 0:
            return "价涨资出"
        if price_chg < 0 and flow_sum > 0:
            return "价跌资进"
        if price_chg > 0 and flow_sum > 0:
            return "价资同向（上涨）"
        if price_chg < 0 and flow_sum < 0:
            return "价资同向（下跌）"
        return ""

    merged["note"] = merged.apply(_note, axis=1)
    merged["divergence"] = merged["note"].isin(["价涨资出", "价跌资进"])
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
    """给交易页的短备注。评分改动走 fund_flow_bias.score_delta，不在这里改。"""
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


_SERIOUS_QUALITY_MARKERS = (
    "empty frame",
    "all-zero amounts",
    "all null",
    "missing column",
    "missing inflow",
    "unavailable",
)

BIAS_BULL = "偏多"
BIAS_BEAR = "偏空"
BIAS_NEUTRAL = "中性"
BIAS_SPLIT = "分化"
BIAS_HORIZON = "1-5日"
_LEG_CN = {
    "market": "市场主力",
    "north": "北向",
    "sector": "板块",
    "stock": "个股",
}


def _numeric_sign(value, eps=0.0):
    if value is None:
        return 0
    try:
        if pd.isna(value):
            return 0
    except (TypeError, ValueError):
        return 0
    number = float(value)
    if math.isnan(number) or math.isinf(number) or abs(number) <= float(eps):
        return 0
    return 1 if number > 0 else -1


def _flow_value_col(df, preferred=("main_net_inflow", "net_inflow")):
    if df is None:
        return None
    for col in preferred:
        if col in df.columns:
            return col
    return None


def _frame_has_rows(df):
    return df is not None and not getattr(df, "empty", True)


def _frame_quality_ok(df):
    """缺数据不算质量差；attrs.ok=False 或严重 issues 才判不合格。"""
    if not _frame_has_rows(df):
        return True
    if df.attrs.get("ok") is False:
        return False
    for item in df.attrs.get("issues") or []:
        text = str(item)
        if any(marker in text for marker in _SERIOUS_QUALITY_MARKERS):
            return False
    return True


def empty_fund_bias(reason="资金数据不足，不下倾向"):
    return {
        "bias": BIAS_NEUTRAL,
        "horizon": BIAS_HORIZON,
        "confidence": 0.0,
        "confidence_label": "低",
        "evidence": [reason] if reason else [],
        "score_delta": 0.0,
        "components": {},
        "quality_ok": True,
        "dropped_legs": [],
        "label": "资金面倾向（1–5日）",
        "disclaimer": "资金面倾向，不是涨跌预测",
    }


def flow_acceleration(df, col=None, window=5):
    """Δ(近 window 日合计 − 前 window 日合计)。序列不够长则不下结论。"""
    result = {
        "delta": None,
        "recent": None,
        "previous": None,
        "label": "",
        "sign": 0,
        "window": int(window),
    }
    col = col or _flow_value_col(df)
    need = int(window) * 2
    if not col or not _ready(df, [col]) or len(df) < need:
        return result
    work = df.sort_values("date") if "date" in df.columns else df
    series = pd.to_numeric(work[col], errors="coerce")
    recent = series.tail(int(window))
    previous = series.iloc[-need : -int(window)]
    if not recent.notna().any() or not previous.notna().any():
        return result
    recent_sum = float(recent.sum())
    previous_sum = float(previous.sum())
    delta = recent_sum - previous_sum
    result["recent"] = recent_sum
    result["previous"] = previous_sum
    result["delta"] = delta
    if abs(delta) < 1.0:
        result["label"] = "近段流速变化很小"
        return result
    prev_sign = _numeric_sign(previous_sum)
    rec_sign = _numeric_sign(recent_sum)
    if rec_sign > 0 and delta > 0:
        result["label"] = "加速流入"
        result["sign"] = 1
    elif rec_sign > 0 and delta < 0:
        result["label"] = "流入减速"
        result["sign"] = 0
    elif rec_sign < 0 and delta < 0:
        result["label"] = "加速流出"
        result["sign"] = -1
    elif rec_sign < 0 and delta > 0:
        result["label"] = "流出放缓"
        result["sign"] = 0
    elif prev_sign < 0 and rec_sign > 0:
        result["label"] = "由出转进"
        result["sign"] = 1
    elif prev_sign > 0 and rec_sign < 0:
        result["label"] = "由进转出"
        result["sign"] = -1
    else:
        result["label"] = "流速变化中性"
    return result


def divergence_reading(note, streak=None):
    """价资背离的短读法：只描述短周期含义，不下派发/吸筹结论。"""
    if not note:
        return ""
    extra = ""
    if streak:
        direction = "流入" if streak > 0 else "流出"
        extra = f"（主力连续{abs(int(streak))}日净{direction}）"
    mapping = {
        "价涨资出": f"价涨资出{extra}：短周期追高风险，价格上涨但资金未同步",
        "价跌资进": f"价跌资进{extra}：关注反弹条件，资金先行、价格尚未确认",
        "价资同向（上涨）": f"价资同向（上涨）{extra}：短周期资金与价格同向",
        "价资同向（下跌）": f"价资同向（下跌）{extra}：短周期资金与价格同向走弱",
    }
    return mapping.get(str(note), str(note))


def latest_divergence_note(price_df, flow_df):
    table = price_flow_divergence(price_df, flow_df)
    if table is None or table.empty or "note" not in table.columns:
        return ""
    notes = table["note"].astype(str)
    nonempty = notes[notes.str.len() > 0]
    if nonempty.empty:
        return ""
    return str(nonempty.iloc[-1])


def sector_rotation_stats(rank_df, column="net_inflow", top_n=5):
    """
    行业榜的广度 / 头部集中度，供轮动观察。
    概念/地域重叠时 usable_for_rotation=False，合计不当作全市场。
    """
    overlapping = _is_overlapping_rank(rank_df)
    empty = {
        "overlapping": overlapping,
        "usable_for_rotation": False,
        "inflow_count": 0,
        "outflow_count": 0,
        "breadth": None,
        "top_concentration": None,
        "top_names": [],
        "total_net_inflow": None,
        "sign": 0,
        "note": "板块排名不可用",
    }
    if not _ready(rank_df, [column]):
        return empty
    values = pd.to_numeric(rank_df[column], errors="coerce")
    inflow_count = int((values > 0).sum())
    outflow_count = int((values < 0).sum())
    counted = inflow_count + outflow_count
    breadth = (inflow_count / counted) if counted else None
    names = rank_df["name"] if "name" in rank_df.columns else rank_df.get("code", pd.Series([""] * len(rank_df)))
    ranked = rank_df.assign(_flow=values, _label=names.astype(str)).dropna(subset=["_flow"])
    top = ranked.nlargest(int(top_n), "_flow")
    positive = values[values > 0]
    top_concentration = None
    if not positive.empty and float(positive.sum()) != 0:
        top_sum = float(pd.to_numeric(top["_flow"], errors="coerce").clip(lower=0).sum())
        top_concentration = top_sum / float(positive.sum())
    total = None if overlapping else float(values.fillna(0).sum())
    if overlapping:
        note = "概念/地域互相重叠，仅行业榜可用于轮动合计；此处只作榜内广度"
        sign = 0
        usable = False
    else:
        usable = True
        if inflow_count > outflow_count or (total is not None and total > 0):
            sign = 1
        elif outflow_count > inflow_count or (total is not None and total < 0):
            sign = -1
        else:
            sign = 0
        note = f"行业流入{inflow_count} / 流出{outflow_count}，可用于轮动观察"
        if top_concentration is not None:
            note += f"；前{int(top_n)}占流入约{top_concentration:.0%}"
    return {
        "overlapping": overlapping,
        "usable_for_rotation": usable,
        "inflow_count": inflow_count,
        "outflow_count": outflow_count,
        "breadth": breadth,
        "top_concentration": top_concentration,
        "top_names": [str(row["_label"]) for _, row in top.iterrows()],
        "total_net_inflow": total,
        "sign": sign,
        "note": note,
    }


def _divergence_implied_sign(note):
    """价涨资出≈资金流出(-1)，价跌资进≈资金流入(+1)。同向已有明确票，不走这里。"""
    if note == "价涨资出":
        return -1
    if note == "价跌资进":
        return 1
    return 0


def _divergence_conflicts(note, stock_sign=0, vote_signs=None):
    """背离含义与个股腿或其他资金票冲突时为 True。"""
    implied = _divergence_implied_sign(note)
    if not implied:
        return False
    if stock_sign and int(stock_sign) != implied:
        return True
    others = [int(sign) for sign in (vote_signs or []) if sign]
    return bool(others) and any(sign != implied for sign in others)


def _confidence_label(value):
    if value >= 0.67:
        return "高"
    if value >= 0.34:
        return "中"
    return "低"


def _leg_component(sign=0, available=False, quality_ok=True, **extra):
    payload = {
        "sign": int(sign),
        "available": bool(available),
        "quality_ok": bool(quality_ok),
    }
    payload.update(extra)
    return payload


def fund_flow_bias(
    market_df=None,
    north_df=None,
    sector_rank=None,
    stock_flow=None,
    price_df=None,
):
    """
    合成短周期资金面倾向。返回偏多/偏空/中性/分化，不是涨跌预测。
    质量不合格的腿只剔除该腿；score_delta=0 仅当没有可用投票腿，或倾向为中性/分化，或信心过低。
    """
    result = empty_fund_bias()
    evidence = []
    votes = []
    components = {}
    dropped_legs = []
    caution = False

    def _take(name, df):
        if not _frame_has_rows(df):
            components[name] = _leg_component(available=False)
            return False
        if not _frame_quality_ok(df):
            dropped_legs.append(name)
            components[name] = _leg_component(available=True, quality_ok=False)
            evidence.append(f"{_LEG_CN.get(name, name)}数据质量不足，该腿不计入")
            return False
        return True

    if _take("market", market_df):
        col = _flow_value_col(market_df)
        stats = flow_trend_stats(market_df, value_col=col or "main_net_inflow")
        accel = flow_acceleration(market_df, col=col)
        window5 = (stats.get("windows") or {}).get(5)
        sign = _numeric_sign(window5 if window5 is not None else stats.get("latest"))
        streak = int(stats.get("streak") or 0)
        if stats.get("latest") is not None:
            evidence.append(
                f"市场主力最新 {format_wan(stats['latest'])}，近5日 {format_wan(window5)}"
            )
        if streak:
            evidence.append(f"市场主力连续{abs(streak)}日净{'流入' if streak > 0 else '流出'}")
        if accel.get("label"):
            evidence.append(f"市场{accel['label']}")
            if accel.get("sign") and sign == 0:
                sign = int(accel["sign"])
        components["market"] = _leg_component(
            sign=sign, available=True, streak=streak, accel=accel.get("label") or ""
        )
        if sign:
            votes.append(("market", sign, 1.5))

    if _take("north", north_df):
        regime = northbound_regime(north_df)
        sign = {"inflow": 1, "outflow": -1}.get(regime.get("regime"), 0)
        if regime.get("note") and regime.get("regime") != "unknown":
            evidence.append(regime["note"])
        components["north"] = _leg_component(
            sign=sign, available=True, regime=regime.get("regime")
        )
        if sign:
            votes.append(("north", sign, 1.0))

    if _take("sector", sector_rank):
        rot = sector_rotation_stats(sector_rank)
        if rot.get("overlapping"):
            evidence.append(rot.get("note") or "概念/地域重叠，合计不能当作全市场")
            evidence.append(
                f"榜内流入{rot.get('inflow_count', 0)} / 流出{rot.get('outflow_count', 0)}（不计入市场合计）"
            )
            components["sector"] = _leg_component(
                sign=0,
                available=True,
                overlapping=True,
                usable_for_rotation=False,
                inflow_count=rot.get("inflow_count"),
                outflow_count=rot.get("outflow_count"),
            )
        else:
            sign = int(rot.get("sign") or 0)
            if rot.get("note"):
                evidence.append(rot["note"])
            components["sector"] = _leg_component(
                sign=sign,
                available=True,
                overlapping=False,
                usable_for_rotation=True,
                inflow_count=rot.get("inflow_count"),
                outflow_count=rot.get("outflow_count"),
                top_concentration=rot.get("top_concentration"),
            )
            if sign:
                votes.append(("sector", sign, 1.0))

    stock_streak = 0
    if _take("stock", stock_flow):
        snap = latest_stock_snapshot(stock_flow)
        col = _flow_value_col(stock_flow)
        accel = flow_acceleration(stock_flow, col=col)
        sign = _numeric_sign(snap.get("sum_5d") if snap.get("sum_5d") is not None else snap.get("latest_main"))
        stock_streak = int(snap.get("streak") or 0)
        if snap.get("latest_main") is not None:
            evidence.append(f"个股主力最新 {format_wan(snap['latest_main'])}，近5日 {format_wan(snap.get('sum_5d'))}")
        if stock_streak:
            evidence.append(
                f"个股主力连续{abs(stock_streak)}日净{'流入' if stock_streak > 0 else '流出'}"
            )
        if snap.get("note"):
            evidence.append(snap["note"])
        if accel.get("label"):
            evidence.append(f"个股{accel['label']}")
            if accel.get("sign") and sign == 0:
                sign = int(accel["sign"])
        components["stock"] = _leg_component(
            sign=sign, available=True, streak=stock_streak, accel=accel.get("label") or ""
        )
        if sign:
            votes.append(("stock", sign, 1.2))

    div_note = latest_divergence_note(price_df, stock_flow) if price_df is not None else ""
    reading = divergence_reading(div_note, streak=stock_streak or None)
    div_sign = 0
    div_implied = _divergence_implied_sign(div_note)
    if div_note == "价资同向（上涨）":
        div_sign = 1
    elif div_note == "价资同向（下跌）":
        div_sign = -1
    elif div_implied:
        caution = True
    if reading:
        evidence.append(reading)
    if price_df is not None or div_note:
        components["divergence"] = _leg_component(
            sign=div_sign or div_implied,
            available=bool(div_note),
            note=div_note,
            reading=reading,
        )
        if div_sign:
            votes.append(("divergence", div_sign, 0.8))

    if not evidence:
        return result

    stock_sign = int((components.get("stock") or {}).get("sign") or 0)
    vote_signs = [sign for _, sign, _ in votes if sign]
    div_conflict = _divergence_conflicts(div_note, stock_sign, vote_signs)
    if div_conflict and div_implied:
        votes.append(("divergence", div_implied, 0.8))
        components["divergence"]["sign"] = int(div_implied)
        evidence.append("价资背离与资金方向冲突，倾向记为分化")

    bull = sum(1 for _, sign, _ in votes if sign > 0)
    bear = sum(1 for _, sign, _ in votes if sign < 0)
    n_avail = sum(1 for item in components.values() if item.get("available") and item.get("quality_ok"))
    usable_votes = bull + bear
    weighted = sum(sign * weight for _, sign, weight in votes)
    # 有可用投票腿则整体仍可用于软评分；缺腿或坏腿不算全场不合格。
    quality_ok = usable_votes > 0 or not dropped_legs

    if bull and bear:
        bias = BIAS_SPLIT
        if not any("分化" in line for line in evidence):
            evidence.append("资金腿方向冲突，倾向记为分化")
        confidence = min(0.45, 0.18 + 0.06 * n_avail)
    elif bull and not bear:
        bias = BIAS_BULL
        confidence = 0.35 + 0.15 * bull + 0.05 * n_avail
    elif bear and not bull:
        bias = BIAS_BEAR
        confidence = 0.35 + 0.15 * bear + 0.05 * n_avail
    else:
        bias = BIAS_NEUTRAL
        confidence = 0.2 if n_avail else 0.0

    if caution and not div_conflict:
        confidence *= 0.85
    confidence = max(0.0, min(1.0, float(confidence)))

    if usable_votes == 0 or bias in (BIAS_NEUTRAL, BIAS_SPLIT) or confidence < 0.25:
        score_delta = 0.0
    else:
        magnitude = 2.0 if confidence >= 0.6 else 1.0
        score_delta = magnitude if bias == BIAS_BULL else -magnitude

    result.update(
        {
            "bias": bias,
            "horizon": BIAS_HORIZON,
            "confidence": round(confidence, 3),
            "confidence_label": _confidence_label(confidence),
            "evidence": evidence,
            "score_delta": float(score_delta),
            "components": components,
            "quality_ok": quality_ok,
            "dropped_legs": list(dropped_legs),
            "net_vote": float(weighted),
        }
    )
    return result


def bias_display(bias):
    """页面卡片用的展示字段。"""
    payload = bias or empty_fund_bias()
    conf = float(payload.get("confidence") or 0)
    return {
        "title": payload.get("label") or "资金面倾向（1–5日）",
        "disclaimer": payload.get("disclaimer") or "资金面倾向，不是涨跌预测",
        "bias": payload.get("bias") or BIAS_NEUTRAL,
        "confidence_label": payload.get("confidence_label") or "低",
        "confidence_pct": f"{conf:.0%}",
        "score_delta": f"{float(payload.get('score_delta') or 0):+.1f}",
        "score_delta_label": "评分贡献",
        "evidence": list(payload.get("evidence") or []),
        "reading": ((payload.get("components") or {}).get("divergence") or {}).get("reading") or "",
        "horizon": payload.get("horizon") or BIAS_HORIZON,
    }


def _action_from_score(score, strong_buy, buy, hold_floor, sell_floor):
    if score >= strong_buy:
        return "强烈买入", "BUY", "高"
    if score >= buy:
        return "买入", "BUY", "中等"
    if score >= hold_floor:
        return "持有", "HOLD", "中等"
    if score >= sell_floor:
        return "减仓", "SELL", "中等"
    return "卖出", "SELL", "高"


def apply_fund_flow_bias(recommendation, bias=None, strong_buy=10, buy=5, hold_floor=0, sell_floor=-5):
    """
    把资金面 score_delta 软加到交易评分。信任 bias.score_delta（坏腿已在合成时剔除）。
    保留技术信心 tech_confidence，不按总分阈值覆盖引擎原信心。
    不改止损；若评分跨过阈值则同步更新 action。
    """
    rec = dict(recommendation or {})
    payload = bias or empty_fund_bias()
    raw = float(rec.get("score") or 0)
    delta = float(payload.get("score_delta") or 0)
    rec["score_raw"] = raw
    rec["tech_score"] = raw
    rec["tech_confidence"] = rec.get("confidence")
    rec["fund_score_delta"] = delta
    rec["fund_flow_bias"] = payload
    rec["score"] = raw + delta
    notes = list(rec.get("analysis_notes") or [])
    notes.append(
        f"资金面倾向（{payload.get('horizon') or BIAS_HORIZON}）："
        f"{payload.get('bias') or BIAS_NEUTRAL}，"
        f"资金信心{payload.get('confidence_label') or '低'}，"
        f"技术 {raw:+.1f} / 资金 {delta:+.1f}"
    )
    for line in payload.get("evidence") or []:
        notes.append(f"资金面：{line}")
    rec["analysis_notes"] = notes
    action, action_code, blended_conf = _action_from_score(
        rec["score"], strong_buy, buy, hold_floor, sell_floor
    )
    rec["recommendation"] = action
    rec["action"] = action_code
    rec["blended_confidence"] = blended_conf
    rec["confidence"] = rec["tech_confidence"]
    if delta:
        reason = rec.get("reason") or ""
        suffix = f"资金面软评分 {delta:+.1f}（倾向，非预测）"
        rec["reason"] = f"{reason}；{suffix}" if reason else suffix
    return rec


class FundFlowAnalyzer:
    """可选的薄封装，方便页面一次传入多张表。"""

    def __init__(self, rank_df=None, stock_df=None, north_df=None, market_df=None, price_df=None):
        self.rank_df = rank_df
        self.stock_df = stock_df
        self.north_df = north_df
        self.market_df = market_df
        self.price_df = price_df

    def rank_summary(self, n=8):
        return summarize_rank(self.rank_df, n=n)

    def stock_snapshot(self):
        return latest_stock_snapshot(self.stock_df)

    def north_regime(self, window=5):
        return northbound_regime(self.north_df, window=window)

    def notes(self):
        return stock_flow_notes(self.stock_df, self.north_df)

    def bias(self, price_df=None):
        return fund_flow_bias(
            market_df=self.market_df,
            north_df=self.north_df,
            sector_rank=self.rank_df,
            stock_flow=self.stock_df,
            price_df=price_df if price_df is not None else self.price_df,
        )
