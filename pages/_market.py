"""
市场分析页面
主要功能：市场概况、涨跌统计、资金流向
"""

import streamlit as st
import pandas as pd
from datetime import datetime

st.set_page_config(page_title="市场分析", page_icon="📊", layout="wide")

st.title("📊 市场分析")
st.markdown("---")

try:
    from src.data import get_active_client, source_switch_note

    _preferred = st.session_state.get("data_source", "akshare")
    _note = source_switch_note(_preferred, get_active_client(_preferred))
    if _note:
        st.caption(_note)
except Exception:
    pass

# Tab功能
tab1, tab2, tab3 = st.tabs(["🌍 市场概况", "📈 涨跌统计", "💰 资金流向"])


def _load_client():
    from src.data import get_active_client

    return get_active_client(st.session_state.get("data_source", "akshare"))


def _empty_reason(frame, fallback=""):
    from src.data import describe_data_problems

    msg = describe_data_problems(frame)
    if msg and msg != "empty frame":
        return msg
    return fallback


def _index_metric(column, indices, keyword, label):
    if indices is None or indices.empty or "name" not in indices.columns:
        column.metric(label, "-")
        return
    row = indices[indices["name"].astype(str).str.contains(keyword, na=False)]
    if row.empty:
        column.metric(label, "-")
        return
    item = row.iloc[0]
    price = item.get("price")
    chg = item.get("change_pct")
    delta = f"{float(chg):+.2f}%" if pd.notna(chg) else None
    column.metric(label, f"{float(price):,.2f}" if pd.notna(price) else "-", delta)


with tab1:
    st.subheader("🌍 A股市场概况")

    try:
        ak_data = _load_client()

        with st.spinner("正在获取市场数据..."):
            overview = ak_data.get_market_overview()
            indices = ak_data.get_index_quotes()

        col1, col2, col3, col4 = st.columns(4)
        _index_metric(col1, indices, "上证", "上证指数")
        _index_metric(col2, indices, "深证", "深证成指")
        _index_metric(col3, indices, "创业板", "创业板指")
        _index_metric(col4, indices, "科创", "科创50")

        source = None
        if indices is not None and not indices.empty:
            source = indices.attrs.get("source")
        if overview is not None and not overview.empty:
            source = source or overview.attrs.get("source")
        st.caption(f"指数数据来源: {source or 'akshare'}")

        st.markdown("---")
        st.subheader("📊 涨跌分布")

        if overview is not None and not overview.empty and {"type", "count"}.issubset(overview.columns):
            from src.visualization.charts import PlotlyChartGenerator

            chart_gen = PlotlyChartGenerator()
            fig_bar = chart_gen.bar_chart(
                overview,
                "type",
                "count",
                title="市场涨跌分布",
            )
            st.plotly_chart(fig_bar, use_container_width=True)
            st.dataframe(overview[["type", "count"]], use_container_width=True, hide_index=True)
        else:
            st.warning("未能获取市场概况数据")
            reason = _empty_reason(overview)
            if reason:
                st.caption(reason)

        boards = ak_data.get_industry_boards()
        if boards is not None and not boards.empty:
            st.markdown("---")
            st.subheader("行业 / 板块")
            show_cols = [c for c in ["name", "code", "change_pct", "price", "turnover"] if c in boards.columns]
            st.dataframe(boards[show_cols].head(30) if show_cols else boards.head(30), use_container_width=True)

    except Exception as e:
        st.error(f"获取市场数据时发生错误: {str(e)}")
        st.info("💡 提示：请检查网络连接或稍后重试")

with tab2:
    st.subheader("📈 涨跌统计")

    col1, col2 = st.columns(2)

    with col1:
        sort_by = st.selectbox(
            "排序方式",
            ["涨跌幅", "成交量", "成交额"],
            index=0,
        )

    with col2:
        limit = st.slider("显示数量", min_value=10, max_value=100, value=20, step=10)

    try:
        ak_data = _load_client()

        with st.spinner("正在获取涨跌排行..."):
            df = ak_data.get_stock_list()

        if df is None or df.empty:
            st.warning("未能获取实时行情，无法生成涨跌排行。")
            reason = _empty_reason(df)
            if reason:
                st.caption(reason)
        else:
            sort_map = {"涨跌幅": "change_pct", "成交量": "volume", "成交额": "amount"}
            sort_col = sort_map[sort_by]
            if sort_col not in df.columns:
                st.warning(f"当前数据没有 {sort_by} 字段，显示原始列表。")
                ranked = df.head(limit)
            else:
                ranked = df.sort_values(sort_col, ascending=False).head(limit)
            show_cols = [
                c
                for c in ["code", "name", "price", "change_pct", "volume", "amount", "turnover", "board", "status"]
                if c in ranked.columns
            ]
            st.dataframe(ranked[show_cols] if show_cols else ranked, use_container_width=True)
            st.caption(f"数据来源: {df.attrs.get('source', 'akshare')} | 单位: 涨跌幅=% , 成交量=手 , 成交额=元")

    except Exception as e:
        st.error(f"获取涨跌统计时发生错误: {str(e)}")

with tab3:
    st.subheader("💰 资金流向")

    try:
        ak_data = _load_client()

        with st.spinner("正在获取资金流向..."):
            flow = ak_data.get_fund_flow()
            north = ak_data.get_northbound_flow()

        if flow is not None and not flow.empty:
            show_cols = [c for c in ["name", "net_inflow", "change_pct"] if c in flow.columns]
            st.dataframe(flow[show_cols].head(30) if show_cols else flow.head(30), use_container_width=True)
            st.caption(f"数据来源: {flow.attrs.get('source', 'akshare')} | 净流入单位视上游接口而定")
        else:
            st.info("资金流向接口暂时不可用（源站限流或字段变更时会自动降级）。")
            reason = _empty_reason(flow)
            if reason:
                st.caption(reason)

        if north is not None and not north.empty:
            st.markdown("#### 北向资金")
            st.dataframe(north.tail(10), use_container_width=True)

    except Exception as e:
        st.error(f"获取资金流向时发生错误: {str(e)}")

# 页脚
st.markdown("---")
st.caption(f"数据来源: AKShare / TuShare 回退 | 更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
