"""
首页
"""

import streamlit as st

st.set_page_config(page_title="首页", page_icon="🏠", layout="wide")

st.title("🏠 首页")
st.markdown("---")

# 欢迎信息
st.info("""
欢迎使用大A股数据分析工具！

本应用基于OpenBB框架，集成AKShare和TuShare数据源，为投资者提供专业的A股数据分析服务。
""")

# 功能导航
st.subheader("📋 功能导航")

col1, col2, col3 = st.columns(3)

with col1:
    if st.button("📈 股票分析", use_container_width=True):
        st.switch_page("pages/_stock_analysis.py")
    st.markdown("查看股票行情、K线图、技术指标")

with col2:
    if st.button("🔍 股票筛选", use_container_width=True):
        st.switch_page("pages/_screener.py")
    st.markdown("多条件筛选优质股票")

with col3:
    if st.button("💼 投资组合", use_container_width=True):
        st.switch_page("pages/_portfolio.py")
    st.markdown("管理投资组合，分析收益")

st.markdown("---")

# 快速统计
st.subheader("📊 市场概况")

try:
    from src.data.akshare_data import AKShareData
    
    ak_data = AKShareData()
    overview = ak_data.get_market_overview()
    
    if not overview.empty:
        col1, col2, col3, col4 = st.columns(4)
        
        col1.metric("上证指数", "3,000", "+0.5%")
        col2.metric("深证成指", "10,000", "-0.3%")
        col3.metric("创业板指", "2,000", "+1.2%")
        col4.metric("上涨股票", "1,500", "45%")
except:
    st.info("正在加载市场数据...")

