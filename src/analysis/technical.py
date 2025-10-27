"""
技术分析模块
计算各种技术指标：MA, MACD, RSI, BOLL, KDJ等
"""

import pandas as pd
import numpy as np


class TechnicalAnalyzer:
    """技术分析器"""
    
    def __init__(self, df):
        """
        初始化技术分析器
        
        Args:
            df: K线数据DataFrame，必须包含 open, close, high, low, volume 列
        """
        self.df = df.copy()
        self._validate_data()
    
    def _validate_data(self):
        """验证数据格式"""
        required_cols = ['open', 'close', 'high', 'low', 'volume']
        for col in required_cols:
            if col not in self.df.columns:
                raise ValueError(f"缺少必要的列: {col}")
    
    def calculate_ma(self, periods=[5, 10, 20, 60, 120]):
        """
        计算移动平均线
        
        Args:
            periods: MA周期列表
            
        Returns:
            self: 返回self以支持链式调用
        """
        for period in periods:
            self.df[f'MA{period}'] = self.df['close'].rolling(window=period).mean()
        return self
    
    def calculate_ema(self, periods=[12, 26]):
        """
        计算指数移动平均线
        
        Args:
            periods: EMA周期列表
            
        Returns:
            self
        """
        for period in periods:
            self.df[f'EMA{period}'] = self.df['close'].ewm(span=period, adjust=False).mean()
        return self
    
    def calculate_macd(self, fast=12, slow=26, signal=9):
        """
        计算MACD指标
        
        Args:
            fast: 快线周期
            slow: 慢线周期
            signal: 信号线周期
            
        Returns:
            self
        """
        # 计算EMA
        ema_fast = self.df['close'].ewm(span=fast, adjust=False).mean()
        ema_slow = self.df['close'].ewm(span=slow, adjust=False).mean()
        
        # 计算DIF和DEA
        self.df['DIF'] = ema_fast - ema_slow
        self.df['DEA'] = self.df['DIF'].ewm(span=signal, adjust=False).mean()
        
        # 计算MACD柱
        self.df['MACD'] = 2 * (self.df['DIF'] - self.df['DEA'])
        
        return self
    
    def calculate_rsi(self, period=14):
        """
        计算RSI指标（相对强弱指标）
        
        Args:
            period: RSI周期
            
        Returns:
            self
        """
        delta = self.df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        
        rs = gain / loss
        self.df['RSI'] = 100 - (100 / (1 + rs))
        
        return self
    
    def calculate_bollinger(self, period=20, num_std=2):
        """
        计算布林带指标
        
        Args:
            period: 计算周期
            num_std: 标准差倍数
            
        Returns:
            self
        """
        # 计算中轨（移动平均）
        self.df['BOLL_MID'] = self.df['close'].rolling(window=period).mean()
        
        # 计算标准差
        std = self.df['close'].rolling(window=period).std()
        
        # 计算上轨和下轨
        self.df['BOLL_UPPER'] = self.df['BOLL_MID'] + num_std * std
        self.df['BOLL_LOWER'] = self.df['BOLL_MID'] - num_std * std
        
        return self
    
    def calculate_kdj(self, n=9, m1=3, m2=3):
        """
        计算KDJ指标
        
        Args:
            n: RSV周期
            m1: K值平滑周期
            m2: D值平滑周期
            
        Returns:
            self
        """
        # 计算RSV
        low_min = self.df['low'].rolling(window=n).min()
        high_max = self.df['high'].rolling(window=n).max()
        rsv = (self.df['close'] - low_min) / (high_max - low_min) * 100
        
        # 计算K值和D值
        self.df['K'] = rsv.ewm(com=m1-1, adjust=False).mean()
        self.df['D'] = self.df['K'].ewm(com=m2-1, adjust=False).mean()
        
        # 计算J值
        self.df['J'] = 3 * self.df['K'] - 2 * self.df['D']
        
        return self
    
    def calculate_obv(self):
        """
        计算OBV指标（能量潮）
        
        Returns:
            self
        """
        obv = (np.sign(self.df['close'].diff()) * self.df['volume']).fillna(0).cumsum()
        self.df['OBV'] = obv
        return self
    
    def calculate_atr(self, period=14):
        """
        计算ATR指标（平均真实波幅）
        
        Args:
            period: ATR周期
            
        Returns:
            self
        """
        # 计算真实波幅
        high_low = self.df['high'] - self.df['low']
        high_close = abs(self.df['high'] - self.df['close'].shift(1))
        low_close = abs(self.df['low'] - self.df['close'].shift(1))
        
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        
        # 计算ATR
        self.df['ATR'] = true_range.rolling(window=period).mean()
        
        return self
    
    def calculate_all(self):
        """计算所有常用技术指标"""
        return (self
                .calculate_ma()
                .calculate_ema()
                .calculate_macd()
                .calculate_rsi()
                .calculate_bollinger()
                .calculate_kdj()
                .calculate_obv()
                .calculate_atr())
    
    def get_signals(self):
        """
        获取交易信号
        
        Returns:
            DataFrame: 包含信号的数据
        """
        self.df['signal'] = 'HOLD'
        
        # MACD金叉死叉
        self.df.loc[(self.df['DIF'] > self.df['DEA']) & 
                   (self.df['DIF'].shift(1) <= self.df['DEA'].shift(1)), 'signal'] = 'BUY_MACD'
        self.df.loc[(self.df['DIF'] < self.df['DEA']) & 
                   (self.df['DIF'].shift(1) >= self.df['DEA'].shift(1)), 'signal'] = 'SELL_MACD'
        
        # RSI超买超卖
        self.df.loc[self.df['RSI'] < 30, 'signal'] = 'BUY_RSI'
        self.df.loc[self.df['RSI'] > 70, 'signal'] = 'SELL_RSI'
        
        # KDJ金叉死叉
        self.df.loc[(self.df['K'] > self.df['D']) & 
                   (self.df['K'].shift(1) <= self.df['D'].shift(1)), 'signal'] = 'BUY_KDJ'
        self.df.loc[(self.df['K'] < self.df['D']) & 
                   (self.df['K'].shift(1) >= self.df['D'].shift(1)), 'signal'] = 'SELL_KDJ'
        
        return self
    
    def get_data(self):
        """获取计算结果"""
        return self.df


def analyze_stock(df):
    """
    便捷函数：对股票数据进行技术分析
    
    Args:
        df: K线数据
        
    Returns:
        DataFrame: 包含技术指标的数据
    """
    analyzer = TechnicalAnalyzer(df)
    return analyzer.calculate_all().get_data()


if __name__ == "__main__":
    # 测试代码
    # 创建模拟数据
    dates = pd.date_range('2023-01-01', periods=100, freq='D')
    df = pd.DataFrame({
        'date': dates,
        'open': np.random.randn(100).cumsum() + 100,
        'close': np.random.randn(100).cumsum() + 100,
        'high': np.random.randn(100).cumsum() + 102,
        'low': np.random.randn(100).cumsum() + 98,
        'volume': np.random.randint(1000000, 10000000, 100)
    })
    
    # 计算技术指标
    analyzer = TechnicalAnalyzer(df)
    result = analyzer.calculate_all().get_data()
    
    print("=== 技术分析结果 ===")
    print(result[['date', 'close', 'MA5', 'MA10', 'MA20', 'MACD', 'RSI', 'K', 'D']].tail())

