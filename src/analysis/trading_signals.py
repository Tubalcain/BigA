"""
交易信号分析模块
专业的买卖决策分析
"""

import pandas as pd
import numpy as np
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')


class TradingSignalAnalyzer:
    """交易信号分析器"""
    
    def __init__(self, df):
        """
        初始化交易信号分析器
        
        Args:
            df: K线数据，必须包含 open, close, high, low, volume, date
        """
        self.df = df.copy()
        self.signals = []
        self._validate_data()
    
    def _validate_data(self):
        """验证数据格式"""
        required_cols = ['open', 'close', 'high', 'low', 'volume']
        for col in required_cols:
            if col not in self.df.columns:
                raise ValueError(f"缺少必要的列: {col}")
    
    def analyze_technical_signals(self):
        """
        分析技术面信号
        返回: list of dict
        """
        signals = []
        
        # 计算技术指标
        df = self.df.copy()
        
        # MA指标
        for ma in [5, 10, 20, 60]:
            df[f'MA{ma}'] = df['close'].rolling(ma).mean()
        
        # MACD
        ema12 = df['close'].ewm(span=12, adjust=False).mean()
        ema26 = df['close'].ewm(span=26, adjust=False).mean()
        df['DIF'] = ema12 - ema26
        df['DEA'] = df['DIF'].ewm(span=9, adjust=False).mean()
        df['MACD'] = 2 * (df['DIF'] - df['DEA'])
        
        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        
        # 最近的价格
        current = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else current
        
        # 信号1: MA金叉/死叉
        if current['MA5'] > current['MA10'] > current['MA20']:
            if prev['MA5'] <= prev['MA10'] or prev['MA10'] <= prev['MA20']:
                signals.append({
                    'type': 'buy',
                    'signal': 'MA金叉',
                    'strength': 3,
                    'description': '均线多头排列，短期强势突破',
                    'indicator': 'MA',
                    'timestamp': current.get('date', datetime.now())
                })
        
        if current['MA5'] < current['MA10'] < current['MA20']:
            if prev['MA5'] >= prev['MA10'] or prev['MA10'] >= prev['MA20']:
                signals.append({
                    'type': 'sell',
                    'signal': 'MA死叉',
                    'strength': 3,
                    'description': '均线空头排列，趋势转弱',
                    'indicator': 'MA',
                    'timestamp': current.get('date', datetime.now())
                })
        
        # 信号2: MACD金叉/死叉
        if current['DIF'] > current['DEA'] and prev['DIF'] <= prev['DEA']:
            signals.append({
                'type': 'buy',
                'signal': 'MACD金叉',
                'strength': 4,
                'description': 'MACD金叉，动能增强',
                'indicator': 'MACD',
                'timestamp': current.get('date', datetime.now())
            })
        
        if current['DIF'] < current['DEA'] and prev['DIF'] >= prev['DEA']:
            signals.append({
                'type': 'sell',
                'signal': 'MACD死叉',
                'strength': 4,
                'description': 'MACD死叉，动能减弱',
                'indicator': 'MACD',
                'timestamp': current.get('date', datetime.now())
            })
        
        # 信号3: RSI超买超卖
        if current['RSI'] < 30:
            signals.append({
                'type': 'buy',
                'signal': 'RSI超卖',
                'strength': 5,
                'description': 'RSI低于30，严重超卖，反弹概率大',
                'indicator': 'RSI',
                'timestamp': current.get('date', datetime.now())
            })
        
        if current['RSI'] > 70:
            signals.append({
                'type': 'sell',
                'signal': 'RSI超买',
                'strength': 5,
                'description': 'RSI高于70，严重超买，回调概率大',
                'indicator': 'RSI',
                'timestamp': current.get('date', datetime.now())
            })
        
        # 信号4: 价格突破MA60
        if current['close'] > current['MA60'] and prev['close'] <= prev['MA60']:
            signals.append({
                'type': 'buy',
                'signal': '突破MA60',
                'strength': 4,
                'description': '价格突破60日均线，中长期转强',
                'indicator': 'MA',
                'timestamp': current.get('date', datetime.now())
            })
        
        if current['close'] < current['MA60'] and prev['close'] >= prev['MA60']:
            signals.append({
                'type': 'sell',
                'signal': '跌破MA60',
                'strength': 4,
                'description': '价格跌破60日均线，中长期转弱',
                'indicator': 'MA',
                'timestamp': current.get('date', datetime.now())
            })
        
        # 信号5: 成交量放大
        if 'volume' in current and 'volume' in prev:
            vol_ratio = current['volume'] / prev['volume'] if prev['volume'] > 0 else 1
            if vol_ratio > 2.0 and current['close'] > current['open']:
                signals.append({
                    'type': 'buy',
                    'signal': '放量上涨',
                    'strength': 3,
                    'description': f'成交量放大{vol_ratio:.1f}倍，资金积极买入',
                    'indicator': 'Volume',
                    'timestamp': current.get('date', datetime.now())
                })
            
            if vol_ratio > 2.0 and current['close'] < current['open']:
                signals.append({
                    'type': 'sell',
                    'signal': '放量下跌',
                    'strength': 3,
                    'description': f'成交量放大{vol_ratio:.1f}倍，资金恐慌抛售',
                    'indicator': 'Volume',
                    'timestamp': current.get('date', datetime.now())
                })
        
        return signals
    
    def analyze_trend(self):
        """分析趋势"""
        df = self.df.copy()
        
        # 计算趋势
        df['trend_short'] = df['close'].rolling(20).mean().iloc[-1]
        df['trend_long'] = df['close'].rolling(60).mean().iloc[-1] if len(df) >= 60 else df['close'].mean()
        
        current_price = df['close'].iloc[-1]
        ma20 = df['close'].rolling(20).mean().iloc[-1]
        ma60 = df['close'].rolling(60).mean().iloc[-1] if len(df) >= 60 else df['close'].mean()
        
        # 判断趋势
        if current_price > ma20 > ma60:
            return {
                'direction': '上涨',
                'strength': '强势',
                'suggestion': '可考虑买入或持有',
                'risk': '中等'
            }
        elif current_price > ma20 and ma20 < ma60:
            return {
                'direction': '震荡',
                'strength': '中性',
                'suggestion': '观望或少量参与',
                'risk': '较高'
            }
        elif current_price < ma20 > ma60:
            return {
                'direction': '回调',
                'strength': '弱势',
                'suggestion': '谨慎持有或减仓',
                'risk': '高'
            }
        else:
            return {
                'direction': '下跌',
                'strength': '强势下跌',
                'suggestion': '考虑卖出',
                'risk': '很高'
            }
    
    def calculate_support_resistance(self):
        """计算支撑位和阻力位"""
        df = self.df.copy()
        
        lookback = min(20, len(df))
        recent = df.tail(lookback)
        
        resistance = recent['high'].max()
        support = recent['low'].min()
        current = df['close'].iloc[-1]
        
        return {
            'support': support,
            'resistance': resistance,
            'current': current,
            'distance_to_support': ((current - support) / support * 100) if support > 0 else 0,
            'distance_to_resistance': ((resistance - current) / current * 100) if current > 0 else 0
        }
    
    def get_trading_recommendation(self):
        """综合交易建议"""
        # 分析技术信号
        signals = self.analyze_technical_signals()
        
        # 分析趋势
        trend = self.analyze_trend()
        
        # 计算支撑阻力
        levels = self.calculate_support_resistance()
        
        # 统计买卖信号
        buy_signals = [s for s in signals if s['type'] == 'buy']
        sell_signals = [s for s in signals if s['type'] == 'sell']
        
        buy_score = sum(s['strength'] for s in buy_signals)
        sell_score = sum(s['strength'] for s in sell_signals)
        
        # 综合判断
        score = buy_score - sell_score
        
        if score >= 8:
            recommendation = '强烈买入'
            action = 'BUY'
            confidence = '高'
        elif score >= 4:
            recommendation = '买入'
            action = 'BUY'
            confidence = '中等'
        elif score >= 0:
            recommendation = '持有'
            action = 'HOLD'
            confidence = '中等'
        elif score >= -4:
            recommendation = '减仓'
            action = 'SELL'
            confidence = '中等'
        else:
            recommendation = '卖出'
            action = 'SELL'
            confidence = '高'
        
        return {
            'recommendation': recommendation,
            'action': action,
            'confidence': confidence,
            'score': score,
            'buy_signals': buy_signals,
            'sell_signals': sell_signals,
            'trend': trend,
            'support_resistance': levels,
            'signals': signals
        }
    
    def get_risk_assessment(self):
        """风险评估"""
        df = self.df.copy()
        
        # 计算波动率
        returns = df['close'].pct_change().dropna()
        volatility = returns.std() * np.sqrt(252)  # 年化波动率
        
        # 计算最大回撤
        cumulative = (1 + returns).cumprod()
        running_max = cumulative.expanding().max()
        drawdown = (cumulative - running_max) / running_max
        max_drawdown = drawdown.min() * 100
        
        # 风险等级
        if volatility < 0.15:
            risk_level = '低'
        elif volatility < 0.30:
            risk_level = '中'
        else:
            risk_level = '高'
        
        return {
            'volatility': volatility,
            'max_drawdown': max_drawdown,
            'risk_level': risk_level,
            'recommended_position_size': '小仓位' if risk_level == '高' else '正常仓位'
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
    
    analyzer = TradingSignalAnalyzer(df)
    recommendation = analyzer.get_trading_recommendation()
    risk = analyzer.get_risk_assessment()
    
    print("交易建议:")
    print(f"推荐动作: {recommendation['recommendation']}")
    print(f"信心: {recommendation['confidence']}")
    print(f"综合评分: {recommendation['score']}")
    print(f"\n风险等级: {risk['risk_level']}")
    print(f"波动率: {risk['volatility']:.2%}")

