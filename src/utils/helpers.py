"""
辅助函数模块
提供各种工具函数
"""

import pandas as pd
from datetime import datetime, timedelta
import re


def format_number(num, decimals=2):
    """
    格式化数字
    
    Args:
        num: 数字
        decimals: 小数位数
        
    Returns:
        str: 格式化后的字符串
    """
    try:
        if num >= 100000000:
            return f"{num/100000000:.{decimals}f}亿"
        elif num >= 10000:
            return f"{num/10000:.{decimals}f}万"
        else:
            return f"{num:.{decimals}f}"
    except:
        return str(num)


def validate_stock_code(code):
    """
    验证股票代码格式
    
    Args:
        code: 股票代码
        
    Returns:
        bool: 是否为有效代码
    """
    if not code:
        return False
    
    # 移除空格
    code = code.strip()
    
    # 检查是否为6位数字
    if re.match(r'^[0-9]{6}$', code):
        # 深圳股票：00xxxx, 30xxxx
        if code.startswith('00') or code.startswith('30'):
            return True
        # 上海股票：60xxxx, 68xxxx
        elif code.startswith('60') or code.startswith('68'):
            return True
    
    return False


def get_stock_name(stock_code):
    """
    获取股票名称（简化版，实际应该从数据库查询）
    
    Args:
        stock_code: 股票代码
        
    Returns:
        str: 股票名称
    """
    # 这里应该从数据库或API获取
    # 暂时返回示例名称
    sample_names = {
        '000001': '平安银行',
        '000002': '万科A',
        '600000': '浦发银行',
        '600519': '贵州茅台',
        '000858': '五粮液',
    }
    
    return sample_names.get(stock_code, '未知股票')


def get_exchange_from_code(code):
    """
    从股票代码判断交易所
    
    Args:
        code: 股票代码
        
    Returns:
        str: 交易所名称
    """
    if code.startswith('00') or code.startswith('30'):
        return '深圳交易所'
    elif code.startswith('60') or code.startswith('68'):
        return '上海交易所'
    else:
        return '未知'


def format_date(date_str, format='%Y-%m-%d'):
    """
    格式化日期
    
    Args:
        date_str: 日期字符串
        format: 输出格式
        
    Returns:
        str: 格式化后的日期
    """
    try:
        if isinstance(date_str, str):
            # 尝试解析多种格式
            formats = ['%Y%m%d', '%Y-%m-%d', '%Y/%m/%d']
            for fmt in formats:
                try:
                    dt = datetime.strptime(date_str, fmt)
                    return dt.strftime(format)
                except:
                    continue
        elif isinstance(date_str, (datetime, pd.Timestamp)):
            return date_str.strftime(format)
        
        return str(date_str)
    except:
        return str(date_str)


def get_recent_trading_days(days=5):
    """
    获取最近N个交易日（模拟，实际应该从交易日历获取）
    
    Args:
        days: 天数
        
    Returns:
        list: 交易日列表
    """
    # 简化实现，实际应该从交易日历API获取
    today = datetime.now()
    trading_days = []
    
    count = 0
    current_date = today
    
    while count < days:
        # 跳过周末（这里简化处理）
        if current_date.weekday() < 5:  # 周一到周五
            trading_days.append(current_date.strftime('%Y-%m-%d'))
            count += 1
        current_date -= timedelta(days=1)
    
    return trading_days


def parse_date_range(start_date, end_date):
    """
    解析日期范围
    
    Args:
        start_date: 开始日期
        end_date: 结束日期
        
    Returns:
        tuple: (start_date, end_date)
    """
    try:
        # 转换为datetime对象
        if isinstance(start_date, str):
            start_date = datetime.strptime(start_date, '%Y-%m-%d')
        if isinstance(end_date, str):
            end_date = datetime.strptime(end_date, '%Y-%m-%d')
        
        # 如果开始日期晚于结束日期，交换
        if start_date > end_date:
            start_date, end_date = end_date, start_date
        
        return start_date, end_date
    except:
        return None, None


def calculate_days_between(date1, date2):
    """
    计算两个日期之间的天数
    
    Args:
        date1: 日期1
        date2: 日期2
        
    Returns:
        int: 天数差
    """
    try:
        if isinstance(date1, str):
            date1 = datetime.strptime(date1, '%Y-%m-%d')
        if isinstance(date2, str):
            date2 = datetime.strptime(date2, '%Y-%m-%d')
        
        return abs((date2 - date1).days)
    except:
        return 0


def safe_div(numerator, denominator, default=0):
    """
    安全除法，避免除以零
    
    Args:
        numerator: 分子
        denominator: 分母
        default: 默认值
        
    Returns:
        float: 除法结果
    """
    try:
        if denominator == 0 or pd.isna(denominator):
            return default
        return numerator / denominator
    except:
        return default


def clean_dataframe(df):
    """
    清理DataFrame数据
    
    Args:
        df: 原始DataFrame
        
    Returns:
        DataFrame: 清理后的DataFrame
    """
    if df.empty:
        return df
    
    # 删除包含NaN的行
    df = df.dropna()
    
    # 重置索引
    df = df.reset_index(drop=True)
    
    return df


def get_color_for_change(change_pct):
    """
    根据涨跌幅返回颜色
    
    Args:
        change_pct: 涨跌幅百分比
        
    Returns:
        str: 颜色代码
    """
    if change_pct > 0:
        return 'red'  # 上涨红色
    elif change_pct < 0:
        return 'green'  # 下跌绿色
    else:
        return 'gray'  # 平盘灰色


def get_stock_board(code):
    """
    获取股票所属板块
    
    Args:
        code: 股票代码
        
    Returns:
        str: 板块名称
    """
    if code.startswith('00'):
        return '深市主板'
    elif code.startswith('30'):
        return '创业板'
    elif code.startswith('60'):
        return '沪市主板'
    elif code.startswith('68'):
        return '科创板'
    else:
        return '未知板块'


if __name__ == "__main__":
    # 测试代码
    print("=== 测试辅助函数 ===")
    
    # 格式化数字
    print(f"10000 -> {format_number(10000)}")
    print(f"100000000 -> {format_number(100000000)}")
    
    # 验证股票代码
    print(f"验证 '000001': {validate_stock_code('000001')}")
    print(f"验证 '12345': {validate_stock_code('12345')}")
    
    # 获取股票名称
    print(f"000001 -> {get_stock_name('000001')}")
    
    # 格式日期
    print(f"格式日期: {format_date('20231201', format='%Y-%m-%d')}")

