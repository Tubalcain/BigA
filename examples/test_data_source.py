"""
测试数据源模块
运行此脚本测试AKShare和TuShare数据源
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data.akshare_data import AKShareData, AKShareIndicator
from src.data.tushare_data import TuShareData


def test_akshare():
    """测试AKShare数据源"""
    print("=" * 60)
    print("测试AKShare数据源")
    print("=" * 60)
    
    ak_data = AKShareData()
    
    # 测试1: 获取股票列表
    print("\n[测试1] 获取股票列表...")
    try:
        stocks = ak_data.get_stock_list("深圳交易所")
        print(f"✓ 成功获取 {len(stocks)} 只深圳股票")
        print(f"前5只: {stocks.head()}")
    except Exception as e:
        print(f"✗ 失败: {e}")
    
    # 测试2: 获取实时行情
    print("\n[测试2] 获取实时行情...")
    try:
        quote = ak_data.get_realtime_quote("000001")
        if not quote.empty:
            print(f"✓ 成功获取平安银行实时行情")
            print(quote)
        else:
            print("✗ 未获取到数据")
    except Exception as e:
        print(f"✗ 失败: {e}")
    
    # 测试3: 获取历史数据
    print("\n[测试3] 获取历史数据...")
    try:
        hist = ak_data.get_history_data("000001", "20240101", "20241201")
        print(f"✓ 成功获取 {len(hist)} 条历史数据")
        print(hist.tail())
    except Exception as e:
        print(f"✗ 失败: {e}")
    
    # 测试4: 计算技术指标
    print("\n[测试4] 计算技术指标...")
    try:
        hist = ak_data.get_history_data("000001", "20240101", "20241201")
        if not hist.empty:
            indicator = AKShareIndicator()
            hist_with_indicators = (indicator
                                   .calculate_ma(hist, [5, 10, 20])
                                   .calculate_macd()
                                   .calculate_rsi()
                                   .get_data())
            print(f"✓ 成功计算技术指标")
            print(hist_with_indicators[['date', 'close', 'MA5', 'MA10', 'MACD', 'RSI']].tail())
    except Exception as e:
        print(f"✗ 失败: {e}")
    
    print("\n" + "=" * 60)
    print("AKShare测试完成")
    print("=" * 60)


def test_tushare():
    """测试TuShare数据源"""
    print("\n" + "=" * 60)
    print("测试TuShare数据源")
    print("=" * 60)
    
    tushare = TuShareData()
    
    if not tushare.is_available():
        print("⚠ TuShare未配置token，跳过测试")
        print("提示: 设置环境变量 TUSHARE_TOKEN=your_token")
        return
    
    # 测试1: 获取基本信息
    print("\n[测试1] 获取股票基本信息...")
    try:
        info = tushare.get_basic_info("000001")
        if info:
            print(f"✓ 成功获取平安银行基本信息")
            print(info)
    except Exception as e:
        print(f"✗ 失败: {e}")
    
    # 测试2: 获取历史数据
    print("\n[测试2] 获取历史数据...")
    try:
        hist = tushare.get_daily_data("000001", "20240101", "20241201")
        if not hist.empty:
            print(f"✓ 成功获取 {len(hist)} 条历史数据")
            print(hist.tail())
    except Exception as e:
        print(f"✗ 失败: {e}")
    
    # 测试3: 获取基本面数据
    print("\n[测试3] 获取基本面数据...")
    try:
        basic = tushare.get_daily_basic("000001", "20240101", "20241201")
        if not basic.empty:
            print(f"✓ 成功获取基本面数据")
            print(basic.tail())
    except Exception as e:
        print(f"✗ 失败: {e}")
    
    print("\n" + "=" * 60)
    print("TuShare测试完成")
    print("=" * 60)


def main():
    """主函数"""
    print("\n🚀 开始测试数据源模块\n")
    
    # 测试AKShare
    test_akshare()
    
    # 测试TuShare
    test_tushare()
    
    print("\n" + "=" * 60)
    print("✨ 所有测试完成")
    print("=" * 60)


if __name__ == "__main__":
    main()

