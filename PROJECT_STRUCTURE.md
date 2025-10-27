# 项目结构说明

```
bigA/
├── app.py                          # Streamlit主应用入口
├── requirements.txt                # Python依赖包
├── README.md                       # 项目说明文档
├── QUICK_START.md                  # 快速开始指南
├── PROJECT_STRUCTURE.md            # 项目结构说明（本文件）
├── .gitignore                      # Git忽略文件
├── run.bat                         # Windows启动脚本
├── run.sh                          # Linux/Mac启动脚本
│
├── config/                         # 配置文件目录
│   └── config.yaml                 # 应用配置文件（数据源、分析参数、UI设置）
│
├── src/                            # 源代码目录
│   ├── __init__.py                 # 包初始化
│   │
│   ├── data/                       # 数据源模块
│   │   ├── __init__.py
│   │   ├── akshare_data.py         # AKShare数据源（免费开源）
│   │   └── tushare_data.py         # TuShare数据源（专业级）
│   │
│   ├── analysis/                   # 分析模块
│   │   ├── __init__.py
│   │   ├── technical.py            # 技术分析（MA, MACD, RSI等）
│   │   ├── fundamental.py          # 基本面分析
│   │   └── portfolio.py            # 投资组合分析
│   │
│   ├── visualization/              # 可视化模块
│   │   ├── __init__.py
│   │   ├── charts.py               # 图表生成器（Plotly）
│   │   └── kline.py                # K线图专用
│   │
│   └── utils/                      # 工具模块
│       ├── __init__.py
│       └── helpers.py              # 辅助函数
│
├── pages/                          # Streamlit多页面
│   ├── __init__.py
│   ├── _home.py                    # 首页（欢迎页）
│   ├── _stock_analysis.py         # 股票分析页面
│   ├── _screener.py               # 股票筛选器页面
│   ├── _portfolio.py               # 投资组合管理页面
│   └── _market.py                  # 市场分析页面
│
├── examples/                       # 示例代码
│   ├── test_data_source.py         # 测试数据源
│   └── simple_analysis.py         # 简单分析示例
│
└── data/                           # 数据缓存目录
    └── .gitkeep
```

## 核心模块说明

### 1. 数据层 (src/data/)
- **akshare_data.py**: AKShare数据源封装
  - 获取实时行情、历史K线
  - 计算技术指标
  - 获取市场概况
  - 优势：免费、数据丰富、无需注册
  
- **tushare_data.py**: TuShare数据源封装
  - 专业级股票数据
  - 财务数据、基本面数据
  - 需要token配置
  - 优势：数据质量高、API稳定

### 2. 分析层 (src/analysis/)
- **technical.py**: 技术分析
  - MA（移动平均线）
  - MACD
  - RSI（相对强弱指标）
  - BOLL（布林带）
  - KDJ
  - 交易信号识别
  
- **fundamental.py**: 基本面分析
  - 盈利能力分析
  - 财务比率计算
  - 估值评估
  - 生成分析报告
  
- **portfolio.py**: 投资组合分析
  - 持仓管理
  - 收益计算
  - 风险评估
  - 投资组合优化

### 3. 可视化层 (src/visualization/)
- **charts.py**: Plotly图表生成器
  - K线图（蜡烛图）
  - 折线图、柱状图、饼图
  - 热力图
  - 交互式图表
  
- **kline.py**: K线图专用
  - 专业K线图
  - 技术指标叠加
  - 成交量柱状图

### 4. UI层 (pages/)
- **_home.py**: 首页
  - 欢迎信息
  - 功能导航
  - 市场概况
  
- **_stock_analysis.py**: 股票分析
  - 实时行情查看
  - K线图展示
  - 技术指标分析
  - 数据导出
  
- **_screener.py**: 股票筛选
  - 多条件筛选
  - 股票列表展示
  - 结果导出
  
- **_portfolio.py**: 投资组合
  - 持仓管理
  - 收益分析
  - 持仓分布可视化
  - 报告生成
  
- **_market.py**: 市场分析
  - 市场概况
  - 涨跌统计
  - 资金流向

### 5. 配置 (config/)
- **config.yaml**: 应用配置
  - 数据源设置
  - 分析参数配置
  - UI主题设置
  - 缓存配置

### 6. 示例 (examples/)
- **test_data_source.py**: 测试数据源连接
- **simple_analysis.py**: 简单股票分析示例

## 技术架构

```
┌─────────────────────────────────────────┐
│           Streamlit UI Layer             │
│  (pages: home, analysis, screener...)   │
└─────────────────┬───────────────────────┘
                  │
┌─────────────────▼───────────────────────┐
│        Visualization Layer               │
│   (Plotly: charts, kline, etc.)         │
└─────────────────┬───────────────────────┘
                  │
┌─────────────────▼───────────────────────┐
│         Analysis Layer                   │
│  (technical, fundamental, portfolio)    │
└─────────────────┬───────────────────────┘
                  │
┌─────────────────▼───────────────────────┐
│          Data Layer                     │
│    (AKShare, TuShare APIs)              │
└─────────────────────────────────────────┘
```

## 数据流

1. **用户输入** → UI页面（Streamlit）
2. **数据获取** → 数据源（AKShare/TuShare）
3. **技术分析** → 计算技术指标
4. **可视化** → Plotly图表生成
5. **展示结果** → 用户界面

## 启动流程

1. 运行 `run.bat` (Windows) 或 `run.sh` (Linux/Mac)
2. 自动创建虚拟环境
3. 安装依赖包
4. 启动Streamlit应用
5. 浏览器打开 http://localhost:8501

## 扩展开发

### 添加新功能：
1. 在 `src/analysis/` 添加新的分析模块
2. 在 `pages/` 添加新的页面
3. 在 `src/visualization/` 添加新的图表类型

### 添加新数据源：
1. 在 `src/data/` 创建新的数据源模块
2. 实现标准接口
3. 在配置文件中启用

## 最佳实践

1. **数据源**: 优先使用AKShare（免费），必要时使用TuShare
2. **性能优化**: 使用缓存避免频繁API调用
3. **错误处理**: 所有API调用都要有异常处理
4. **用户体验**: 提供加载提示和友好的错误信息
5. **代码规范**: 遵循PEP8编码规范

