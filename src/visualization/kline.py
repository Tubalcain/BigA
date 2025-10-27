"""
K线图专用模块
"""

import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def draw_kline_chart(df, title='K线图'):
    """
    绘制K线图
    
    Args:
        df: K线数据，必须包含 date, open, close, high, low, volume
        title: 图表标题
        
    Returns:
        figure: Plotly图表对象
    """
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        row_heights=[0.7, 0.3],
        vertical_spacing=0.03,
        subplot_titles=(title, '成交量'),
        specs=[[{"secondary_y": False}],
               [{"secondary_y": False}]]
    )
    
    # K线图
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
    
    # 成交量
    colors = ['red' if close >= open else 'green' 
              for close, open in zip(df['close'], df['open'])]
    
    fig.add_trace(
        go.Bar(
            x=df['date'],
            y=df['volume'],
            name='成交量',
            marker_color=colors
        ),
        row=2, col=1
    )
    
    # 更新布局
    fig.update_layout(
        title=title,
        xaxis_rangeslider_visible=False,
        height=700,
        hovermode='x unified',
        template='plotly_white'
    )
    
    return fig


def draw_candlestick_chart(df, indicators=None, title='K线图'):
    """
    绘制带技术指标的K线图
    
    Args:
        df: K线数据
        indicators: 要显示的技术指标
        title: 图表标题
        
    Returns:
        figure: Plotly图表对象
    """
    from plotly.subplots import make_subplots
    
    # 确定子图数量
    rows = 1
    if indicators:
        if 'volume' in indicators:
            rows += 1
        if 'MACD' in indicators or 'RSI' in indicators:
            rows += 1
    
    specs = [[{"secondary_y": False}] for _ in range(rows)]
    
    fig = make_subplots(
        rows=rows, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        subplot_titles=(title, '成交量', 'MACD')[:rows],
        specs=specs
    )
    
    # K线
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
    
    # 移动平均线
    if indicators and 'MA5' in df.columns:
        fig.add_trace(
            go.Scatter(x=df['date'], y=df['MA5'], mode='lines', name='MA5', line=dict(color='orange')),
            row=1, col=1
        )
    
    if indicators and 'MA10' in df.columns:
        fig.add_trace(
            go.Scatter(x=df['date'], y=df['MA10'], mode='lines', name='MA10', line=dict(color='purple')),
            row=1, col=1
        )
    
    if indicators and 'MA20' in df.columns:
        fig.add_trace(
            go.Scatter(x=df['date'], y=df['MA20'], mode='lines', name='MA20', line=dict(color='blue')),
            row=1, col=1
        )
    
    # 成交量
    if indicators and 'volume' in indicators and 'volume' in df.columns:
        row_idx = 2
        colors = ['red' if close >= open else 'green' 
                 for close, open in zip(df['close'], df['open'])]
        
        fig.add_trace(
            go.Bar(x=df['date'], y=df['volume'], name='成交量', marker_color=colors),
            row=row_idx, col=1
        )
    
    # MACD
    if indicators and 'MACD' in indicators and 'DIF' in df.columns:
        row_idx = rows
        fig.add_trace(
            go.Scatter(x=df['date'], y=df['DIF'], mode='lines', name='DIF', line=dict(color='blue')),
            row=row_idx, col=1
        )
        fig.add_trace(
            go.Scatter(x=df['date'], y=df['DEA'], mode='lines', name='DEA', line=dict(color='orange')),
            row=row_idx, col=1
        )
        fig.add_trace(
            go.Bar(x=df['date'], y=df['MACD'], name='MACD', marker_color='gray'),
            row=row_idx, col=1
        )
    
    # RSI
    if indicators and 'RSI' in indicators and 'RSI' in df.columns and 'MACD' not in indicators:
        row_idx = rows
        fig.add_trace(
            go.Scatter(x=df['date'], y=df['RSI'], mode='lines', name='RSI', line=dict(color='purple')),
            row=row_idx, col=1
        )
        fig.add_hline(y=70, line_dash="dash", line_color="red", opacity=0.5, row=row_idx, col=1)
        fig.add_hline(y=30, line_dash="dash", line_color="green", opacity=0.5, row=row_idx, col=1)
    
    # 更新布局
    fig.update_layout(
        title=title,
        xaxis_rangeslider_visible=False,
        height=300 * rows + 200,
        hovermode='x unified',
        template='plotly_white'
    )
    
    return fig


if __name__ == "__main__":
    # 测试代码
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
    
    # 绘制K线图
    fig = draw_candlestick_chart(df, indicators=['MA', 'volume'], title='测试K线图')
    # fig.show()
    
    print("K线图生成成功！")

