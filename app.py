"""
BigA Stock Analysis - 大A股数据分析应用
集成 AKShare（默认）与 TuShare（可选）数据源，OpenBB 未接入
主应用文件
"""

import streamlit as st
import pandas as pd
import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 设置页面配置
st.set_page_config(
    page_title="大A股数据分析",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 自定义CSS样式
st.markdown("""
<style>
    .main {
        padding-top: 2rem;
    }
    .big-font {
        font-size: 2rem !important;
        font-weight: bold;
    }
    .metric-card {
        background-color: #f0f2f6;
        padding: 1rem;
        border-radius: 0.5rem;
        border-left: 3px solid #1f77b4;
    }
    .positive { color: #FF4444; }
    .negative { color: #00AA00; }
    .stSelectbox > div > div {
        background-color: white;
    }
</style>
""", unsafe_allow_html=True)

# 初始化session state
if 'initialized' not in st.session_state:
    st.session_state.initialized = True
    st.session_state.data_source = 'akshare'
    st.session_state.selected_stock = '000001'

# 侧边栏
with st.sidebar:
    st.title("📈 大A股数据分析")
    st.markdown("---")
    
    # 数据源选择
    st.subheader("📊 数据源")
    data_source = st.radio(
        "选择数据源",
        ["AKShare (推荐)", "TuShare"],
        key="data_source_radio"
    )
    st.session_state.data_source = 'akshare' if data_source == "AKShare (推荐)" else 'tushare'
    
    if st.session_state.data_source == 'tushare':
        st.info("💡 使用TuShare需要配置Token")
    
    st.markdown("---")
    
    # 快速链接
    st.subheader("🔗 快速链接")
    if st.button("🏠 首页"):
        st.switch_page("pages/_home.py")
    if st.button("📊 交易决策"):
        st.switch_page("pages/_trading_decision.py")
    if st.button("📈 股票分析"):
        st.switch_page("pages/_stock_analysis.py")
    if st.button("🔍 股票筛选"):
        st.switch_page("pages/_screener.py")
    if st.button("💼 投资组合"):
        st.switch_page("pages/_portfolio.py")
    if st.button("📊 市场分析"):
        st.switch_page("pages/_market.py")
    
    st.markdown("---")
    
    # 关于信息
    st.subheader("ℹ️ 关于")
    st.markdown("""
    **BigA Stock Analysis**  
    版本: v1.0.0  
    
    数据源: AKShare + TuShare（可选）  
    OpenBB: 未集成（可选未来扩展）
    
    [GitHub](https://github.com) | 
    [文档](https://github.com)
    """)

# 主内容区域
def show_home():
    """显示首页"""
    st.title("🏠 欢迎使用大A股数据分析")
    st.markdown("---")
    
    # 介绍
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("""
        ### 📊 交易决策
        **专业买卖信号分析**
        - 技术面信号识别
        - 买卖点决策
        - 风险评级
        """)
    
    with col2:
        st.markdown("""
        ### 📈 行情分析
        实时查看A股市场行情
        - 实时/历史行情
        - K线图分析
        - 技术指标
        """)
    
    with col3:
        st.markdown("""
        ### 💼 投资组合
        管理你的投资组合
        - 持仓管理
        - 收益分析
        - 风险评估
        """)
    
    st.markdown("---")
    
    # 快速开始
    st.subheader("🚀 快速开始")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.markdown("""
        1. **选择数据源**: 在侧边栏选择AKShare或TuShare
        2. **查看股票**: 点击"股票分析"开始使用
        3. **输入代码**: 输入6位股票代码（如：000001）
        4. **查看数据**: 查看实时行情、K线图、技术指标
        """)
    
    with col2:
        st.markdown("""
        #### 📝 示例
        - 平安银行: `000001`
        - 万科A: `000002`
        - 浦发银行: `600000`
        - 贵州茅台: `600519`
        """)
    
    st.markdown("---")
    
    # 功能特点
    st.subheader("✨ 功能特点")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("""
        - ✅ **多数据源**: AKShare + TuShare
        - ✅ **实时行情**: 获取最新市场数据
        - ✅ **技术分析**: MA, MACD, RSI, KDJ
        - ✅ **交互图表**: Plotly交互式图表
        """)
    
    with col2:
        st.markdown("""
        - ✅ **投资组合**: 持仓管理 + 收益分析
        - ✅ **智能筛选**: 多条件股票筛选
        - ✅ **数据导出**: 支持CSV/Excel导出
        - ✅ **可视化**: 丰富的数据可视化
        """)

# 显示首页
show_home()

# 页脚
st.markdown("---")
st.markdown("""
<div style='text-align: center; color: #666;'>
    <p>BigA Stock Analysis © 2024 | Powered by Streamlit + AKShare/TuShare</p>
</div>
""", unsafe_allow_html=True)

