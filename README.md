# 大A股数据分析应用 (BigA Stock Analysis)

一个基于OpenBB框架的A股数据分析工具，集成AKShare和TuShare数据源，为终端用户、研究员和操盘手提供专业的数据分析、可视化和交易决策支持。

## 功能特点

### 核心功能
- 📊 **多数据源集成**：AKShare + TuShare
- 📈 **技术分析**：K线图、技术指标、成交量分析
- 🎨 **交互式可视化**：Plotly图表、实时数据展示
- 💼 **投资组合分析**：持仓分析、风险评估、收益统计
- 🔍 **数据挖掘**：股票筛选、市场行情、资金流向

### 目标用户
- **终端用户**：查看股票行情、技术指标、基本面数据
- **研究员**：深度分析、策略回测、数据导出
- **操盘手**：实时盯盘、技术信号、交易策略

## 技术架构

```
BigA Stock Analysis
├── Data Layer (数据层)
│   ├── AKShare API (市场数据、宏观经济)
│   └── TuShare API (行情数据、财务数据)
├── Analysis Layer (分析层)
│   ├── OpenBB Framework (分析引擎)
│   ├── Technical Analysis (技术指标)
│   └── Strategy Backtesting (策略回测)
├── UI Layer (界面层)
│   ├── Streamlit (主界面)
│   ├── Plotly (交互图表)
│   └── Aggrid (数据表格)
└── Core Features (核心功能)
    ├── Stock Screener (股票筛选器)
    ├── Portfolio Manager (投资组合管理)
    └── Market Dashboard (市场仪表盘)
```

## 快速开始

### 1. 环境准备

#### Windows用户（推荐）
```bash
# 直接运行启动脚本（已修复编码问题）
run.bat
```

#### 手动安装
```bash
# 克隆项目
git clone <project-url>
cd bigA

# 创建虚拟环境
python -m venv venv

# Windows
venv\Scripts\activate
# Linux/Mac
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

> **注意**：如有问题，请查看 `TROUBLESHOOTING.md` 获取解决方案。

### 2. 配置数据源

#### TuShare配置（推荐用于正式项目）
```bash
# 访问 https://tushare.pro/ 注册获取token
# 设置环境变量
export TUSHARE_TOKEN=your_token_here
```

编辑 `config/config.yaml` 添加你的token：
```yaml
data_sources:
  tushare:
    token: your_token_here
    enabled: true
  akshare:
    enabled: true
```

### 3. 运行应用

```bash
streamlit run app.py
```

应用将在 http://localhost:8501 启动

## 使用指南

### 主要模块

#### 1. 股票行情 (Stock Quotes)
- 实时/历史行情查询
- K线图展示
- 技术指标分析

#### 2. 股票筛选器 (Stock Screener)
- 多条件筛选
- 自定义指标
- 结果导出

#### 3. 投资组合 (Portfolio)
- 持仓管理
- 收益分析
- 风险评估

#### 4. 市场分析 (Market Analysis)
- 市场涨跌统计
- 板块轮动分析
- 资金流向追踪

#### 5. 研究报告 (Research Reports)
- 基本面分析
- 技术面分析
- 投资建议

## 项目结构

```
bigA/
├── app.py                          # Streamlit主应用
├── requirements.txt                # 依赖包
├── README.md                       # 项目文档
├── config/
│   └── config.yaml                # 配置文件
├── src/
│   ├── data/                      # 数据模块
│   │   ├── __init__.py
│   │   ├── akshare_data.py       # AKShare数据源
│   │   └── tushare_data.py       # TuShare数据源
│   ├── analysis/                  # 分析模块
│   │   ├── __init__.py
│   │   ├── technical.py          # 技术分析
│   │   ├── fundamental.py         # 基本面分析
│   │   └── portfolio.py           # 投资组合分析
│   ├── visualization/             # 可视化模块
│   │   ├── __init__.py
│   │   ├── charts.py             # 图表绘制
│   │   └── kline.py              # K线图
│   └── utils/                     # 工具模块
│       ├── __init__.py
│       └── helpers.py             # 辅助函数
├── pages/                         # 多页面
│   ├── _home.py                  # 首页
│   ├── _stock_analysis.py        # 股票分析
│   ├── _screener.py              # 股票筛选
│   ├── _portfolio.py             # 投资组合
│   └── _market.py                # 市场分析
└── data/                          # 数据缓存
    └── .gitkeep
```

## 注意事项

1. **数据源限制**
   - TuShare免费版有API调用频率限制
   - AKShare无需注册，但数据更新可能有延迟

2. **性能优化**
   - 合理使用数据缓存
   - 避免频繁API调用
   - 大数据集使用分页展示

3. **使用建议**
   - 专业用户推荐注册TuShare Pro版
   - 开发和测试使用AKShare即可

## 贡献指南

欢迎提交Issue和Pull Request！

## 许可证

MIT License

## 联系方式

如有问题或建议，请提交Issue。

