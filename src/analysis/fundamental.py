"""
基本面分析模块
分析公司财务数据、盈利能力、成长性等
"""

import pandas as pd
import numpy as np


class FundamentalAnalyzer:
    """基本面分析器"""
    
    def __init__(self, financial_data=None):
        """
        初始化基本面分析器
        
        Args:
            financial_data: 财务数据DataFrame
        """
        self.financial_data = financial_data
        self.analysis = {}
    
    def analyze_profitability(self, revenue, net_profit):
        """
        分析盈利能力
        
        Args:
            revenue: 营业收入
            net_profit: 净利润
            
        Returns:
            dict: 盈利能力指标
        """
        # 净利润率
        profit_margin = (net_profit / revenue) * 100 if revenue > 0 else 0
        
        # 平均增长率（需要多个期间数据）
        if len(revenue) > 1:
            revenue_growth = ((revenue.iloc[-1] / revenue.iloc[-2]) - 1) * 100
        else:
            revenue_growth = 0
        
        return {
            'profit_margin': profit_margin,
            'revenue_growth': revenue_growth
        }
    
    def calculate_financial_ratios(self, data):
        """
        计算财务比率
        
        Args:
            data: 财务数据DataFrame
            
        Returns:
            dict: 财务比率
        """
        ratios = {}
        
        # PE比率（需要额外数据）
        if 'pe' in data.columns:
            ratios['pe'] = data['pe'].iloc[-1] if not data['pe'].isna().iloc[-1] else None
        
        # PB比率
        if 'pb' in data.columns:
            ratios['pb'] = data['pb'].iloc[-1] if not data['pb'].isna().iloc[-1] else None
        
        # 换手率
        if 'turnover_rate' in data.columns:
            ratios['turnover_rate'] = data['turnover_rate'].iloc[-1] if not data['turnover_rate'].isna().iloc[-1] else None
        
        return ratios
    
    def evaluate_stock(self, pe_ratio, pb_ratio, industry_avg_pe=20):
        """
        评估股票价值
        
        Args:
            pe_ratio: PE比率
            pb_ratio: PB比率
            industry_avg_pe: 行业平均PE
            
        Returns:
            dict: 评估结果
        """
        evaluation = {
            'valuation': 'NORMAL',
            'reason': ''
        }
        
        # PE评估
        if pe_ratio and pe_ratio > 0:
            if pe_ratio < industry_avg_pe * 0.7:
                evaluation['valuation'] = 'UNDERVALUED'
                evaluation['reason'] = f'PE比率({pe_ratio:.2f})低于行业均值，可能存在低估'
            elif pe_ratio > industry_avg_pe * 1.5:
                evaluation['valuation'] = 'OVERVALUED'
                evaluation['reason'] = f'PE比率({pe_ratio:.2f})远高于行业均值，可能存在高估'
            else:
                evaluation['reason'] = f'PE比率({pe_ratio:.2f})在合理区间'
        
        return evaluation
    
    def get_basic_info_summary(self, stock_code, stock_name, current_price, industry):
        """
        获取基本信息摘要
        
        Args:
            stock_code: 股票代码
            stock_name: 股票名称
            current_price: 当前价格
            industry: 所属行业
            
        Returns:
            dict: 基本信息摘要
        """
        return {
            'code': stock_code,
            'name': stock_name,
            'price': current_price,
            'industry': industry if industry else '未分类',
            'exchange': '深圳' if stock_code.startswith(('00', '30')) else '上海',
            'board': self._get_board(stock_code)
        }
    
    def _get_board(self, stock_code):
        """判断所属板块"""
        if stock_code.startswith('00'):
            return '主板'
        elif stock_code.startswith('30'):
            return '创业板'
        elif stock_code.startswith('60'):
            return '主板'
        elif stock_code.startswith('68'):
            return '科创板'
        else:
            return '未知'
    
    def generate_report(self, analysis_results):
        """
        生成分析报告
        
        Args:
            analysis_results: 分析结果字典
            
        Returns:
            str: 文本报告
        """
        report = "# 基本面分析报告\n\n"
        
        # 基本信息
        if 'basic_info' in analysis_results:
            info = analysis_results['basic_info']
            report += f"## 基本信息\n\n"
            report += f"- 股票代码: {info.get('code', 'N/A')}\n"
            report += f"- 股票名称: {info.get('name', 'N/A')}\n"
            report += f"- 当前价格: {info.get('price', 'N/A')}\n"
            report += f"- 所属行业: {info.get('industry', 'N/A')}\n"
            report += f"- 所属板块: {info.get('board', 'N/A')}\n\n"
        
        # 估值分析
        if 'valuation' in analysis_results:
            valuation = analysis_results['valuation']
            report += f"## 估值分析\n\n"
            report += f"- 估值状态: {valuation.get('valuation', 'N/A')}\n"
            report += f"- 分析原因: {valuation.get('reason', 'N/A')}\n\n"
        
        # 财务比率
        if 'ratios' in analysis_results:
            ratios = analysis_results['ratios']
            report += f"## 财务比率\n\n"
            for key, value in ratios.items():
                if value is not None:
                    report += f"- {key.upper()}: {value:.2f}\n"
            report += "\n"
        
        # 投资建议
        report += "## 投资建议\n\n"
        if 'valuation' in analysis_results and analysis_results['valuation'].get('valuation') == 'UNDERVALUED':
            report += "建议: 增持\n"
            report += "理由: 当前估值偏低，具备投资价值\n"
        elif 'valuation' in analysis_results and analysis_results['valuation'].get('valuation') == 'OVERVALUED':
            report += "建议: 减持\n"
            report += "理由: 当前估值偏高，建议谨慎\n"
        else:
            report += "建议: 持有\n"
            report += "理由: 估值合理，可持续关注\n"
        
        return report


if __name__ == "__main__":
    # 测试代码
    analyzer = FundamentalAnalyzer()
    
    # 模拟数据
    financial_data = pd.DataFrame({
        'date': pd.date_range('2023-01-01', periods=4, freq='Q'),
        'pe': [15, 18, 20, 22],
        'pb': [2.5, 2.8, 3.0, 3.2],
        'turnover_rate': [2.5, 3.0, 3.5, 4.0]
    })
    
    # 计算财务比率
    ratios = analyzer.calculate_financial_ratios(financial_data)
    print("财务比率:", ratios)
    
    # 评估股票
    evaluation = analyzer.evaluate_stock(22, 3.2)
    print("评估结果:", evaluation)
    
    # 生成报告
    results = {
        'basic_info': {
            'code': '000001',
            'name': '平安银行',
            'price': 12.50,
            'industry': '银行',
            'board': '主板'
        },
        'valuation': evaluation,
        'ratios': ratios
    }
    
    report = analyzer.generate_report(results)
    print("\n基本面分析报告:")
    print(report)

