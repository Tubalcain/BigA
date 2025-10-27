"""
图表生成模块
使用Plotly创建交互式图表
"""

import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots


class ChartGenerator:
    """图表生成器基类"""
    
    def __init__(self, theme='default'):
        self.theme = theme
        self.color_up = '#FF4444'      # 上涨红色
        self.color_down = '#00AA00'    # 下跌绿色
        self.color_volume = '#666666'  # 成交量灰色
    
    def create_layout(self, title, xaxis_title='日期', yaxis_title='价格'):
        """创建图表布局"""
        return {
            'title': title,
            'xaxis': {'title': xaxis_title},
            'yaxis': {'title': yaxis_title},
            'hovermode': 'x unified',
            'template': 'plotly_white',
            'height': 600
        }


class PlotlyChartGenerator(ChartGenerator):
    """Plotly图表生成器"""
    
    def candlestick_chart(self, df, title='K线图', indicators=None):
        """
        创建K线图（蜡烛图）
        
        Args:
            df: K线数据
            title: 图表标题
            indicators: 要显示的技术指标列表
            
        Returns:
            figure: Plotly图表对象
        """
        # 创建副图
        fig = make_subplots(
            rows=3, cols=1,
            shared_xaxes=True,
            row_heights=[0.6, 0.2, 0.2],
            vertical_spacing=0.05,
            subplot_titles=(title, '成交量', '技术指标'),
            specs=[[{"secondary_y": False}],
                   [{"secondary_y": False}],
                   [{"secondary_y": False}]]
        )
        
        # 绘制K线图
        fig.add_trace(
            go.Candlestick(
                x=df['date'],
                open=df['open'],
                high=df['high'],
                low=df['low'],
                close=df['close'],
                name='K线'
            ),
            row=1, col=1
        )
        
        # 添加移动平均线
        if indicators and 'MA' in indicators:
            for ma in [5, 10, 20, 60]:
                if f'MA{ma}' in df.columns:
                    fig.add_trace(
                        go.Scatter(
                            x=df['date'],
                            y=df[f'MA{ma}'],
                            mode='lines',
                            name=f'MA{ma}',
                            line=dict(width=1.5)
                        ),
                        row=1, col=1
                    )
        
        # 绘制成交量
        colors = [self.color_down if close >= prev else self.color_up
                 for close, prev in zip(df['close'], df['close'].shift(1))]
        colors[0] = self.color_down
        
        fig.add_trace(
            go.Bar(
                x=df['date'],
                y=df['volume'],
                name='成交量',
                marker_color=colors
            ),
            row=2, col=1
        )
        
        # 添加MACD
        if indicators and 'MACD' in indicators and 'DIF' in df.columns:
            fig.add_trace(
                go.Scatter(x=df['date'], y=df['DIF'], mode='lines', name='DIF', line=dict(color='blue')),
                row=3, col=1
            )
            fig.add_trace(
                go.Scatter(x=df['date'], y=df['DEA'], mode='lines', name='DEA', line=dict(color='orange')),
                row=3, col=1
            )
            fig.add_trace(
                go.Bar(x=df['date'], y=df['MACD'], name='MACD', marker_color='gray'),
                row=3, col=1
            )
        
        # 添加RSI
        if indicators and 'RSI' in indicators and 'RSI' in df.columns:
            # 替换第3行，改为RSI图
            fig.add_trace(
                go.Scatter(x=df['date'], y=df['RSI'], mode='lines', name='RSI', line=dict(color='purple')),
                row=3, col=1
            )
            # 添加超买超卖线
            fig.add_hline(y=70, line_dash="dash", line_color="red", opacity=0.5, row=3, col=1)
            fig.add_hline(y=30, line_dash="dash", line_color="green", opacity=0.5, row=3, col=1)
        
        # 更新布局
        fig.update_layout(
            title=title,
            xaxis_rangeslider_visible=False,
            height=800,
            hovermode='x unified',
            template='plotly_white'
        )
        
        return fig
    
    def line_chart(self, df, x_col, y_cols, title='折线图'):
        """
        创建折线图
        
        Args:
            df: 数据
            x_col: X轴列名
            y_cols: Y轴列名列表
            title: 图表标题
            
        Returns:
            figure: Plotly图表对象
        """
        fig = go.Figure()
        
        for col in y_cols:
            if col in df.columns:
                fig.add_trace(go.Scatter(
                    x=df[x_col],
                    y=df[col],
                    mode='lines',
                    name=col,
                    line=dict(width=2)
                ))
        
        fig.update_layout(
            title=title,
            xaxis_title=x_col,
            yaxis_title='值',
            hovermode='x unified',
            height=500,
            template='plotly_white'
        )
        
        return fig
    
    def bar_chart(self, df, x_col, y_col, title='柱状图', orientation='v'):
        """
        创建柱状图
        
        Args:
            df: 数据
            x_col: X轴列名
            y_col: Y轴列名
            title: 图表标题
            orientation: 方向 'v'垂直 | 'h'水平
            
        Returns:
            figure: Plotly图表对象
        """
        fig = go.Figure()
        
        if orientation == 'v':
            fig.add_trace(go.Bar(x=df[x_col], y=df[y_col], name=y_col))
        else:
            fig.add_trace(go.Bar(x=df[y_col], y=df[x_col], orientation='h', name=y_col))
        
        fig.update_layout(
            title=title,
            height=500,
            template='plotly_white'
        )
        
        return fig
    
    def pie_chart(self, labels, values, title='饼图'):
        """
        创建饼图
        
        Args:
            labels: 标签列表
            values: 值列表
            title: 图表标题
            
        Returns:
            figure: Plotly图表对象
        """
        fig = go.Figure(data=[go.Pie(labels=labels, values=values)])
        
        fig.update_layout(
            title=title,
            height=500,
            template='plotly_white'
        )
        
        return fig
    
    def heatmap(self, data, title='热力图', xlabel='X轴', ylabel='Y轴'):
        """
        创建热力图
        
        Args:
            data: 二维数组或DataFrame
            title: 图表标题
            xlabel: X轴标签
            ylabel: Y轴标签
            
        Returns:
            figure: Plotly图表对象
        """
        if isinstance(data, pd.DataFrame):
            fig = go.Figure(data=go.Heatmap(
                z=data.values,
                x=data.columns,
                y=data.index,
                colorscale='RdYlGn'
            ))
        else:
            fig = go.Figure(data=go.Heatmap(z=data))
        
        fig.update_layout(
            title=title,
            xaxis_title=xlabel,
            yaxis_title=ylabel,
            height=600,
            template='plotly_white'
        )
        
        return fig


def create_comparison_chart(data_dict, title='对比图'):
    """
    创建对比图表
    
    Args:
        data_dict: 数据字典，格式 {label: [values]}
        title: 图表标题
        
    Returns:
        figure: Plotly图表对象
    """
    fig = go.Figure()
    
    for label, values in data_dict.items():
        fig.add_trace(go.Scatter(
            y=values,
            mode='lines+markers',
            name=label,
            line=dict(width=2)
        ))
    
    fig.update_layout(
        title=title,
        xaxis_title='时间',
        yaxis_title='值',
        hovermode='x unified',
        height=500,
        template='plotly_white'
    )
    
    return fig


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
    for ma in [5, 10, 20]:
        df[f'MA{ma}'] = df['close'].rolling(ma).mean()
    
    # 创建图表
    generator = PlotlyChartGenerator()
    
    # 创建K线图
    fig = generator.candlestick_chart(df, title='测试K线图', indicators=['MA', 'MACD'])
    # fig.show()
    
    print("图表生成成功！")

