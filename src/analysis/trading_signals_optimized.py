"""
优化版交易信号分析模块
资深分析师的专业优化版本
"""

import pandas as pd
import numpy as np
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')


class OptimizedTradingSignalAnalyzer:
    """优化版交易信号分析器 - 专业级"""
    
    def __init__(self, df):
        """
        初始化优化版交易信号分析器
        
        Args:
            df: K线数据
        """
        self.df = df.copy()
        self._validate_data()
        self._calculate_all_indicators()
    
    def _validate_data(self):
        """验证数据格式"""
        required_cols = ['open', 'close', 'high', 'low', 'volume']
        for col in required_cols:
            if col not in self.df.columns:
                raise ValueError(f"缺少必要的列: {col}")
    
    def _calculate_all_indicators(self):
        """预计算所有指标"""
        df = self.df.copy()
        
        # 均线
        for ma in [5, 10, 20, 60, 120]:
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
        
        # 成交量均线
        df['VOL_MA5'] = df['volume'].rolling(5).mean()
        df['VOL_MA20'] = df['volume'].rolling(20).mean()
        
        self.df = df
    
    def _get_trend_factor(self):
        """获取趋势因子"""
        df = self.df
        current = df.iloc[-1]
        
        # 判断趋势方向
        if current['close'] > current['MA20'] > current['MA60']:
            # 强势上涨趋势
            return {'buy': 1.5, 'sell': 0.7, 'trend': '强势上涨'}
        elif current['close'] < current['MA20'] < current['MA60']:
            # 强势下跌趋势
            return {'buy': 0.7, 'sell': 1.5, 'trend': '强势下跌'}
        else:
            # 震荡行情
            return {'buy': 1.0, 'sell': 1.0, 'trend': '震荡'}
    
    def _get_position_factor(self):
        """获取位置因子"""
        df = self.df
        lookback = min(120, len(df))
        recent = df.tail(lookback)
        
        max_price = recent['high'].max()
        min_price = recent['low'].min()
        current_price = df['close'].iloc[-1]
        
        if max_price - min_price > 0:
            position_pct = (current_price - min_price) / (max_price - min_price) * 100
        else:
            position_pct = 50
        
        # 高位（>80%）：卖出信号强化，买入信号弱化
        if position_pct > 80:
            return {
                'position': '高位',
                'buy': 0.6,
                'sell': 1.4,
                'pct': position_pct
            }
        # 低位（<20%）：买入信号强化，卖出信号弱化
        elif position_pct < 20:
            return {
                'position': '低位',
                'buy': 1.4,
                'sell': 0.6,
                'pct': position_pct
            }
        else:
            return {
                'position': '中位',
                'buy': 1.0,
                'sell': 1.0,
                'pct': position_pct
            }
    
    def analyze_signals_with_weights(self):
        """
        带权重的信号分析
        
        信号权重：
        - 一级信号（5分）：放量突破、成交量异常、年线突破
        - 二级信号（4分）：MACD金叉、突破MA60、RSI极值
        - 三级信号（3分）：MA金叉、成交量温和放大
        - 四级信号（2分）：突破MA20、短期超涨
        """
        df = self.df
        current = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else current
        
        signals = []
        
        # 获取调整因子
        trend_factor = self._get_trend_factor()
        position_factor = self._get_position_factor()
        
        # 成交量分析
        vol_ratio = current['volume'] / current['VOL_MA20'] if current['VOL_MA20'] > 0 else 1
        
        # === 买入信号 ===
        
        # 1. 放量突破（一级信号）
        if vol_ratio > 2.0 and current['close'] > current['high'].shift(1).iloc[0]:
            signals.append({
                'type': 'buy',
                'signal': '放量突破',
                'strength': 5,
                'description': f'成交量放大{vol_ratio:.1f}倍，成功突破前期高点',
                'weight': '一级'
            })
        
        # 2. RSI超卖（二级信号）
        if current['RSI'] < 30:
            signals.append({
                'type': 'buy',
                'signal': 'RSI超卖',
                'strength': 4,
                'description': f'RSI值{current["RSI"]:.1f}，严重超卖，反弹概率大',
                'weight': '二级'
            })
        
        # 3. MACD金叉（二级信号）
        if current['DIF'] > current['DEA'] and prev['DIF'] <= prev['DEA']:
            signals.append({
                'type': 'buy',
                'signal': 'MACD金叉',
                'strength': 4,
                'description': 'MACD金叉形成，动能增强',
                'weight': '二级'
            })
        
        # 4. 突破MA60（二级信号）
        if current['close'] > current['MA60'] and prev['close'] <= prev['MA60']:
            signals.append({
                'type': 'buy',
                'signal': '突破MA60',
                'strength': 4,
                'description': '价格突破60日均线，中期转强',
                'weight': '二级'
            })
        
        # 5. MA金叉（三级信号）
        if current['MA5'] > current['MA10'] and prev['MA5'] <= prev['MA10']:
            signals.append({
                'type': 'buy',
                'signal': 'MA金叉',
                'strength': 3,
                'description': 'MA5金叉MA10，短期转强',
                'weight': '三级'
            })
        
        # 6. 温和放量上涨（三级信号）
        if 1.2 < vol_ratio < 2.0 and current['close'] > current['open']:
            signals.append({
                'type': 'buy',
                'signal': '温和放量',
                'strength': 3,
                'description': f'成交量温和放大{vol_ratio:.1f}倍，资金流入',
                'weight': '三级'
            })
        
        # === 卖出信号 ===
        
        # 1. 放量下跌（一级信号）
        if vol_ratio > 2.0 and current['close'] < current['low'].shift(1).iloc[0]:
            signals.append({
                'type': 'sell',
                'signal': '放量下跌',
                'strength': 5,
                'description': f'成交量放大{vol_ratio:.1f}倍，资金恐慌抛售',
                'weight': '一级'
            })
        
        # 2. RSI超买（二级信号）
        if current['RSI'] > 70:
            signals.append({
                'type': 'sell',
                'signal': 'RSI超买',
                'strength': 4,
                'description': f'RSI值{current["RSI"]:.1f}，严重超买，回调概率大',
                'weight': '二级'
            })
        
        # 3. MACD死叉（二级信号）
        if current['DIF'] < current['DEA'] and prev['DIF'] >= prev['DEA']:
            signals.append({
                'type': 'sell',
                'signal': 'MACD死叉',
                'strength': 4,
                'description': 'MACD死叉形成，动能减弱',
                'weight': '二级'
            })
        
        # 4. 跌破MA60（二级信号）
        if current['close'] < current['MA60'] and prev['close'] >= prev['MA60']:
            signals.append({
                'type': 'sell',
                'signal': '跌破MA60',
                'strength': 4,
                'description': '价格跌破60日均线，中期转弱',
                'weight': '二级'
            })
        
        # 5. MA死叉（三级信号）
        if current['MA5'] < current['MA10'] and prev['MA5'] >= prev['MA10']:
            signals.append({
                'type': 'sell',
                'signal': 'MA死叉',
                'strength': 3,
                'description': 'MA5死叉MA10，短期转弱',
                'weight': '三级'
            })
        
        # 应用调整因子
        for signal in signals:
            if signal['type'] == 'buy':
                signal['adjusted_strength'] = signal['strength'] * trend_factor['buy'] * position_factor['buy']
            else:
                signal['adjusted_strength'] = signal['strength'] * trend_factor['sell'] * position_factor['sell']
        
        return {
            'signals': signals,
            'trend_info': trend_factor,
            'position_info': position_factor,
            'vol_info': {
                'ratio': vol_ratio,
                'status': '放量' if vol_ratio > 2 else ('正常' if vol_ratio > 0.8 else '缩量')
            }
        }
    
    def get_optimized_recommendation(self):
        """获取优化后的交易建议"""
        analysis = self.analyze_signals_with_weights()
        signals = analysis['signals']
        trend = analysis['trend_info']
        position = analysis['position_info']
        vol = analysis['vol_info']
        
        # 分类信号
        buy_signals = [s for s in signals if s['type'] == 'buy']
        sell_signals = [s for s in signals if s['type'] == 'sell']
        
        # 使用调整后的强度
        buy_score = sum(s.get('adjusted_strength', s['strength']) for s in buy_signals)
        sell_score = sum(s.get('adjusted_strength', s['strength']) for s in sell_signals)
        
        # 综合评分
        score = buy_score - sell_score
        
        # 专业评估
        if score >= 10:
            recommendation = '强烈买入'
            action = 'BUY'
            confidence = '高'
            reason = '多个强信号共振，趋势有利，位置合适'
        elif score >= 5:
            recommendation = '买入'
            action = 'BUY'
            confidence = '中等'
            reason = '买入信号明显，可考虑建仓'
        elif score >= 0:
            recommendation = '持有'
            action = 'HOLD'
            confidence = '中等'
            reason = '信号不明确，建议持有观望'
        elif score >= -5:
            recommendation = '减仓'
            action = 'SELL'
            confidence = '中等'
            reason = '出现卖出信号，建议减仓'
        else:
            recommendation = '卖出'
            action = 'SELL'
            confidence = '高'
            reason = '多个强卖出信号，建议及时止损'
        
        return {
            'recommendation': recommendation,
            'action': action,
            'confidence': confidence,
            'score': score,
            'buy_score': buy_score,
            'sell_score': sell_score,
            'buy_signals': buy_signals,
            'sell_signals': sell_signals,
            'reason': reason,
            'trend_info': trend,
            'position_info': position,
            'vol_info': vol,
            'analysis_notes': self._generate_analysis_notes(score, trend, position, vol)
        }
    
    def _generate_analysis_notes(self, score, trend, position, vol):
        """生成分析说明"""
        notes = []
        
        # 趋势分析
        notes.append(f"📈 当前趋势：{trend['trend']}")
        if trend['trend'] == '强势上涨':
            notes.append("✅ 建议：趋势向上，买入信号更可靠")
        elif trend['trend'] == '强势下跌':
            notes.append("⚠️ 警告：趋势向下，买入信号应谨慎")
        
        # 位置分析
        notes.append(f"📍 价格位置：{position['position']}（{position['pct']:.1f}%）")
        if position['position'] == '高位':
            notes.append("⚠️ 警告：价格处于高位，注意回调风险")
        elif position['position'] == '低位':
            notes.append("✅ 提示：价格处于低位，可能是入场良机")
        
        # 成交量分析
        notes.append(f"📊 成交量：{vol['status']}（比率{vol['ratio']:.2f}）")
        if vol['status'] == '放量':
            notes.append("✅ 提示：成交量放大，市场活跃，信号更可靠")
        elif vol['status'] == '缩量':
            notes.append("⚠️ 警告：成交量萎缩，可能是假信号")
        
        return notes
    
    def calculate_optimized_stop_loss(self):
        """计算优化后的止损位"""
        df = self.df
        
        # 计算波动率
        returns = df['close'].pct_change().dropna()
        volatility = returns.std()
        
        # 判断市场状态
        current = df.iloc[-1]
        trend_factor = self._get_trend_factor()
        
        # 根据趋势调整止损幅度
        if trend_factor['trend'] == '强势上涨':
            stop_loss_pct = abs(volatility * 3)  # 强势趋势，可以承受更大波动
        elif trend_factor['trend'] == '强势下跌':
            stop_loss_pct = abs(volatility * 2)  # 下跌趋势，需要更紧止损
        else:
            stop_loss_pct = abs(volatility * 2.5)  # 震荡行情，适中止损
        
        current_price = df['close'].iloc[-1]
        stop_loss = current_price * (1 - stop_loss_pct)
        
        # 动态支撑位
        lookback = min(20, len(df))
        recent = df.tail(lookback)
        dynamic_support = recent['low'].min()
        
        # 取两者最小值（更保守）
        final_stop_loss = min(stop_loss, dynamic_support * 0.98)
        
        return {
            'stop_loss': final_stop_loss,
            'stop_loss_pct': abs(final_stop_loss - current_price) / current_price * 100,
            'volatility': volatility,
            'trend_adjustment': trend_factor['trend']
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
    
    analyzer = OptimizedTradingSignalAnalyzer(df)
    recommendation = analyzer.get_optimized_recommendation()
    
    print("优化后的交易建议:")
    print(f"推荐: {recommendation['recommendation']}")
    print(f"信心: {recommendation['confidence']}")
    print(f"评分: {recommendation['score']:.1f}")
    print(f"原因: {recommendation['reason']}")
    print(f"\n分析说明:")
    for note in recommendation['analysis_notes']:
        print(f"  {note}")

