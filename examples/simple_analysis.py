"""
简单的股票分析示例
演示如何使用BigA Stock Analysis进行股票分析
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data.akshare_data import AKShareData, AKShareIndicator
from src.analysis.technical import TechnicalAnalyzer
from src.visualization.charts import PlotlyChartGenerator
from datetime import datetime


def simple_stock_analysis(stock_code="000001"):
    """
    简单的股票分析
    
    Args:
        stock_code: 股票代码
    """
    print(f"\n📊 开始分析股票: {stock_code}")
    print("=" * 60)
    
    # 1. 获取数据
    print("步骤1: 获取历史数据...")
    ak_data = AKShareData()
    hist = ak_data.get_history_data(stock_code, "20240101", "20241201")
    
    if hist.empty:
        from src.data import describe_data_problems

        print("✗ 未能获取数据")
        print("  ", describe_data_problems(hist))
        return
    
    print(f"✓ 获取到 {len(hist)} 条历史数据")
    
    # 2. 计算技术指标
    print("\n步骤2: 计算技术指标...")
    indicator = AKShareIndicator()
    hist_with_indicators = (indicator
                           .calculate_ma(hist, [5, 10, 20, 60])
                           .calculate_macd()
                           .calculate_rsi()
                           .calculate_bollinger()
                           .get_data())
    
    print("✓ 技术指标计算完成")
    
    # 3. 显示基本统计
    print("\n步骤3: 基本统计信息")
    print(f"股票代码: {stock_code}")
    print(f"最新收盘价: {hist_with_indicators['close'].iloc[-1]:.2f}")
    print(f"最高价: {hist_with_indicators['high'].max():.2f}")
    print(f"最低价: {hist_with_indicators['low'].min():.2f}")
    print(f"涨跌幅: {(hist_with_indicators['close'].iloc[-1] / hist_with_indicators['close'].iloc[-2] - 1) * 100:.2f}%")
    
    # 4. 显示技术指标
    print("\n步骤4: 技术指标值")
    latest = hist_with_indicators.iloc[-1]
    print(f"MA5: {latest.get('MA5', 'N/A'):.2f}")
    print(f"MA10: {latest.get('MA10', 'N/A'):.2f}")
    print(f"RSI: {latest.get('RSI', 'N/A'):.2f}")
    print(f"MACD: {latest.get('MACD', 'N/A'):.2f}")
    
    # 5. 生成图表
    print("\n步骤5: 生成K线图...")
    chart_gen = PlotlyChartGenerator()
    fig = chart_gen.candlestick_chart(
        hist_with_indicators,
        title=f"{stock_code} K线图",
        indicators=['MA', 'MACD', 'RSI']
    )
    
    # 注意: 需要plotly环境才能显示图表
    # fig.show()
    print("✓ K线图已生成")
    
    print("\n" + "=" * 60)
    print("✅ 分析完成")
    print("=" * 60)
    
    return hist_with_indicators


def main():
    """主函数"""
    print("🚀 BigA Stock Analysis - 简单示例\n")
    
    # 分析平安银行
    result = simple_stock_analysis("000001")
    
    if result is not None:
        print("\n📋 数据预览（最近5天）:")
        print(result[['date', 'open', 'close', 'high', 'low', 'volume']].tail())


if __name__ == "__main__":
    main()

