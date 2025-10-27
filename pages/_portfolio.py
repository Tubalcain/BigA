"""
投资组合管理页面
主要功能：管理持仓、分析收益
"""

import streamlit as st
import pandas as pd
from datetime import datetime

st.set_page_config(page_title="投资组合", page_icon="💼", layout="wide")

st.title("💼 投资组合管理")
st.markdown("---")

# 初始化session state
if 'portfolio' not in st.session_state:
    st.session_state.portfolio = []

# 侧边栏
with st.sidebar:
    st.header("➕ 添加持仓")
    
    stock_code = st.text_input("股票代码", value="000001")
    stock_name = st.text_input("股票名称", value="平安银行")
    quantity = st.number_input("持有数量", min_value=1, value=1000, step=100)
    cost_price = st.number_input("成本价", min_value=0.01, value=12.0, step=0.1)
    
    if st.button("➕ 添加持仓", type="primary", use_container_width=True):
        st.session_state.portfolio.append({
            'code': stock_code,
            'name': stock_name,
            'quantity': quantity,
            'cost_price': cost_price
        })
        st.success(f"✓ 已添加 {stock_name}")
        st.rerun()
    
    if st.button("🗑️ 清空持仓", type="secondary", use_container_width=True):
        st.session_state.portfolio = []
        st.rerun()

# 主内容区域
if len(st.session_state.portfolio) > 0:
    try:
        from src.analysis.portfolio import PortfolioAnalyzer
        from src.data.akshare_data import AKShareData
        
        analyzer = PortfolioAnalyzer(st.session_state.portfolio)
        ak_data = AKShareData()
        
        # 获取当前价格
        current_prices = {}
        with st.spinner("正在获取最新价格..."):
            for pos in st.session_state.portfolio:
                quote = ak_data.get_realtime_quote(pos['code'])
                if not quote.empty and 'price' in quote.columns:
                    current_prices[pos['code']] = quote['price'].iloc[0]
                else:
                    # 如果没有实时数据，使用成本价
                    current_prices[pos['code']] = pos['cost_price']
        
        # 计算投资组合价值
        portfolio_info = analyzer.calculate_portfolio_value(current_prices)
        
        # 显示总体情况
        st.subheader("📊 总体情况")
        col1, col2, col3, col4 = st.columns(4)
        
        col1.metric("总成本", f"¥{portfolio_info['total_cost']:,.2f}")
        col2.metric("当前价值", f"¥{portfolio_info['total_value']:,.2f}")
        col3.metric("总盈亏", f"¥{portfolio_info['total_profit']:,.2f}")
        col4.metric("收益率", f"{portfolio_info['total_profit_pct']:.2f}%")
        
        # 持仓明细
        st.subheader("📋 持仓明细")
        
        holdings_df = pd.DataFrame(portfolio_info['holdings'])
        st.dataframe(
            holdings_df[['code', 'name', 'quantity', 'cost_price', 'current_price', 'profit', 'profit_pct', 'weight']].style.format({
                'cost_price': '{:.2f}',
                'current_price': '{:.2f}',
                'profit': '{:.2f}',
                'profit_pct': '{:.2f}%',
                'weight': '{:.2f}%'
            }),
            use_container_width=True,
            height=300
        )
        
        # 生成图表
        from src.visualization.charts import PlotlyChartGenerator
        
        chart_gen = PlotlyChartGenerator()
        
        col1, col2 = st.columns(2)
        
        with col1:
            # 持仓分布饼图
            pie_labels = [h['name'] for h in portfolio_info['holdings']]
            pie_values = [h['current_value'] for h in portfolio_info['holdings']]
            
            fig_pie = chart_gen.pie_chart(
                pie_labels,
                pie_values,
                title="持仓分布"
            )
            st.plotly_chart(fig_pie, use_container_width=True)
        
        with col2:
            # 盈亏柱状图
            bar_names = [h['name'] for h in portfolio_info['holdings']]
            bar_profits = [h['profit'] for h in portfolio_info['holdings']]
            
            fig_bar = chart_gen.bar_chart(
                pd.DataFrame({'name': bar_names, 'profit': bar_profits}),
                'name',
                'profit',
                title="持仓盈亏"
            )
            st.plotly_chart(fig_bar, use_container_width=True)
        
        # 生成报告
        report = analyzer.generate_portfolio_report(current_prices)
        
        with st.expander("📄 查看详细报告"):
            st.markdown(report)
    
    except Exception as e:
        st.error(f"分析过程中发生错误: {str(e)}")
        st.info("💡 提示：请确保网络连接正常，或稍后重试")

else:
    # 显示空状态
    st.info("""
    👋 你还没有添加任何持仓！
    
    在左侧输入股票信息并添加持仓，系统会自动分析你的投资组合。
    """)
    
    # 功能说明
    st.subheader("💡 功能说明")
    
    st.markdown("""
    ### 📊 投资组合管理功能
    
    - **持仓管理**: 添加/删除持仓，记录成本和数量
    - **实时收益**: 自动获取最新价格，计算盈亏
    - **收益分析**: 总收益、收益率、持仓占比
    - **可视化**: 持仓分布、盈亏图表
    - **报告生成**: 生成详细投资组合报告
    
    ### 🎓 使用示例
    
    1. 添加持仓：在左侧输入股票代码、名称、数量、成本价
    2. 查看分析：系统自动计算收益和风险
    3. 导出数据：支持导出投资组合数据
    """)
    
    # 示例持仓
    with st.expander("📝 示例持仓"):
        example_df = pd.DataFrame({
            '股票代码': ['000001', '000002', '600000'],
            '股票名称': ['平安银行', '万科A', '浦发银行'],
            '持有数量': [1000, 500, 800],
            '成本价': [12.0, 18.5, 9.5]
        })
        st.dataframe(example_df, use_container_width=True)

# 页脚
st.markdown("---")
st.caption("数据来源: AKShare | 投资有风险，入市需谨慎")

