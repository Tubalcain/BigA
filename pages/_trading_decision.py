"""
交易决策看板 - 专业增强版
完整的交易分析工具箱
资深A股分析师的专业工具
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import numpy as np

st.set_page_config(page_title="交易决策", page_icon="📊", layout="wide")

st.title("📊 交易决策看板（专业增强版）")
st.caption("资深A股分析师的完整工具箱 - 多维度信号分析 + 仓位管理 + 止损止盈")
st.markdown("---")

# 侧边栏
with st.sidebar:
    st.header("⚙️ 分析配置")
    
    # 股票选择
    stock_code = st.text_input(
        "股票代码",
        value="000001",
        help="6 位代码，如 000001；也可写 000001.SZ"
    ).strip()
    
    # 时间周期
    st.subheader("📅 时间周期")
    period = st.select_slider(
        "回看周期",
        options=[30, 60, 90, 120, 180, 365],
        value=120
    )
    
    time_frame = st.selectbox(
        "K线周期",
        ["日线", "周线", "月线"],
        index=0
    )
    
    # 账户设置
    st.subheader("💰 账户设置")
    account_size = st.number_input(
        "账户总资金（元）",
        min_value=10000,
        value=100000,
        step=10000
    )
    
    risk_percent = st.slider(
        "单笔风险（%）",
        min_value=1,
        max_value=5,
        value=2,
        help="建议2%，保守型1%，积极型3-5%"
    )
    
    # 风险偏好
    st.subheader("⚖️ 风险偏好")
    risk_tolerance = st.selectbox(
        "您的风险承受能力",
        ["保守型", "稳健型", "积极型"],
        index=1
    )
    
    # 高级选项
    with st.expander("🎛️ 高级选项"):
        show_buy_sell_points = st.checkbox("显示买卖点标记", value=True)
        show_volume_profile = st.checkbox("显示成交量分析", value=True)
        show_stop_loss = st.checkbox("显示止损止盈", value=True)
        show_momentum = st.checkbox("显示动量分析", value=True)
        
        # 分析引擎选择
        analysis_mode = st.radio(
            "分析引擎",
            ["🌟 优化版（推荐）", "原版"],
            help="优化版考虑了趋势、位置、成交量等多个维度，建议更强"
        )
    
    # 分析按钮
    analyze_btn = st.button("🚀 开始分析", type="primary", use_container_width=True)
    
    # 推荐股票
    st.markdown("---")
    st.subheader("📌 热门股票")
    popular_stocks = {
        "000001": "平安银行",
        "600519": "贵州茅台", 
        "000002": "万科A",
        "600000": "浦发银行"
    }
    for code, name in popular_stocks.items():
        if st.button(f"{code} - {name}", key=f"stock_{code}", use_container_width=True):
            st.session_state.stock_code = code
            st.rerun()

# 主内容区域
if analyze_btn or 'analyze' in st.session_state:
    if analyze_btn:
        st.session_state.analyze = True
    
    try:
        from src.data import describe_data_problems, get_active_client, outlier_count, source_switch_note
        from src.analysis.trading_signals import TradingSignalAnalyzer
        from src.analysis.trading_signals_optimized import OptimizedTradingSignalAnalyzer
        from src.analysis.advanced_trading import AdvancedTradingAnalyzer
        from src.analysis.technical import TechnicalAnalyzer
        from src.visualization.charts import PlotlyChartGenerator
        
        # 获取数据
        with st.spinner("正在获取数据..."):
            preferred = st.session_state.get("data_source", "akshare")
            ak_data = get_active_client(preferred)
            note = source_switch_note(preferred, ak_data)
            if note:
                st.caption(note)
            
            end_date = datetime.now()
            start_date = end_date - timedelta(days=period)
            
            period_map = {"日线": "daily", "周线": "weekly", "月线": "monthly"}
            hist_data = ak_data.get_history_data(
                stock_code,
                start_date.strftime('%Y%m%d'),
                end_date.strftime('%Y%m%d'),
                period=period_map.get(time_frame, "daily"),
            )
        
        if not hist_data.empty:
            n_out = outlier_count(hist_data)
            if n_out:
                st.caption(f"有 {n_out} 根 K 线涨跌幅异常（is_outlier），已保留。")
            # 标准化数据
            if 'date' in hist_data.columns:
                hist_data['date'] = pd.to_datetime(hist_data['date'])
            
            # 技术分析
            tech_analyzer = TechnicalAnalyzer(hist_data)
            hist_data = (tech_analyzer
                        .calculate_ma([5, 10, 20, 60])
                        .calculate_macd()
                        .calculate_rsi()
                        .get_data())
            
            # 选择分析引擎
            use_optimized = '优化版' in analysis_mode
            
            if use_optimized:
                # 使用优化版分析引擎
                signal_analyzer = OptimizedTradingSignalAnalyzer(hist_data)
                recommendation = signal_analyzer.get_optimized_recommendation()
            else:
                # 使用原版分析引擎
                signal_analyzer = TradingSignalAnalyzer(hist_data)
                recommendation = signal_analyzer.get_trading_recommendation()
            
            # 高级分析
            advanced_analyzer = AdvancedTradingAnalyzer(hist_data, stock_code)
            trading_plan = advanced_analyzer.generate_trading_plan(
                hist_data['close'].iloc[-1],
                account_size
            )
            momentum = advanced_analyzer.calculate_momentum_score()
            
            # 1. 核心交易建议
            st.markdown("---")
            
            if use_optimized:
                st.subheader("💡 核心交易建议（优化版）")
                
                # 显示分析引擎
                st.info(f"✨ 使用优化版分析引擎 - 综合考虑趋势、位置、成交量等因素")
                
                # 显示分析原因
                if 'reason' in recommendation:
                    st.markdown(f"**建议原因**：{recommendation['reason']}")
                
                # 显示分析说明
                if 'analysis_notes' in recommendation:
                    with st.expander("📋 详细分析说明"):
                        for note in recommendation['analysis_notes']:
                            st.markdown(f"- {note}")
            else:
                st.subheader("💡 核心交易建议")
            
            col1, col2, col3, col4, col5 = st.columns(5)
            
            with col1:
                action = recommendation['action']
                if action == 'BUY':
                    st.metric("推荐动作", "🟢 买入", delta="积极信号", delta_color="normal")
                elif action == 'SELL':
                    st.metric("推荐动作", "🔴 卖出", delta="负面信号", delta_color="inverse")
                else:
                    st.metric("推荐动作", "🟡 持有", delta="中性信号")
            
            with col2:
                score = recommendation['score']
                st.metric("综合评分", f"{score:.1f}", delta=f"{'+' if score >= 0 else ''}{score:.1f}分")
            
            with col3:
                confidence = recommendation['confidence']
                st.metric("信心度", confidence)
            
            with col4:
                momentum_pct = momentum['percentage']
                st.metric("动量得分", f"{momentum['score']}/15", 
                         delta=f"{momentum_pct:.1f}%")
            
            with col5:
                trend = trading_plan['trend']
                st.metric("趋势状态", trend)

            try:
                from src.analysis.fund_flow import format_wan, northbound_regime, stock_flow_notes

                end_key = end_date.strftime("%Y%m%d")
                start_key = start_date.strftime("%Y%m%d")
                stock_flow = ak_data.get_stock_fund_flow(stock_code, start_key, end_key)
                north = ak_data.get_northbound_flow()
                notes = stock_flow_notes(stock_flow, north)
                if notes or (north is not None and not north.empty):
                    st.markdown("##### 资金面")
                    if stock_flow is not None and not stock_flow.empty and "main_net_inflow" in stock_flow.columns:
                        latest_main = stock_flow["main_net_inflow"].iloc[-1]
                        sum_5 = pd.to_numeric(stock_flow["main_net_inflow"].tail(5), errors="coerce").sum()
                        fc1, fc2, fc3 = st.columns(3)
                        fc1.metric("主力净流入", format_wan(latest_main))
                        fc2.metric("近5日主力", format_wan(sum_5))
                        regime = northbound_regime(north) if north is not None else {}
                        fc3.metric("北向5日", format_wan(regime.get("window_sum")))
                    if notes:
                        st.caption("；".join(notes))
            except Exception:
                pass
            
            # 2. 止损止盈建议
            if show_stop_loss:
                st.markdown("---")
                st.subheader("🛡️ 止损止盈建议")
                
                current_price = hist_data['close'].iloc[-1]
                
                # 使用优化版止损计算
                if use_optimized and hasattr(signal_analyzer, 'calculate_optimized_stop_loss'):
                    stop_loss_calc = signal_analyzer.calculate_optimized_stop_loss()
                    # 格式化优化版数据
                    stop_loss_data = {
                        'stop_loss': {
                            'long': stop_loss_calc['stop_loss'],
                            'distance_pct': stop_loss_calc['stop_loss_pct']
                        },
                        'support': 0,  # 优化版暂时没有
                        'resistance': 0
                    }
                else:
                    stop_loss_data = advanced_analyzer.calculate_stop_loss_profit(current_price)
                
                col1, col2, col3, col4 = st.columns(4)
                
                col1.metric("当前价格", f"{current_price:.2f}")
                
                # 检查数据格式
                if isinstance(stop_loss_data.get('stop_loss'), dict):
                    col2.metric("止损位", f"{stop_loss_data['stop_loss']['long']:.2f}", 
                               delta=f"-{stop_loss_data['stop_loss']['distance_pct']:.2f}%")
                else:
                    stop_loss_val = stop_loss_data.get('stop_loss', 0)
                    col2.metric("止损位", f"{stop_loss_val:.2f}")
                
                if 'take_profit' in stop_loss_data:
                    col3.metric("止盈位1", f"{stop_loss_data['take_profit']['level_1']:.2f}",
                               delta=f"+{stop_loss_data['take_profit']['distance_pct_1']:.2f}%")
                    col4.metric("支撑位", f"{stop_loss_data['support']:.2f}")
                else:
                    col3.metric("止盈位", "计算中")
                    col4.metric("支撑位", "-")
            
            # 3. 仓位管理建议
            st.markdown("---")
            st.subheader("📊 仓位管理建议")
            
            position = trading_plan['position']
            volume_profile = advanced_analyzer.analyze_volume_profile()
            
            col1, col2, col3, col4 = st.columns(4)
            
            col1.metric("建议股数", f"{position['suggested_shares']:,}股")
            col2.metric("仓位市值", f"¥{position['position_value']:,.0f}")
            col3.metric("仓位占比", f"{position['position_pct']:.1f}%")
            col4.metric("风险等级", position['risk_level'])
            
            # 4. 成交量分析
            if show_volume_profile:
                st.markdown("---")
                st.subheader("📈 成交量分析")
                
                col1, col2, col3 = st.columns(3)
                col1.metric("成交量比率", f"{volume_profile['volume_ratio']:.2f}")
                col2.metric("成交状态", volume_profile['status'])
                col3.metric("说明", volume_profile['description'])
            
            # 5. 买卖点标记
            if show_buy_sell_points:
                buy_sell_points = advanced_analyzer.get_buy_sell_points()
                
                st.markdown("---")
                st.subheader("🎯 买卖点分析")
                
                col1, col2 = st.columns(2)
                
                with col1:
                    st.markdown("#### ✅ 买入点")
                    if buy_sell_points['buy']:
                        df_buy = pd.DataFrame(buy_sell_points['buy'])
                        st.dataframe(df_buy, use_container_width=True)
                    else:
                        st.info("当前无明显买入点")
                
                with col2:
                    st.markdown("#### ⚠️ 卖出点")
                    if buy_sell_points['sell']:
                        df_sell = pd.DataFrame(buy_sell_points['sell'])
                        st.dataframe(df_sell, use_container_width=True)
                    else:
                        st.info("当前无明显卖出点")
            
            # 6. K线图 + 买卖点
            st.markdown("---")
            st.subheader("📊 技术分析图表")
            
            # 创建带买卖点标记的图表
            fig = make_subplots(
                rows=2, cols=1,
                shared_xaxes=True,
                row_heights=[0.7, 0.3],
                vertical_spacing=0.05,
                subplot_titles=(f"{stock_code} K线图（含买卖点）", "技术指标"),
                specs=[[{"secondary_y": False}],
                       [{"secondary_y": False}]]
            )
            
            # K线图
            fig.add_trace(
                go.Candlestick(
                    x=hist_data['date'],
                    open=hist_data['open'],
                    high=hist_data['high'],
                    low=hist_data['low'],
                    close=hist_data['close'],
                    name='K线'
                ),
                row=1, col=1
            )
            
            # 均线
            for ma in [5, 10, 20, 60]:
                if f'MA{ma}' in hist_data.columns:
                    fig.add_trace(
                        go.Scatter(
                            x=hist_data['date'],
                            y=hist_data[f'MA{ma}'],
                            name=f'MA{ma}',
                            line=dict(width=1.5)
                        ),
                        row=1, col=1
                    )
            
            # 买卖点标记
            if show_buy_sell_points:
                buy_points = advanced_analyzer.get_buy_sell_points()
                
                # 买入点
                if buy_points['buy']:
                    buy_df = pd.DataFrame(buy_points['buy'])
                    for idx, row in buy_df.iterrows():
                        fig.add_trace(
                            go.Scatter(
                                x=[row['date']],
                                y=[row['price']],
                                mode='markers',
                                marker=dict(
                                    symbol='triangle-up',
                                    size=15,
                                    color='green',
                                    line=dict(width=2, color='darkgreen')
                                ),
                                name='买入点',
                                showlegend=idx==0
                            ),
                            row=1, col=1
                        )
                
                # 卖出点
                if buy_points['sell']:
                    sell_df = pd.DataFrame(buy_points['sell'])
                    for idx, row in sell_df.iterrows():
                        fig.add_trace(
                            go.Scatter(
                                x=[row['date']],
                                y=[row['price']],
                                mode='markers',
                                marker=dict(
                                    symbol='triangle-down',
                                    size=15,
                                    color='red',
                                    line=dict(width=2, color='darkred')
                                ),
                                name='卖出点',
                                showlegend=idx==0
                            ),
                            row=1, col=1
                        )
            
            # MACD
            if 'DIF' in hist_data.columns:
                fig.add_trace(
                    go.Scatter(x=hist_data['date'], y=hist_data['DIF'], 
                              name='DIF', line=dict(color='blue')),
                    row=2, col=1
                )
                fig.add_trace(
                    go.Scatter(x=hist_data['date'], y=hist_data['DEA'], 
                              name='DEA', line=dict(color='orange')),
                    row=2, col=1
                )
                fig.add_trace(
                    go.Bar(x=hist_data['date'], y=hist_data['MACD'], 
                           name='MACD', marker_color='gray'),
                    row=2, col=1
                )
            
            fig.update_layout(
                title=f"{stock_code} 完整技术分析",
                xaxis_rangeslider_visible=False,
                height=800,
                hovermode='x unified',
                template='plotly_white'
            )
            
            st.plotly_chart(fig, use_container_width=True)
            
            # 7. 综合建议
            st.markdown("---")
            st.subheader("💼 完整交易计划")
            
            with st.expander("📋 查看详细计划", expanded=True):
                col1, col2 = st.columns(2)
                
                with col1:
                    st.markdown("### 操作建议")
                    st.markdown(f"**推荐动作**：{recommendation['recommendation']}")
                    st.markdown(f"**趋势方向**：{trend}")
                    st.markdown(f"**动量得分**：{momentum['score']}/15 ({momentum['percentage']:.1f}%)")
                    st.markdown(f"**信心度**：{recommendation['confidence']}")
                    st.markdown(f"**综合评分**：{recommendation['score']}分")
                
                with col2:
                    st.markdown("### 仓位建议")
                    st.markdown(f"**建议股数**：{position['suggested_shares']}股")
                    st.markdown(f"**仓位占比**：{position['position_pct']:.1f}%")
                    st.markdown(f"**风险等级**：{position['risk_level']}")
                    st.markdown(f"**止损比例**：{position['stop_loss_pct']:.2f}%")
                    st.markdown(f"**风险金额**：¥{position['risk_amount']:,.0f}")
            
            st.info(f"""
            **根据您的风险偏好（{risk_tolerance}）的建议**：
            
            1. **操作方向**：{recommendation['recommendation']}
            2. **建议仓位**：{position['position_pct']:.1f}%（{position['suggested_shares']}股）
            3. **止损位**：{stop_loss_data['stop_loss']['long']:.2f}（跌幅{stop_loss_data['stop_loss']['distance_pct']:.2f}%）
            4. **止盈位**：{stop_loss_data['take_profit']['level_1']:.2f}（涨幅{stop_loss_data['take_profit']['distance_pct_1']:.2f}%）
            
            **重要提醒**：
            - 本分析仅供参考，不构成投资建议
            - 投资有风险，入市需谨慎
            - 严格执行止损纪律
            - 控制仓位，分散风险
            """)
            
        else:
            st.error(f"❌ 未能获取股票 {stock_code} 的数据")
            msg = describe_data_problems(hist_data)
            if msg:
                st.caption(msg)
            st.info("💡 提示：请检查股票代码是否为 6 位数字（也可写 000001.SZ）")
    
    except Exception as e:
        st.error(f"❌ 分析过程中发生错误: {str(e)}")
        with st.expander("查看详细错误信息"):
            st.code(str(e))

else:
    # 显示欢迎信息
    st.info("""
    👋 欢迎使用交易决策看板 - 专业增强版！
    
    **完整功能**：
    - 📊 多维度买卖信号分析
    - 🎯 精确买卖点标记
    - 🛡️ 止损止盈建议
    - 📈 成交量分析
    - 🚀 动量得分计算
    - 💰 仓位管理建议
    
    **在左侧配置参数，点击"开始分析"开始使用。**
    """)
    
    # 功能演示
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### ✨ 核心功能")
        st.markdown("""
        1. **智能信号识别**
           - MA/MACD/RSI综合判断
           - 自动识别金叉死叉
           - 超买超卖检测
        
        2. **买卖点标注**
           - 在K线图上标注买卖点
           - 显示信号强度和类型
           - 历史信号回顾
        
        3. **止损止盈系统**
           - 自动计算止损位
           - 动态调整止盈位
           - 风险等级提示
        """)
    
    with col2:
        st.markdown("### 🎓 专业工具")
        st.markdown("""
        1. **仓位管理**
           - 根据风险偏好计算仓位
           - 单笔风险控制
           - 账户资金管理
        
        2. **成交量分析**
           - 放量缩量识别
           - 成交状态判断
           - 量价关系分析
        
        3. **动量评分**
           - 15分制动量评分
           - 多指标综合打分
           - 趋势强度量化
        """)
    
    st.markdown("---")
    st.subheader("📚 使用指南")
    
    st.markdown("""
    1. **输入股票代码**：如 000001（平安银行）
    2. **设置分析周期**：建议120天
    3. **配置账户**：输入账户总资金
    4. **选择风险偏好**：保守/稳健/积极
    5. **点击分析**：获得完整交易建议
    """)
    
    st.markdown("---")
    st.warning("""
    ⚠️ 免责声明：
    
    本系统提供的分析仅供参考，不构成任何投资建议。
    投资有风险，入市需谨慎。
    请根据自身风险承受能力和投资目标，做出理性决策。
    """)

