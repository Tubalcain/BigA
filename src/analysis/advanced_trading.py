"""
高级交易决策分析模块
专业股票分析师的完整工具箱
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')


class AdvancedTradingAnalyzer:
    """高级交易分析器 - 专业版"""
    
    def __init__(self, df, stock_code=None):
        """
        初始化高级交易分析器
        
        Args:
            df: K线数据
            stock_code: 股票代码
        """
        self.df = df.copy()
        self.stock_code = stock_code
        self._validate_data()
    
    def _validate_data(self):
        """验证数据格式"""
        required_cols = ['open', 'close', 'high', 'low', 'volume']
        for col in required_cols:
            if col not in self.df.columns:
                raise ValueError(f"缺少必要的列: {col}")
    
    def get_buy_sell_points(self):
        """获取买卖点标记"""
        df = self.df.copy()
        points = {'buy': [], 'sell': []}
        
        # 计算所有必要指标
        for ma in [5, 10, 20, 60]:
            df[f'MA{ma}'] = df['close'].rolling(ma).mean()
        
        # MACD
        ema12 = df['close'].ewm(span=12, adjust=False).mean()
        ema26 = df['close'].ewm(span=26, adjust=False).mean()
        df['DIF'] = ema12 - ema26
        df['DEA'] = df['DIF'].ewm(span=9, adjust=False).mean()
        
        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        
        # 标记买卖点
        for i in range(1, len(df)):
            prev = df.iloc[i-1]
            curr = df.iloc[i]
            
            # 买入信号
            buy_signals = 0
            if curr['close'] > curr['MA5'] > prev['close'] <= prev['MA5']:
                buy_signals += 1
            if curr['DIF'] > curr['DEA'] and prev['DIF'] <= prev['DEA']:
                buy_signals += 1
            if curr['RSI'] < 30:
                buy_signals += 1
            
            if buy_signals >= 2:
                points['buy'].append({
                    'date': curr.get('date', i),
                    'price': curr['close'],
                    'signal_type': '强买' if buy_signals >= 3 else '买入'
                })
            
            # 卖出信号
            sell_signals = 0
            if curr['close'] < curr['MA5'] and prev['close'] >= prev['MA5']:
                sell_signals += 1
            if curr['DIF'] < curr['DEA'] and prev['DIF'] >= prev['DEA']:
                sell_signals += 1
            if curr['RSI'] > 70:
                sell_signals += 1
            
            if sell_signals >= 2:
                points['sell'].append({
                    'date': curr.get('date', i),
                    'price': curr['close'],
                    'signal_type': '强卖' if sell_signals >= 3 else '卖出'
                })
        
        return points
    
    def calculate_stop_loss_profit(self, current_price):
        """计算止损止盈位"""
        df = self.df.copy()
        
        # 计算波动率
        returns = df['close'].pct_change().dropna()
        volatility = returns.std()
        
        # 计算支撑阻力位
        lookback = min(20, len(df))
        recent = df.tail(lookback)
        support = recent['low'].min()
        resistance = recent['high'].max()
        
        # 止损位：波动率的2倍
        stop_loss_down = current_price * (1 - 2 * volatility)
        stop_loss_up = current_price * (1 + 2 * volatility)
        
        # 止盈位1：支撑位
        take_profit_1 = resistance
        
        # 止盈位2：阻力位
        take_profit_2 = resistance * 1.05
        
        return {
            'stop_loss': {
                'long': stop_loss_down,
                'short': stop_loss_up,
                'distance_pct': abs(stop_loss_down - current_price) / current_price * 100
            },
            'take_profit': {
                'level_1': take_profit_1,
                'level_2': take_profit_2,
                'distance_pct_1': abs(take_profit_1 - current_price) / current_price * 100,
                'distance_pct_2': abs(take_profit_2 - current_price) / current_price * 100
            },
            'support': support,
            'resistance': resistance
        }
    
    def analyze_volume_profile(self):
        """分析成交量特征"""
        df = self.df.copy()
        
        recent = df.tail(20)
        avg_volume = recent['volume'].mean()
        current_volume = df['volume'].iloc[-1]
        
        # 成交量比率
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1
        
        # 判断成交量状态
        if volume_ratio > 2.0:
            status = '放量'
            description = '成交量异常放大'
        elif volume_ratio > 1.5:
            status = '温和放量'
            description = '成交量温和增加'
        elif volume_ratio < 0.5:
            status = '缩量'
            description = '成交量萎缩'
        else:
            status = '正常'
            description = '成交量正常'
        
        return {
            'volume_ratio': volume_ratio,
            'status': status,
            'description': description,
            'avg_volume': avg_volume,
            'current_volume': current_volume
        }
    
    def calculate_position_size(self, account_size, risk_percent=2):
        """
        计算建议仓位
        
        Args:
            account_size: 账户总资金
            risk_percent: 单笔交易风险百分比
        
        Returns:
            dict: 仓位建议
        """
        df = self.df.copy()
        
        # 计算波动率
        returns = df['close'].pct_change().dropna()
        volatility = returns.std()
        current_price = df['close'].iloc[-1]
        
        # 止损位
        stop_loss = current_price * (1 - 2 * volatility)
        stop_loss_pct = abs(current_price - stop_loss) / current_price
        
        # 计算仓位
        risk_amount = account_size * risk_percent / 100
        position_size = risk_amount / (current_price * stop_loss_pct) if stop_loss_pct > 0 else 0
        shares = int(position_size) if position_size >= 100 else 0
        position_value = shares * current_price
        
        # 仓位百分比
        position_pct = (position_value / account_size) * 100 if account_size > 0 else 0
        
        # 风险等级
        if volatility < 0.02:
            risk_level = '低'
        elif volatility < 0.04:
            risk_level = '中'
        else:
            risk_level = '高'
        
        return {
            'suggested_shares': shares,
            'position_value': position_value,
            'position_pct': position_pct,
            'risk_amount': risk_amount,
            'stop_loss_pct': stop_loss_pct * 100,
            'risk_level': risk_level
        }
    
    def generate_trading_plan(self, current_price, account_size=100000):
        """生成完整交易计划"""
        signals = self.get_buy_sell_points()
        stop_loss = self.calculate_stop_loss_profit(current_price)
        volume = self.analyze_volume_profile()
        position = self.calculate_position_size(account_size)
        
        # 计算趋势
        for ma in [5, 10, 20, 60]:
            self.df[f'MA{ma}'] = self.df['close'].rolling(ma).mean()
        
        current = self.df.iloc[-1]
        
        # 判断趋势
        if current['close'] > current['MA20'] > current['MA60']:
            trend = '强势上涨'
            trend_signal = 'buy'
        elif current['close'] > current['MA20'] < current['MA60']:
            trend = '震荡上行'
            trend_signal = 'caution'
        elif current['close'] < current['MA20'] > current['MA60']:
            trend = '震荡下行'
            trend_signal = 'caution'
        else:
            trend = '弱势下跌'
            trend_signal = 'sell'
        
        # 综合建议
        if len(signals['buy']) > len(signals['sell']):
            action = 'BUY'
            recommendation = '建议买入'
        elif len(signals['sell']) > len(signals['buy']):
            action = 'SELL'
            recommendation = '建议卖出'
        else:
            action = 'HOLD'
            recommendation = '建议持有'
        
        return {
            'recommendation': recommendation,
            'action': action,
            'trend': trend,
            'trend_signal': trend_signal,
            'signals': signals,
            'stop_loss': stop_loss,
            'volume': volume,
            'position': position,
            'current_price': current_price,
            'account_size': account_size
        }
    
    def calculate_momentum_score(self):
        """计算动量得分"""
        df = self.df.copy()
        
        scores = []
        
        # 计算各种指标
        for ma in [5, 10, 20, 60]:
            df[f'MA{ma}'] = df['close'].rolling(ma).mean()
        
        # MACD
        ema12 = df['close'].ewm(span=12, adjust=False).mean()
        ema26 = df['close'].ewm(span=26, adjust=False).mean()
        df['DIF'] = ema12 - ema26
        df['DEA'] = df['DIF'].ewm(span=9, adjust=False).mean()
        
        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        
        current = df.iloc[-1]
        
        score = 0
        
        # MA评分
        if current['close'] > current['MA5']:
            score += 1
        if current['MA5'] > current['MA10']:
            score += 1
        if current['MA10'] > current['MA20']:
            score += 1
        if current['MA20'] > current['MA60']:
            score += 1
        
        # MACD评分
        if current['DIF'] > 0:
            score += 1
        if current['DIF'] > current['DEA']:
            score += 1
        
        # RSI评分
        if 30 < current['RSI'] < 70:
            score += 1
        elif current['RSI'] < 30:
            score += 2
        elif current['RSI'] > 70:
            score -= 2
        
        # 价格动量
        returns_5d = (current['close'] / df['close'].iloc[-5] - 1) * 100 if len(df) >= 5 else 0
        returns_20d = (current['close'] / df['close'].iloc[-20] - 1) * 100 if len(df) >= 20 else 0
        
        if returns_5d > 0 and returns_20d > 0:
            score += 2
        elif returns_5d > 0:
            score += 1
        elif returns_5d < -5:
            score -= 2
        
        # 成交量
        vol_ratio = current['volume'] / df['volume'].tail(20).mean()
        if vol_ratio > 1.5 and current['close'] > current['open']:
            score += 2
        
        return {
            'score': score,
            'max_score': 15,
            'percentage': (score / 15) * 100 if score > 0 else 0,
            'returns_5d': returns_5d,
            'returns_20d': returns_20d
        }


if __name__ == "__main__":
    # 测试代码
    dates = pd.date_range('2024-01-01', periods=100, freq='D')
    df = pd.DataFrame({
        'date': dates,
        'open': np.random.randn(100).cumsum() + 100,
        'close': np.random.randn(100).cumsum() + 100,
        'high': np.random.randn(100).cumsum() + 102,
        'low': np.random.randn(100).cumsum() + 98,
        'volume': np.random.randint(1000000, 10000000, 100)
    })
    
    analyzer = AdvancedTradingAnalyzer(df, '000001')
    
    print("买卖点分析:")
    points = analyzer.get_buy_sell_points()
    print(f"买入点数: {len(points['buy'])}")
    print(f"卖出点数: {len(points['sell'])}")
    
    print("\n止损止盈:")
    stop_loss = analyzer.calculate_stop_loss_profit(100)
    print(stop_loss)
    
    print("\n动量得分:")
    momentum = analyzer.calculate_momentum_score()
    print(f"得分: {momentum['score']}/15 ({momentum['percentage']:.1f}%)")

