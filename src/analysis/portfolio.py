"""
投资组合分析模块
分析投资组合的收益、风险、持仓分布等
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta


class PortfolioAnalyzer:
    """投资组合分析器"""
    
    def __init__(self, positions=None):
        """
        初始化投资组合分析器
        
        Args:
            positions: 持仓列表，格式：[{'code': '000001', 'name': '平安银行', 'quantity': 1000, 'cost_price': 12.0}]
        """
        self.positions = positions or []
        self.total_value = 0
        self.total_cost = 0
    
    def add_position(self, code, name, quantity, cost_price):
        """
        添加持仓
        
        Args:
            code: 股票代码
            name: 股票名称
            quantity: 持有数量
            cost_price: 成本价
        """
        self.positions.append({
            'code': code,
            'name': name,
            'quantity': quantity,
            'cost_price': cost_price
        })
    
    def calculate_portfolio_value(self, current_prices):
        """
        计算投资组合总价值
        
        Args:
            current_prices: 当前价格字典，格式：{'000001': 12.5}
            
        Returns:
            dict: 投资组合价值信息
        """
        total_value = 0
        total_cost = 0
        holdings = []
        
        for pos in self.positions:
            code = pos['code']
            quantity = pos['quantity']
            cost_price = pos['cost_price']
            current_price = current_prices.get(code, cost_price)
            
            current_value = current_price * quantity
            cost_value = cost_price * quantity
            profit = current_value - cost_value
            profit_pct = (current_price / cost_price - 1) * 100
            
            holdings.append({
                'code': code,
                'name': pos['name'],
                'quantity': quantity,
                'cost_price': cost_price,
                'current_price': current_price,
                'cost_value': cost_value,
                'current_value': current_value,
                'profit': profit,
                'profit_pct': profit_pct,
                'weight': 0  # 待计算权重
            })
            
            total_value += current_value
            total_cost += cost_value
        
        # 计算权重
        for holding in holdings:
            holding['weight'] = (holding['current_value'] / total_value * 100) if total_value > 0 else 0
        
        self.total_value = total_value
        self.total_cost = total_cost
        
        return {
            'total_value': total_value,
            'total_cost': total_cost,
            'total_profit': total_value - total_cost,
            'total_profit_pct': ((total_value / total_cost - 1) * 100) if total_cost > 0 else 0,
            'holdings': holdings
        }
    
    def calculate_risk_metrics(self, returns):
        """
        计算风险指标
        
        Args:
            returns: 收益率序列
            
        Returns:
            dict: 风险指标
        """
        if len(returns) == 0:
            return {}
        
        # 年化收益率
        annual_return = returns.mean() * 252
        
        # 年化波动率
        annual_volatility = returns.std() * np.sqrt(252)
        
        # 夏普比率（假设无风险利率3%）
        risk_free_rate = 0.03
        sharpe_ratio = (annual_return - risk_free_rate) / annual_volatility if annual_volatility > 0 else 0
        
        # 最大回撤
        cumulative = (1 + returns).cumprod()
        running_max = cumulative.expanding().max()
        drawdown = (cumulative - running_max) / running_max
        max_drawdown = drawdown.min()
        
        # 胜率
        win_rate = (returns > 0).sum() / len(returns) * 100
        
        return {
            'annual_return': annual_return * 100,
            'annual_volatility': annual_volatility * 100,
            'sharpe_ratio': sharpe_ratio,
            'max_drawdown': max_drawdown * 100,
            'win_rate': win_rate
        }
    
    def get_holding_distribution(self):
        """
        获取持仓分布
        
        Returns:
            dict: 持仓分布统计
        """
        if not self.positions:
            return {}
        
        df = pd.DataFrame(self.positions)
        
        # 按股票统计
        holding_stats = df.groupby(['code', 'name']).agg({
            'quantity': 'sum',
            'cost_price': 'mean'
        }).reset_index()
        
        # 计算持仓价值（需要当前价格，这里用成本价代替）
        holding_stats['value'] = holding_stats['quantity'] * holding_stats['cost_price']
        total_value = holding_stats['value'].sum()
        holding_stats['weight'] = holding_stats['value'] / total_value * 100
        
        return {
            'total_stocks': len(holding_stats),
            'total_value': total_value,
            'holdings': holding_stats.to_dict('records')
        }
    
    def generate_portfolio_report(self, current_prices):
        """
        生成投资组合报告
        
        Args:
            current_prices: 当前价格字典
            
        Returns:
            str: 文本报告
        """
        portfolio_info = self.calculate_portfolio_value(current_prices)
        
        report = "# 投资组合分析报告\n\n"
        
        # 总体情况
        report += "## 总体情况\n\n"
        report += f"- 持仓股票数: {len(self.positions)}\n"
        report += f"- 组合总成本: ¥{portfolio_info['total_cost']:,.2f}\n"
        report += f"- 组合当前价值: ¥{portfolio_info['total_value']:,.2f}\n"
        report += f"- 总盈亏: ¥{portfolio_info['total_profit']:,.2f}\n"
        report += f"- 总收益率: {portfolio_info['total_profit_pct']:.2f}%\n\n"
        
        # 持仓明细
        report += "## 持仓明细\n\n"
        report += "| 代码 | 名称 | 数量 | 成本价 | 现价 | 盈亏 | 收益率 | 权重 |\n"
        report += "|------|------|------|--------|------|------|--------|------|\n"
        
        for holding in portfolio_info['holdings']:
            report += f"| {holding['code']} | {holding['name']} | {holding['quantity']} | {holding['cost_price']:.2f} | {holding['current_price']:.2f} | {holding['profit']:.2f} | {holding['profit_pct']:.2f}% | {holding['weight']:.2f}% |\n"
        
        return report
    
    def optimize_portfolio(self, expected_returns, cov_matrix, risk_aversion=3):
        """
        优化投资组合（Markowitz均值方差优化）
        
        Args:
            expected_returns: 预期收益率向量
            cov_matrix: 协方差矩阵
            risk_aversion: 风险厌恶系数
            
        Returns:
            dict: 优化结果
        """
        try:
            from scipy.optimize import minimize
            
            n = len(expected_returns)
            
            def objective(weights):
                """目标函数：最小化负效用"""
                portfolio_return = np.dot(weights, expected_returns)
                portfolio_risk = np.sqrt(np.dot(weights, np.dot(cov_matrix, weights)))
                return -(portfolio_return - risk_aversion * portfolio_risk)
            
            # 约束条件
            constraints = {'type': 'eq', 'fun': lambda w: np.sum(w) - 1}
            bounds = [(0, 1) for _ in range(n)]
            
            # 初始权重
            x0 = np.array([1/n] * n)
            
            # 优化
            result = minimize(objective, x0, method='SLSQP', bounds=bounds, constraints=constraints)
            
            return {
                'optimal_weights': result.x,
                'expected_return': np.dot(result.x, expected_returns),
                'expected_risk': np.sqrt(np.dot(result.x, np.dot(cov_matrix, result.x)))
            }
        except ImportError:
            print("需要安装scipy进行优化")
            return {}


if __name__ == "__main__":
    # 测试代码
    analyzer = PortfolioAnalyzer()
    
    # 添加持仓
    analyzer.add_position('000001', '平安银行', 1000, 12.0)
    analyzer.add_position('000002', '万科A', 500, 18.5)
    analyzer.add_position('600000', '浦发银行', 800, 9.5)
    
    # 计算投资组合价值
    current_prices = {
        '000001': 12.5,
        '000002': 19.0,
        '600000': 10.0
    }
    
    portfolio_info = analyzer.calculate_portfolio_value(current_prices)
    print("投资组合信息:")
    print(f"总价值: {portfolio_info['total_value']:.2f}")
    print(f"总收益率: {portfolio_info['total_profit_pct']:.2f}%")
    
    # 生成报告
    report = analyzer.generate_portfolio_report(current_prices)
    print("\n投资组合报告:")
    print(report)

