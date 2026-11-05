# 大A股数据分析应用 (BigA Stock Analysis)

一个面向 A 股的 Streamlit 数据分析工具，默认使用 **AKShare** 采集行情，可选接入 **TuShare Pro**。内置技术指标、筛选、组合跟踪和交易决策看板。

> OpenBB **没有接入**。文档和代码里不再把它写成当前分析引擎；若以后需要，可以作为可选扩展。

## 功能特点

- 📊 **双数据源**：AKShare（免费默认）+ TuShare（token 可选），主源失败可回退
- 📈 **技术分析**：K 线、MA / MACD / RSI / BOLL / KDJ
- 🎨 **交互可视化**：Plotly 图表
- 💼 **投资组合**：持仓、盈亏、分布
- 🔍 **筛选与市场**：实时快照筛选、指数、涨跌分布、板块/资金流向（接口可用时）

## 数据层

`src/data/` 是页面真正依赖的采集层（历史上 README 写了这个目录，但仓库里一直缺失，现已补齐）。

| 能力 | 方法 | 说明 |
| --- | --- | --- |
| 历史 OHLCV | `get_history_data` | 日/周/月线；统一 `date,open,high,low,close,volume` |
| 实时/快照 | `get_realtime_quote` / `get_stock_list` | 报价至少含 `price`；列表尽量带市值/涨跌幅/成交量 |
| 市场概况 | `get_market_overview` / `get_index_quotes` | `type,count` 涨跌分布 + 主要指数 |
| 扩展 | `get_industry_boards` / `get_fund_flow` / `get_trade_calendar` / `get_halted_stocks` | 页面用到的才接，没有的接口会空表降级 |
| 基本面 | `get_basic_info` / TuShare `get_daily_basic` | PE/PB/换手等，取决于源权限 |

质量约定：

- 适配器工厂是 `get_data_source("akshare"|"tushare")`：**不会**在无 token 时悄悄换源。页面用 `get_active_client()`，当前源不可用时会换到另一源（akshare ↔ tushare）。历史 / 列表 / 指数 / 概况在 `fallback: true` 时也会一跳回退。
- 股票代码必须是 6 位（`000001.SZ` 可以），不会把 `1` 补成平安银行；非法代码和不可用源会返回空表，并在 `df.attrs['issues']` / `error` 写明原因。
- 中英列名映射到同一套英文 schema；报价丢掉未知列和空/非法代码。
- 日期为 **Asia/Shanghai 日历日**（naive midnight）；`2024-1-2` / `2024/01/02` 会收成 `YYYYMMDD`；起止颠倒会自动交换，并标记 `date_range_swapped`。
- 去重、丢弃缺 OHLC 的 bar、把 high/low 钳到包含 open/close，标记 `is_outlier`；页面会提示异常 K 线数量。
- 空态可用 `describe_data_problems(df)` 收成一行给 UI。TTL 缓存只保存校验通过的历史 K 线；超时立刻返回，不等后台线程。

## 快速开始

### 1. 环境准备

```bash
python -m venv venv
# Windows: venv\Scripts\activate
source venv/bin/activate
pip install -r requirements.txt
```

Windows 也可以直接运行 `run.bat`。Linux/Mac：`./run.sh`。

### 2. 配置数据源

**AKShare**（推荐起步）：无需注册，`config/config.yaml` 里默认 `enabled: true`。

**TuShare**（可选）：到 https://tushare.pro 申请 token，**不要把真实 token 写进仓库**。

```bash
# Linux/Mac
export TUSHARE_TOKEN=your_token_here
# Windows
set TUSHARE_TOKEN=your_token_here
```

也可以复制 `.env.example` 为 `.env`。环境变量优先于 YAML 里的空 `token` 字段。

其它可选变量：`BIGA_DATA_PRIMARY=akshare|tushare`、`BIGA_DATA_FALLBACK=true`、`BIGA_AKSHARE_ADJUST=qfq`。

### 3. 运行应用

```bash
streamlit run app.py
```

打开 http://localhost:8501

### 4. 验证数据源

离线（模式/缓存/配置，不打外部 API）：

```bash
python -m unittest tests.test_data_quality
```

在线冒烟（需要能访问 AKShare；TuShare 无 token 会跳过）：

```bash
python examples/test_data_source.py
```

## 使用指南

- **交易决策**：买卖信号、止损止盈、仓位；K 线周期（日/周/月）会传给数据层
- **股票分析**：历史行情 + 技术指标，可在 AKShare / TuShare 间切换
- **股票筛选**：按交易所、市值（万元）、涨跌幅、成交量（手）、停牌过滤
- **投资组合**：用实时 `price` 估值
- **市场分析**：指数、涨跌分布、排行、资金流向（源站限流时自动降级）

指标说明见 [TRADING_INDICATORS_GUIDE.md](TRADING_INDICATORS_GUIDE.md)。故障见 [TROUBLESHOOTING.md](TROUBLESHOOTING.md)。

## 项目结构

```
bigA/
├── app.py
├── requirements.txt
├── config/config.yaml
├── .env.example
├── src/
│   ├── data/                      # 数据采集（本次补齐）
│   │   ├── __init__.py
│   │   ├── config.py              # YAML + 环境变量
│   │   ├── quality.py             # 列名/类型/清洗
│   │   ├── cache.py / fetch.py    # TTL 缓存、超时重试
│   │   ├── akshare_data.py
│   │   └── tushare_data.py
│   ├── analysis/
│   ├── visualization/
│   └── utils/
├── pages/
│   ├── _home.py
│   ├── _stock_analysis.py
│   ├── _trading_decision.py
│   ├── _screener.py
│   ├── _portfolio.py
│   └── _market.py
├── examples/test_data_source.py
├── tests/test_data_quality.py
└── data/                          # 本地缓存目录（gitignored）
```

## 注意事项

1. **TuShare** 免费积分有调用频率和权限限制；没有 token 时页面会回退到 AKShare。
2. **AKShare** 依赖东财/新浪等站点，偶发限流或改字段；适配器按多种 API 回退，并缓存快照。
3. 停牌、周末、退市股票可能只有历史或空报价；实时失败时会用最近一根 K 线的收盘价兜底。
4. 本工具仅供研究，不构成投资建议。

## 许可证

MIT License
