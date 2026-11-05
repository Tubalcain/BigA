"""
首页
"""

import streamlit as st
import pandas as pd

st.set_page_config(page_title="首页", page_icon="🏠", layout="wide")

st.title("🏠 首页")
st.markdown("---")

# 欢迎信息
st.info("""
欢迎使用大A股数据分析工具！

本应用使用 AKShare（默认）和可选的 TuShare 数据源，为投资者提供 A 股行情、技术分析和组合跟踪。OpenBB 未接入。
""")

# 功能导航
st.subheader("📋 功能导航")

col1, col2 = st.columns(2)

with col1:
    if st.button("📊 交易决策", use_container_width=True):
        st.switch_page("pages/_trading_decision.py")
    st.markdown("**最推荐** - 买卖信号分析，交易决策支持")

with col2:
    if st.button("📈 股票分析", use_container_width=True):
        st.switch_page("pages/_stock_analysis.py")
    st.markdown("查看股票行情、K线图、技术指标")

col3, col4 = st.columns(2)

with col3:
    if st.button("🔍 股票筛选", use_container_width=True):
        st.switch_page("pages/_screener.py")
    st.markdown("多条件筛选优质股票")

with col4:
    if st.button("💼 投资组合", use_container_width=True):
        st.switch_page("pages/_portfolio.py")
    st.markdown("管理投资组合，分析收益")

st.markdown("---")

# 快速统计
st.subheader("📊 市场概况")

try:
    from src.data import describe_data_problems, get_active_client, source_switch_note

    preferred = st.session_state.get("data_source", "akshare")
    ak_data = get_active_client(preferred)
    note = source_switch_note(preferred, ak_data)
    if note:
        st.caption(note)
    # 首页只拉指数，避免每次打开都打全市场快照（易限流、很慢）
    indices = ak_data.get_index_quotes()
    overview = ak_data.get_market_overview(light=True)

    col1, col2, col3, col4 = st.columns(4)
    shown = False

    def _index_metric(column, keyword, label):
        if indices is None or indices.empty or "name" not in indices.columns:
            return False
        row = indices[indices["name"].astype(str).str.contains(keyword, na=False)]
        if row.empty:
            return False
        item = row.iloc[0]
        price = item.get("price")
        chg = item.get("change_pct")
        delta = f"{chg:+.2f}%" if pd.notna(chg) else None
        column.metric(label, f"{float(price):,.2f}" if pd.notna(price) else "-", delta)
        return True

    shown |= _index_metric(col1, "上证", "上证指数")
    shown |= _index_metric(col2, "深证", "深证成指")
    shown |= _index_metric(col3, "创业板", "创业板指")

    if overview is not None and not overview.empty and {"type", "count"}.issubset(overview.columns):
        up = overview.loc[overview["type"] == "上涨", "count"]
        if not up.empty:
            col4.metric("上涨股票", f"{int(up.iloc[0]):,}")
            shown = True
        source = overview.attrs.get("source") or ak_data.name
        st.caption(f"数据来源: {source}")
    elif shown:
        source = None
        if indices is not None and not indices.empty:
            source = indices.attrs.get("source")
        st.caption(f"数据来源: {source or ak_data.name}")
    if not shown:
        st.info("市场快照暂不可用，请检查网络后刷新。")
        for frame in (indices, overview):
            msg = describe_data_problems(frame)
            if msg and msg != "empty frame":
                st.caption(msg)
                break
except Exception as exc:
    st.warning("市场数据加载失败")
    st.caption(str(exc))

