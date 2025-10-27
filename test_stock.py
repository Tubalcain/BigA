"""
测试特定股票的数据获取
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import akshare as ak
from datetime import datetime, timedelta

def test_stock(stock_code):
    """测试股票数据获取"""
    print(f"\n测试股票: {stock_code}")
    print("=" * 60)
    
    # 测试1: 尝试获取股票基本信息
    print("\n[1] 测试获取股票基本信息...")
    try:
        df_stocks = ak.stock_info_a_code_name()
        stock_info = df_stocks[df_stocks['code'] == stock_code]
        if not stock_info.empty:
            print(f"✓ 找到股票: {stock_info.iloc[0]['name']}")
        else:
            print(f"✗ 未找到股票 {stock_code}")
    except Exception as e:
        print(f"✗ 失败: {e}")
    
    # 测试2: 尝试获取实时行情
    print("\n[2] 测试获取实时行情...")
    try:
        df_spot = ak.stock_zh_a_spot_em()
        stock_data = df_spot[df_spot['代码'] == stock_code]
        if not stock_data.empty:
            print(f"✓ 获取到实时行情:")
            print(f"  名称: {stock_data.iloc[0]['名称']}")
            print(f"  最新价: {stock_data.iloc[0]['最新价']}")
        else:
            print(f"✗ 未获取到实时行情")
    except Exception as e:
        print(f"✗ 失败: {e}")
    
    # 测试3: 尝试获取历史数据（多种方法）
    print("\n[3] 测试获取历史K线数据...")
    
    start_date = (datetime.now() - timedelta(days=30)).strftime('%Y%m%d')
    end_date = datetime.now().strftime('%Y%m%d')
    
    # 方法1: stock_zh_a_hist
    methods = [
        ("stock_zh_a_hist", lambda: ak.stock_zh_a_hist(symbol=stock_code, period="daily", start_date=start_date, end_date=end_date, adjust="")),
        ("stock_zh_a_hist (前复权)", lambda: ak.stock_zh_a_hist(symbol=stock_code, period="daily", start_date=start_date, end_date=end_date, adjust="前复权")),
    ]
    
    success = False
    for method_name, method_func in methods:
        try:
            df = method_func()
            if not df.empty and len(df) > 0:
                print(f"✓ {method_name} 成功，获取到 {len(df)} 条数据")
                print(f"  最新日期: {df.iloc[-1].to_dict()}")
                success = True
                break
        except Exception as e:
            print(f"✗ {method_name} 失败: {str(e)[:100]}")
    
    if not success:
        print("\n⚠ 所有历史数据获取方法都失败")
        print(f"可能原因:")
        print(f"1. 股票代码 {stock_code} 可能已退市")
        print(f"2. 数据源API暂时不可用")
        print(f"3. 该股票数据源不支持此股票")

def test_popular_stocks():
    """测试几个常见的股票代码"""
    print("\n" + "=" * 60)
    print("测试常用股票代码")
    print("=" * 60)
    
    popular_stocks = ['000001', '000002', '600000', '600519', '300015']
    
    for code in popular_stocks:
        test_stock(code)
        print()

if __name__ == "__main__":
    print("BigA Stock Data Source Test")
    print("=" * 60)
    
    # 测试300225
    test_stock('300225')
    
    # 测试常用股票
    test_popular_stocks()
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)

