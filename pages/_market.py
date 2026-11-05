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


def _show_empty(frame, fallback="接口暂时不可用（源站限流、字段变更或权限不足时会自动降级）。"):
    st.info(fallback)
    reason = _empty_reason(frame)
    if reason:
        st.caption(reason)


def _flow_table(df, extra=None, rows=20):
    cols = ["code", "name", "net_inflow", "main_net_inflow", "super_large_net", "large_net", "small_net", "change_pct"]
    if extra:
        cols.extend(extra)
    show = [c for c in cols if c in df.columns]
    st.dataframe(df[show].head(rows) if show else df.head(rows), use_container_width=True, hide_index=True)


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
    st.caption("金额已统一为万元。主力 ≈ 超大单 + 大单；小单近似散户。源站限流或积分不足时会空表降级并标明原因。")

    ctrl1, ctrl2, ctrl3 = st.columns(3)
    with ctrl1:
        period = st.selectbox("统计周期", ["今日", "3日", "5日", "10日"], index=0)
    with ctrl2:
        sector_kind = st.selectbox("板块类型", ["行业", "概念", "地域"], index=0)
    with ctrl3:
        rank_n = st.slider("榜单条数", min_value=8, max_value=30, value=15, step=1)

    try:
        from src.analysis.fund_flow import (
            enrich_sector_flow,
            extreme_rows,
            format_wan,
            main_vs_retail,
            northbound_regime,
            rank_inflow,
            rank_outflow,
            summarize_rank,
            unit_caption,
        )
        from src.visualization.charts import PlotlyChartGenerator

        ak_data = _load_client()
        chart_gen = PlotlyChartGenerator()

        with st.spinner("正在获取资金流向..."):
            sector = ak_data.get_sector_fund_flow(indicator=period, sector_type=sector_kind)
            stock_rank = ak_data.get_stock_fund_flow_rank(indicator=period)
            market_flow = ak_data.get_market_fund_flow()
            north = ak_data.get_northbound_flow()
            boards = ak_data.get_industry_boards()

        sector = enrich_sector_flow(sector, boards)

        st.markdown("#### 市场资金")
        if market_flow is not None and not market_flow.empty and "main_net_inflow" in market_flow.columns:
            last = market_flow.iloc[-1]
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("主力净流入", format_wan(last.get("main_net_inflow")))
            m2.metric("超大单", format_wan(last.get("super_large_net")))
            m3.metric("大单", format_wan(last.get("large_net")))
            m4.metric("小单(散户)", format_wan(last.get("small_net")))
            y_cols = [c for c in ["main_net_inflow", "super_large_net", "small_net"] if c in market_flow.columns]
            fig_mkt = chart_gen.line_chart(market_flow.tail(60), "date", y_cols, title="市场主力资金（近60日）")
            st.plotly_chart(fig_mkt, use_container_width=True)
            st.caption(unit_caption(market_flow))
        else:
            summary = summarize_rank(sector)
            if sector is not None and not sector.empty:
                s1, s2, s3 = st.columns(3)
                s1.metric("板块净流入合计", format_wan(summary["total_net_inflow"]))
                s2.metric("净流入板块", summary["inflow_count"])
                s3.metric("净流出板块", summary["outflow_count"])
                st.caption("大盘序列暂不可用，上表由板块排名加总近似（行业之间可能有重叠）。")
            else:
                _show_empty(market_flow, "市场级资金序列暂时不可用。")

        st.markdown("---")
        st.markdown(f"#### {sector_kind}资金排名（{period}）")
        if sector is not None and not sector.empty and "net_inflow" in sector.columns:
            vs = main_vs_retail(sector)
            c1, c2, c3 = st.columns(3)
            c1.metric("主力合计", format_wan(vs.get("main_net_inflow")))
            c2.metric("小单合计", format_wan(vs.get("retail_net_inflow")))
            c3.caption(vs.get("note") or "")
            chart_df = extreme_rows(sector, n=rank_n)
            label = "name" if "name" in chart_df.columns else "code"
            fig = chart_gen.signed_bar_chart(
                chart_df, label, "net_inflow", title=f"{sector_kind}净流入 / 净流出"
            )
            st.plotly_chart(fig, use_container_width=True)
            left, right = st.columns(2)
            with left:
                st.markdown("**流入榜**")
                _flow_table(rank_inflow(sector, n=rank_n))
            with right:
                st.markdown("**流出榜**")
                _flow_table(rank_outflow(sector, n=rank_n))
            st.caption(unit_caption(sector))
        else:
            _show_empty(sector, "板块资金流向暂时不可用。")

        st.markdown("---")
        st.markdown(f"#### 个股主力排名（{period}）")
        if stock_rank is not None and not stock_rank.empty and "net_inflow" in stock_rank.columns:
            chart_df = extreme_rows(stock_rank, n=rank_n)
            label = "name" if "name" in chart_df.columns else "code"
            fig = chart_gen.signed_bar_chart(
                chart_df, label, "net_inflow", title="个股主力净流入 / 净流出"
            )
            st.plotly_chart(fig, use_container_width=True)
            left, right = st.columns(2)
            with left:
                st.markdown("**流入榜**")
                _flow_table(rank_inflow(stock_rank, n=rank_n))
            with right:
                st.markdown("**流出榜**")
                _flow_table(rank_outflow(stock_rank, n=rank_n))
            st.caption(unit_caption(stock_rank))
        else:
            _show_empty(stock_rank, "个股资金排名暂时不可用。")

        st.markdown("---")
        st.markdown("#### 北向 / 南向资金")
        if north is not None and not north.empty and "net_inflow" in north.columns:
            regime = northbound_regime(north)
            n1, n2, n3 = st.columns(3)
            n1.metric("最新北向", format_wan(regime.get("latest")))
            n2.metric("近5日合计", format_wan(regime.get("window_sum")))
            n3.metric("状态", {"inflow": "净流入", "outflow": "净流出", "mixed": "分化"}.get(regime.get("regime"), "未知"))
            st.caption(regime.get("note") or "")
            y_cols = [
                c
                for c in ["north_inflow", "south_inflow", "net_inflow"]
                if c in north.columns and north[c].notna().any()
            ]
            # 避免 north_inflow 与 net_inflow 重复画一条线
            if "north_inflow" in y_cols and "net_inflow" in y_cols:
                y_cols = [c for c in y_cols if c != "net_inflow"]
            fig_n = chart_gen.line_chart(north.tail(90), "date", y_cols, title="北向 / 南向净流入（近90日）")
            st.plotly_chart(fig_n, use_container_width=True)
            show_cols = [c for c in ["date", "north_inflow", "south_inflow", "net_inflow", "hgt", "sgt"] if c in north.columns]
            st.dataframe(north[show_cols].tail(12) if show_cols else north.tail(12), use_container_width=True, hide_index=True)
            st.caption(unit_caption(north))
        else:
            _show_empty(north, "北向资金暂时不可用。")

    except Exception as e:
        st.error(f"获取资金流向时发生错误: {str(e)}")

# 页脚
st.markdown("---")
st.caption(f"数据来源: AKShare / TuShare 回退 | 更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
