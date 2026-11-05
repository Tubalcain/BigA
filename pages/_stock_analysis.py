"""
股票分析页面
主要功能：查看股票行情、K线图、技术指标
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

st.set_page_config(page_title="股票分析", page_icon="📈", layout="wide")

st.title("📈 股票分析")
st.markdown("---")

# 侧边栏配置
with st.sidebar:
    st.header("📊 分析配置")
    
    # 股票选择
    stock_code = st.text_input(
        "股票代码",
        value="000001",
        help="6 位代码，如 000001；也可写 000001.SZ"
    ).strip()
    
    # 数据源选择
    data_source = st.radio(
        "数据源",
        ["AKShare", "TuShare"],
        index=0
    )
    
    # 时间范围
    st.subheader("📅 时间范围")
    col1, col2 = st.columns(2)
    
    with col1:
        start_date = st.date_input(
            "开始日期",
            value=datetime.now() - timedelta(days=365),
            format="YYYY-MM-DD"
        )
    
    with col2:
        end_date = st.date_input(
            "结束日期",
            value=datetime.now(),
            format="YYYY-MM-DD"
        )
    
    # 技术指标选择
    st.subheader("🔧 技术指标")
    indicators = st.multiselect(
        "选择要显示的技术指标",
        ["MA", "MACD", "RSI", "BOLL", "KDJ"],
        default=["MA", "MACD"]
    )
    
    # 生成按钮
    analyze_btn = st.button("🚀 开始分析", type="primary", use_container_width=True)

# 主内容区域
if analyze_btn or 'show_analysis' in st.session_state:
    if analyze_btn:
        st.session_state.show_analysis = True
    
    st.subheader(f"📊 {stock_code} 股票分析")
    
    # 获取股票基本信息
    try:
        from src.data import describe_data_problems, get_active_client, outlier_count, source_switch_note
        from src.analysis.technical import TechnicalAnalyzer
        from src.visualization.charts import PlotlyChartGenerator
        
        preferred = "akshare" if data_source == "AKShare" else "tushare"
        data_obj = get_active_client(preferred)
        note = source_switch_note(preferred, data_obj)
        if note:
            st.warning(note)
            data_source = "AKShare" if getattr(data_obj, "name", "") == "akshare" else "TuShare"

        if start_date > end_date:
            st.warning("开始日期晚于结束日期，已按时间顺序交换。")
            start_date, end_date = end_date, start_date
        
        with st.spinner("正在获取数据..."):
            hist_data = data_obj.get_history_data(
                stock_code,
                start_date.strftime('%Y%m%d'),
                end_date.strftime('%Y%m%d')
            )
        
        # 调试信息
        if not hist_data.empty:
            used_source = hist_data.attrs.get("source") or data_source
            st.success(f"✓ 成功获取 {len(hist_data)} 条数据（来源: {used_source}）")
            if hist_data.attrs.get("date_range_swapped"):
                st.caption("开始/结束日期已按时间顺序交换。")
            n_out = outlier_count(hist_data)
            if n_out:
                st.caption(f"有 {n_out} 根 K 线涨跌幅异常（is_outlier），已保留。")
            with st.expander("🔍 调试信息（点击查看数据列名）"):
                st.write("数据列名:", list(hist_data.columns))
                st.write("attrs:", {k: hist_data.attrs.get(k) for k in ("source", "timezone", "issues", "ok")})
                st.write("前5行数据:")
                st.dataframe(hist_data.head())
        
        if not hist_data.empty:
            # 转换日期格式
            if 'date' in hist_data.columns:
                hist_data['date'] = pd.to_datetime(hist_data['date'])
            
            # 检查必要的列是否存在
            required_cols = ['open', 'close', 'high', 'low', 'volume']
            missing_cols = [col for col in required_cols if col not in hist_data.columns]
            
            if missing_cols:
                st.error(f"❌ 数据缺少必要的列: {missing_cols}")
                st.info(f"当前数据的列: {list(hist_data.columns)}")
                st.stop()
            
            # 计算技术指标
            if indicators:
                analyzer = TechnicalAnalyzer(hist_data)
                
                if 'MA' in indicators:
                    analyzer.calculate_ma([5, 10, 20, 60])
                if 'MACD' in indicators:
                    analyzer.calculate_macd()
                if 'RSI' in indicators:
                    analyzer.calculate_rsi()
                if 'BOLL' in indicators:
                    analyzer.calculate_bollinger()
                if 'KDJ' in indicators:
                    analyzer.calculate_kdj()
                
                hist_data = analyzer.get_data()
            
            # 显示基本统计
            st.subheader("📊 基本统计")
            col1, col2, col3, col4 = st.columns(4)
            
            col1.metric("收盘价", f"{hist_data['close'].iloc[-1]:.2f}", 
                       f"{hist_data['close'].pct_change().iloc[-1]*100:.2f}%")
            col2.metric("最高价", f"{hist_data['high'].max():.2f}", "")
            col3.metric("最低价", f"{hist_data['low'].min():.2f}", "")
            col4.metric("成交量", f"{hist_data['volume'].mean()/10000:.0f}万", "")
            
            # 绘制K线图
            st.subheader("📈 K线图")
            chart_generator = PlotlyChartGenerator()
            
            fig = chart_generator.candlestick_chart(
                hist_data,
                title=f"{stock_code} K线图 - {data_source}",
                indicators=indicators
            )
            
            st.plotly_chart(fig, use_container_width=True)
            
            # 显示数据表格
            st.subheader("📋 历史数据")
            
            col1, col2, col3 = st.columns([2, 1, 1])
            
            with col1:
                st.dataframe(
                    hist_data[['date', 'open', 'close', 'high', 'low', 'volume']].tail(20),
                    use_container_width=True
                )
            
            with col2:
                if st.button("📥 导出CSV"):
                    csv = hist_data.to_csv(index=False)
                    st.download_button(
                        label="下载数据",
                        data=csv,
                        file_name=f"{stock_code}_data.csv",
                        mime="text/csv"
                    )
            
            with col3:
                if st.button("📥 导出Excel"):
                    # 这里可以添加Excel导出功能
                    st.info("Excel导出功能开发中")

            st.subheader("💰 资金流向")
            try:
                from src.analysis.fund_flow import (
                    bias_display,
                    format_wan,
                    fund_flow_bias,
                    latest_stock_snapshot,
                    main_vs_retail,
                    price_flow_divergence,
                    unit_caption,
                )

                with st.spinner("正在获取个股资金流..."):
                    stock_flow = data_obj.get_stock_fund_flow(
                        stock_code,
                        start_date.strftime("%Y%m%d"),
                        end_date.strftime("%Y%m%d"),
                    )
                    north = data_obj.get_northbound_flow()
                stock_bias = fund_flow_bias(
                    north_df=north,
                    stock_flow=stock_flow,
                    price_df=hist_data,
                )
                view = bias_display(stock_bias)
                st.markdown(f"**{view['title']}**")
                st.caption(view["disclaimer"])
                b1, b2, b3 = st.columns(3)
                b1.metric("倾向", view["bias"])
                b2.metric("信心", view["confidence_label"], delta=view["confidence_pct"])
                b3.metric("软评分", view["score_delta"])
                for line in view["evidence"][:6]:
                    st.caption("· " + line)
                if view["reading"]:
                    st.caption(view["reading"])
                if stock_flow is not None and not stock_flow.empty:
                    snap = latest_stock_snapshot(stock_flow)
                    vs = main_vs_retail(stock_flow)
                    f1, f2, f3, f4 = st.columns(4)
                    f1.metric("最新主力净流入", format_wan(snap.get("latest_main")))
                    f2.metric("近5日主力", format_wan(snap.get("sum_5d")))
                    f3.metric("近10日主力", format_wan(snap.get("sum_10d")))
                    f4.metric("小单(散户)", format_wan(vs.get("retail_net_inflow")))
                    if vs.get("note"):
                        st.caption(vs["note"])
                    y_cols = [
                        c
                        for c in ["main_net_inflow", "super_large_net", "large_net", "small_net"]
                        if c in stock_flow.columns
                    ]
                    if y_cols:
                        fig_flow = chart_generator.line_chart(
                            stock_flow, "date", y_cols, title=f"{stock_code} 主力资金"
                        )
                        st.plotly_chart(fig_flow, use_container_width=True)
                    diverged = price_flow_divergence(hist_data, stock_flow)
                    if diverged is not None and not diverged.empty and diverged["divergence"].any():
                        st.markdown("**价资背离（近窗口）**")
                        hits = diverged[diverged["divergence"]].tail(8)
                        st.dataframe(hits, use_container_width=True, hide_index=True)
                    st.caption(unit_caption(stock_flow))
                else:
                    st.info("该股票暂无主力资金序列（接口限流、停牌或源不支持时会降级）。")
                    msg = describe_data_problems(stock_flow)
                    if msg:
                        st.caption(msg)
            except Exception as flow_exc:
                st.info(f"资金流向暂不可用: {flow_exc}")
            
        else:
            st.error(f"❌ 未能获取股票 {stock_code} 的数据")
            msg = describe_data_problems(hist_data)
            if msg:
                st.caption(msg)
            
            with st.expander("🆘 可能的原因和解决方案"):
                st.markdown("""
                ### 可能的原因：
                1. **股票代码错误** - 请确认是6位数字代码
                2. **该股票可能已退市** - 某些退市股票无法获取数据
                3. **数据源API暂时不可用** - 请稍后重试
                4. **网络连接问题** - 请检查网络连接
                
                ### 解决方案：
                - 尝试使用热门股票代码：
                  - **000001** (平安银行)
                  - **000002** (万科A)
                  - **600000** (浦发银行)
                  - **600519** (贵州茅台)
                - 检查股票代码是否为6位数字
                - 稍后再试
                
                ### 测试数据源：
                可以运行 `python examples/test_data_source.py` 来测试数据源是否可用
                """)
    
    except Exception as e:
        st.error(f"❌ 获取数据时发生错误: {str(e)}")
        st.warning("💡 提示：")
        
        with st.expander("查看详细错误信息"):
            st.code(str(e))
        
        st.info("""
        **尝试以下解决方案：**
        1. 检查股票代码格式是否正确（6位数字）
        2. 尝试使用其他数据源（AKShare/TuShare）
        3. 稍后重试
        4. 运行测试脚本：`python examples/test_data_source.py`
        """)

else:
    # 显示欢迎信息
    st.info("""
    👋 欢迎使用股票分析功能！
    
    在左侧配置股票代码、时间范围和技术指标，然后点击"开始分析"按钮。
    """)
    
    # 示例
    st.subheader("📝 使用示例")
    example_code = st.code("""
# 使用示例
stock_code = "000001"  # 平安银行
start_date = "2023-01-01"
end_date = "2024-12-01"
indicators = ["MA", "MACD", "RSI"]
    """, language='python')
    
    st.markdown("""
    ### 📚 热门股票代码参考
    
    **银行股：**
    - 000001: 平安银行
    - 600000: 浦发银行
    - 601398: 工商银行
    
    **地产股：**
    - 000002: 万科A
    - 000069: 华侨城A
    
    **白酒股：**
    - 600519: 贵州茅台
    - 000858: 五粮液
    
    **创业板：**
    - 300015: 爱尔眼科
    - 300059: 东方财富
    """)

# 页脚
st.markdown("---")
st.caption("数据来源: AKShare / TuShare（可回退） | 更新时间: " + datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

