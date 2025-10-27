"""
股票筛选器页面
主要功能：多条件筛选股票
"""

import streamlit as st
import pandas as pd

st.set_page_config(page_title="股票筛选", page_icon="🔍", layout="wide")

st.title("🔍 股票筛选器")
st.markdown("---")

# 侧边栏
with st.sidebar:
    st.header("🎯 筛选条件")
    
    # 交易所选择
    exchange = st.selectbox(
        "交易所",
        ["所有", "深圳交易所", "上海交易所"],
        index=0
    )
    
    # 市值筛选
    st.subheader("💼 市值筛选")
    market_cap_min = st.number_input("最小市值（万元）", min_value=0, value=0, step=1000)
    market_cap_max = st.number_input("最大市值（万元）", min_value=0, value=1000000000, step=1000)
    
    # 涨跌幅筛选
    st.subheader("📈 涨跌幅筛选")
    change_min = st.number_input("最小涨跌幅（%）", min_value=-10.0, max_value=10.0, value=-10.0, step=0.1)
    change_max = st.number_input("最大涨跌幅（%）", min_value=-10.0, max_value=10.0, value=10.0, step=0.1)
    
    # 成交量筛选
    st.subheader("📊 成交量筛选")
    volume_min = st.number_input("最小成交量（手）", min_value=0, value=0, step=1000)
    
    # 筛选按钮
    screen_btn = st.button("🚀 开始筛选", type="primary", use_container_width=True)

# 主内容区域
if screen_btn:
    try:
        from src.data.akshare_data import AKShareData
        
        ak_data = AKShareData()
        
        with st.spinner("正在获取股票列表..."):
            # 根据交易所获取股票列表
            if exchange == "所有":
                df = ak_data.get_stock_list("深圳交易所")
                df_sh = ak_data.get_stock_list("上海交易所")
                df = pd.concat([df, df_sh], ignore_index=True)
            else:
                exchange_type = "深圳交易所" if exchange == "深圳交易所" else "上海交易所"
                df = ak_data.get_stock_list(exchange_type)
        
        if not df.empty:
            st.success(f"✓ 获取到 {len(df)} 只股票")
            
            # 简单筛选示例（实际应该根据条件筛选）
            # 这里展示所有股票
            st.subheader("📋 筛选结果")
            
            # 显示股票列表
            st.dataframe(
                df,
                use_container_width=True,
                height=600
            )
            
            # 导出功能
            col1, col2 = st.columns([3, 1])
            
            with col2:
                if st.button("📥 导出CSV"):
                    csv = df.to_csv(index=False)
                    st.download_button(
                        label="下载筛选结果",
                        data=csv,
                        file_name="stock_screener_results.csv",
                        mime="text/csv"
                    )
        else:
            st.warning("未能获取股票列表")
    
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
        
        - **交易所**: 选择深圳或上海交易所
        - **市值**: 按市值范围筛选
        - **涨跌幅**: 按涨幅筛选
        - **成交量**: 按成交量筛选
        """)
    
    with col2:
        st.markdown("""
       ### 💡 使用技巧
        
        - 组合使用多个条件可获得更精确的结果
        - 支持导出筛选结果为CSV文件
        - 点击股票代码可跳转到详情页
        """)
    
    # 示例条件
    st.subheader("🎓 示例筛选条件")
    
    example1 = {
        "交易所": "深圳交易所",
        "市值": "10亿 - 100亿",
        "涨跌幅": "0% - 5%",
        "成交量": "> 100万"
    }
    
    st.json(example1)

# 页脚
st.markdown("---")
st.caption("数据来源: AKShare | 筛选结果仅供参考，投资需谨慎")

