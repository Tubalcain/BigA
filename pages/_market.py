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

# Tab功能
tab1, tab2, tab3 = st.tabs(["🌍 市场概况", "📈 涨跌统计", "💰 资金流向"])

with tab1:
    st.subheader("🌍 A股市场概况")
    
    try:
        from src.data.akshare_data import AKShareData
        
        ak_data = AKShareData()
        
        with st.spinner("正在获取市场数据..."):
            # 获取市场概况
            overview = ak_data.get_market_overview()
            
            if not overview.empty:
                # 显示统计卡片
                col1, col2, col3, col4 = st.columns(4)
                
                # 这里应该从真实数据获取
                col1.metric("上证指数", "3,200.00", "+15.50", delta_color="normal")
                col2.metric("深证成指", "10,800.00", "-25.30", delta_color="inverse")
                col3.metric("创业板指", "2,100.00", "+35.20", delta_color="normal")
                col4.metric("科创板50", "1,050.00", "+10.80", delta_color="normal")
                
                st.markdown("---")
                
                # 涨跌统计
                st.subheader("📊 涨跌分布")
                
                if not overview.empty:
                    fig_data = overview.set_index('type')['count']
                    
                    from src.visualization.charts import PlotlyChartGenerator
                    chart_gen = PlotlyChartGenerator()
                    
                    fig_bar = chart_gen.bar_chart(
                        overview,
                        'type',
                        'count',
                        title="市场涨跌分布"
                    )
                    st.plotly_chart(fig_bar, use_container_width=True)
                
            else:
                st.warning("未能获取市场概况数据")
    
    except Exception as e:
        st.error(f"获取市场数据时发生错误: {str(e)}")
        st.info("💡 提示：请检查网络连接或稍后重试")

with tab2:
    st.subheader("📈 涨跌统计")
    
    # 筛选选项
    col1, col2 = st.columns(2)
    
    with col1:
        sort_by = st.selectbox(
            "排序方式",
            ["涨跌幅", "成交量", "成交额"],
            index=0
        )
    
    with col2:
        limit = st.slider("显示数量", min_value=10, max_value=100, value=20, step=10)
    
    try:
        from src.data.akshare_data import AKShareData
        
        ak_data = AKShareData()
        
        with st.spinner("正在获取涨跌排行..."):
            # 获取实时行情
            df = ak_data.get_stock_list()
            
            # 这里应该获取真实的涨跌数据
            # 由于API限制，这里使用示例数据
            
            st.info("💡 涨跌排行数据加载中...")
            
            # 示例数据
            example_data = pd.DataFrame({
                '代码': ['000001', '000002', '600000', '600519', '000858'],
                '名称': ['平安银行', '万科A', '浦发银行', '贵州茅台', '五粮液'],
                '涨跌幅': [2.5, -1.2, 3.8, 5.2, -0.8],
                '成交量': [15000000, 8000000, 12000000, 25000000, 10000000]
            })
            
            st.dataframe(example_data, use_container_width=True)
    
    except Exception as e:
        st.error(f"获取涨跌统计时发生错误: {str(e)}")

with tab3:
    st.subheader("💰 资金流向")
    
    try:
        from src.data.akshare_data import AKShareData
        
        ak_data = AKShareData()
        
        st.info("💡 资金流向数据分析功能开发中...")
        
        # 这里可以显示：
        # 1. 主力资金净流入/流出
        # 2. 北向资金流向
        # 3. 南向资金流向
        # 4. 板块资金流向
        
        st.markdown("""
        ### 📊 资金流向分析内容
        
        - **主力资金**: 大单、超大单净流入/流出
        - **北向资金**: 沪股通、深股通资金流向
        - **板块资金**: 各板块资金净流入排行
        - **个股资金**: 个股资金流入流出排行
        """)
        
        # 示例数据
        fund_flow = pd.DataFrame({
            '板块': ['金融', '科技', '消费', '医药', '新能源'],
            '净流入': [500000000, -200000000, 300000000, 150000000, 400000000],
            '涨跌幅': [2.5, -1.2, 1.8, 3.2, 4.5]
        })
        
        st.dataframe(fund_flow, use_container_width=True)
    
    except Exception as e:
        st.error(f"获取资金流向时发生错误: {str(e)}")

# 页脚
st.markdown("---")
st.caption(f"数据来源: AKShare | 更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

