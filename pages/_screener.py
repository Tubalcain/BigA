"""
股票筛选器页面
主要功能：多条件筛选股票
"""

import streamlit as st

st.set_page_config(page_title="股票筛选", page_icon="🔍", layout="wide")

st.title("🔍 股票筛选器")
st.markdown("---")

# 侧边栏
with st.sidebar:
    st.header("🎯 筛选条件")

    # 交易所选择
    exchange = st.selectbox(
        "交易所",
        ["所有", "深圳交易所", "上海交易所", "北京交易所"],
        index=0,
    )

    # 市值筛选
    st.subheader("💼 市值筛选")
    market_cap_min = st.number_input("最小市值（万元）", min_value=0, value=0, step=1000)
    market_cap_max = st.number_input("最大市值（万元）", min_value=0, value=1000000000, step=1000)

    # 涨跌幅筛选
    st.subheader("📈 涨跌幅筛选")
    change_min = st.number_input("最小涨跌幅（%）", min_value=-30.0, max_value=30.0, value=-10.0, step=0.1)
    change_max = st.number_input("最大涨跌幅（%）", min_value=-30.0, max_value=30.0, value=10.0, step=0.1)

    # 成交量筛选
    st.subheader("📊 成交量筛选")
    volume_min = st.number_input("最小成交量（手）", min_value=0, value=0, step=1000)

    exclude_halted = st.checkbox("排除停牌", value=True)

    st.subheader("💰 资金流向")
    use_fund_flow = st.checkbox("叠加主力资金排名", value=False, help="多一次排名接口；限流时会跳过并提示。")
    flow_period = st.selectbox(
        "资金排名周期",
        ["今日", "3日", "5日"],
        index=0,
        help="用排名接口的周期合计，不逐股拉历史。",
    )
    min_net_inflow = st.number_input("最小主力净流入（万元）", value=0.0, step=1000.0)
    require_period_inflow = st.checkbox(
        "仅保留该周期净流入>0",
        value=False,
        help="近似「连续流入」：用 3日/5日排名净额，不是逐日 streak。",
    )
    st.caption(
        "「连续流入」依赖排名接口的多日净额，不逐股请求历史。"
        "价资同向需要个股 K 线 + 资金序列，筛选器不逐股打接口，故未提供该开关。"
    )

    # 筛选按钮
    screen_btn = st.button("🚀 开始筛选", type="primary", use_container_width=True)

# 主内容区域
if screen_btn:
    try:
        from src.data import describe_data_problems, get_active_client, source_switch_note

        preferred = st.session_state.get("data_source", "akshare")
        ak_data = get_active_client(preferred)
        note = source_switch_note(preferred, ak_data)
        if note:
            st.caption(note)

        with st.spinner("正在获取股票列表..."):
            df = ak_data.get_stock_list(exchange)

        if df is not None and not df.empty:
            filtered = df.copy()
            applied = []

            if "market_cap" in filtered.columns:
                filtered = filtered[
                    (filtered["market_cap"].fillna(0) >= market_cap_min)
                    & (filtered["market_cap"].fillna(0) <= market_cap_max)
                ]
                applied.append("市值")
            if "change_pct" in filtered.columns:
                filtered = filtered[
                    (filtered["change_pct"].fillna(0) >= change_min)
                    & (filtered["change_pct"].fillna(0) <= change_max)
                ]
                applied.append("涨跌幅")
            if "volume" in filtered.columns:
                filtered = filtered[filtered["volume"].fillna(0) >= volume_min]
                applied.append("成交量")
            if exclude_halted and "status" in filtered.columns:
                filtered = filtered[filtered["status"] != "halted"]
                applied.append("非停牌")
            if use_fund_flow:
                rank = ak_data.get_stock_fund_flow_rank(indicator=flow_period)
                if rank is not None and not rank.empty and "code" in rank.columns:
                    keep = [c for c in ["code", "net_inflow", "main_net_inflow", "period"] if c in rank.columns]
                    extra = rank[keep].drop_duplicates("code")
                    filtered = filtered.merge(extra, on="code", how="left")
                    if min_net_inflow and "net_inflow" in filtered.columns:
                        filtered = filtered[filtered["net_inflow"].fillna(0) >= min_net_inflow]
                    if require_period_inflow and "net_inflow" in filtered.columns:
                        filtered = filtered[filtered["net_inflow"].fillna(0) > 0]
                    applied.append(f"主力资金({flow_period})")
                    if require_period_inflow:
                        applied.append(f"{flow_period}净流入>0")
                else:
                    st.caption("主力资金排名暂不可用，已跳过该条件。")
                    reason = describe_data_problems(rank)
                    if reason:
                        st.caption(reason)

            st.success(f"✓ 获取到 {len(df)} 只股票，筛选后 {len(filtered)} 只")
            if applied:
                st.caption("已应用条件: " + " / ".join(applied) + f" | 来源: {df.attrs.get('source', 'akshare')}")
            else:
                st.info("当前列表没有市值/涨跌幅/成交量字段，仅按交易所过滤。")

            st.subheader("📋 筛选结果")
            show_cols = [
                c
                for c in [
                    "code",
                    "name",
                    "price",
                    "change_pct",
                    "volume",
                    "amount",
                    "market_cap",
                    "pe",
                    "pb",
                    "board",
                    "exchange",
                    "status",
                    "net_inflow",
                    "main_net_inflow",
                ]
                if c in filtered.columns
            ]
            st.dataframe(
                filtered[show_cols] if show_cols else filtered,
                use_container_width=True,
                height=600,
            )

            col1, col2 = st.columns([3, 1])
            with col2:
                csv = filtered.to_csv(index=False)
                st.download_button(
                    label="📥 下载筛选结果",
                    data=csv,
                    file_name="stock_screener_results.csv",
                    mime="text/csv",
                )
        else:
            st.warning("未能获取股票列表")
            msg = describe_data_problems(df)
            if msg:
                st.caption(msg)

    except Exception as e:
        st.error(f"筛选过程中发生错误: {str(e)}")

else:
    # 显示使用说明
    st.info("""
    👋 使用股票筛选器快速找到符合你条件的股票！
    
    在左侧设置筛选条件，然后点击"开始筛选"按钮。
    """)

    # 功能说明
    st.subheader("📝 功能说明")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("""
        ### 🎯 筛选维度
        
        - **交易所**: 选择深圳、上海或北京交易所
        - **市值**: 按总市值（万元）筛选
        - **涨跌幅**: 按当日涨幅筛选
        - **成交量**: 按成交量（手）筛选
        - **主力资金**: 可选叠加个股净流入排名（万元）；「该周期净流入>0」用排名接口，不逐股拉历史。价资同向未提供。
        """)

    with col2:
        st.markdown("""
       ### 💡 使用技巧
        
        - 组合使用多个条件可获得更精确的结果
        - 支持导出筛选结果为CSV文件
        - 列表优先来自实时快照；快照失败时回退到代码表
        """)

    st.subheader("🎓 示例筛选条件")

    example1 = {
        "交易所": "深圳交易所",
        "市值": "10亿 - 100亿（即 100000 - 1000000 万元）",
        "涨跌幅": "0% - 5%",
        "成交量": "> 100万手",
    }

    st.json(example1)

# 页脚
st.markdown("---")
st.caption("数据来源: AKShare / TuShare 回退 | 筛选结果仅供参考，投资需谨慎")
