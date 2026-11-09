# 大A股数据分析应用 (BigA Stock Analysis)

一个面向 A 股的 Streamlit 数据分析工具，默认使用 **AKShare** 采集行情，可选接入 **TuShare Pro**。内置技术指标、筛选、组合跟踪和交易决策看板。

> OpenBB **没有接入**。文档和代码里不再把它写成当前分析引擎；若以后需要，可以作为可选扩展。

## 功能特点

- 📊 **双数据源**：AKShare（免费默认）+ TuShare（token 可选），主源失败可回退
- 📈 **技术分析**：K 线、MA / MACD / RSI / BOLL / KDJ
- 🎨 **交互可视化**：Plotly 图表
- 💼 **投资组合**：持仓、盈亏、分布
- 🔍 **筛选与市场**：实时快照筛选、指数、涨跌分布、板块/个股/北向资金流向（接口可用时）

## 数据层

`src/data/` 是页面真正依赖的采集层（历史上 README 写了这个目录，但仓库里一直缺失，现已补齐）。

| 能力 | 方法 | 说明 |
| --- | --- | --- |
| 历史 OHLCV | `get_history_data` | 日/周/月线；统一 `date,open,high,low,close,volume` |
| 实时/快照 | `get_realtime_quote` / `get_stock_list` | 报价至少含 `price`；列表尽量带市值/涨跌幅/成交量 |
| 市场概况 | `get_market_overview` / `get_index_quotes` | `type,count` 涨跌分布 + 主要指数 |
| 扩展 | `get_industry_boards` / `get_trade_calendar` / `get_halted_stocks` | 页面用到的才接，没有的接口会空表降级 |
| 资金流向 | `get_sector_fund_flow` / `get_stock_fund_flow_rank` / `get_stock_fund_flow` / `get_market_fund_flow` / `get_northbound_flow` | 行业·概念·地域排名、个股排名与日序列、市场主力、北向/南向。`get_fund_flow` 仍指向行业排名。金额统一 **万元** |
| 基本面 | `get_basic_info` / TuShare `get_daily_basic` | PE/PB/换手等，取决于源权限 |

质量约定：

- 适配器工厂是 `get_data_source("akshare"|"tushare")`：**不会**在无 token 时悄悄换源。页面用 `get_active_client()`，当前源不可用时会换到另一源（akshare ↔ tushare）。历史 / 列表 / 指数 / 概况在 `fallback: true` 时也会一跳回退。
- 股票代码必须是 6 位（`000001.SZ` 可以），不会把 `1` 补成平安银行；非法代码和不可用源会返回空表，并在 `df.attrs['issues']` / `error` 写明原因。
- 中英列名映射到同一套英文 schema；报价丢掉未知列和空/非法代码。
- 日期为 **Asia/Shanghai 日历日**（naive midnight）；`2024-1-2` / `2024/01/02` 会收成 `YYYYMMDD`；起止颠倒会**先交换再请求上游**，并标记 `date_range_swapped`。
- 去重、丢弃缺 OHLC 的 bar、把 high/low 钳到包含 open/close，标记 `is_outlier`；页面会提示异常 K 线数量。
- 空态可用 `describe_data_problems(df)` 收成一行给 UI；源切换用 `source_switch_note`。Web/CLI 共享 `data/cache` 持久缓存（按源/参数/上海时段分段），并发请求合并；成功 TTL 有上限且盘中走短 TTL，失败短冷却，**不会同日永久缓存**。过期缓存若被拿来垫底会标 `stale_cache` / 来源 / 抓取时间，不得冒充新鲜数据。超时立刻返回且**不再叠加重试**（避免后台分页继续打接口）；断连才有界退避+抖动，总时间受 `retry_budget` 约束。真正的 HTTP 429 才按限流处理并尊重 `Retry-After`；取不到 HTTP 状态码记 `unknown`。AKShare `Push2RateLimitError` 是上游启发式包装，**不是**已证实的 429。
- 资金流：东财排名按元、HSGT 历史按万、TuShare HSGT 按百万换算为万元；`auto` 只作兜底并做量级校验。周期/板块回退会写入 `actual_period` / `actual_sector` 和 `period_fallback:5日→今日` 这类 issues，UI 展示实际值。TuShare 行业/个股排名只有日频，多日请求会空表，不会盖请求周期的假章。概念/地域互相重叠，合计不当作全市场。分析在 `src/analysis/fund_flow.py`（排名、主力 vs 散户、趋势、价资背离、`market_fund_bias` / `stock_fund_bias` 短周期倾向）。倾向是 1–5 日方向，不是涨跌预测。个股分析页与交易决策页共用个股级输入（个股资金、价资、市场主力、北向）。坏腿只剔除该腿；不合格个股表不算价资背离。`apply_fund_flow_bias` 只记软参考分，**不改**技术面买卖动作。
- 市场级 `quality_ok`：需要至少一条可用的**关键主数据**（大盘主力，或非重叠行业榜）。有效主腿中性仍是中性、不是数据不足。缺主数据且只剩北向零净额/mixed 时为 **insufficient**（`quality_ok=false`、`confidence=0`、`score_delta=0`），UI 与 Saima 导出一致。各腿展示 Asia/Shanghai 真实数据日期；日频盘中/周末用上一交易日合理，**不要把 `as_of_date` 当成今日行情**。
- TuShare 备用限制：`moneyflow_ind_dc` / `moneyflow_mkt_dc` 与 AKShare 东财 push2 **同一上游**，不再当作独立备用（避免双倍打东财）。北向 `moneyflow_hsgt` 在配置了 `TUSHARE_TOKEN` 且账号有权限时才是独立源；无 token 时如实等待配置，不阻塞其它修复。积分/权限不足不会假装有数据，也不会发明第三源或承诺上游恢复。OpenBB 未接入。

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

其它可选变量：`BIGA_DATA_PRIMARY=akshare|tushare`、`BIGA_DATA_FALLBACK=true`、`BIGA_AKSHARE_ADJUST=qfq`、`BIGA_CACHE_ENABLED=true`、`BIGA_CACHE_PERSIST=true`、`BIGA_CACHE_DIR=data/cache`。

### 缓存清理

共享缓存目录默认 `data/cache`（已 gitignore）。清缓存：

```bash
rm -rf data/cache
# 或
python -c "from src.data import reset_cache; reset_cache()"
```

盘中资金流默认约 30s 过期；失败约 45s 冷却。不要靠循环刷新硬打上游。本仓库**不**内置 routine/cron。

### 3. 运行应用

```bash
streamlit run app.py
```

打开 http://localhost:8501

### 4. 验证数据源

离线（模式/缓存/配置/稳定性，不打外部 API）：

```bash
python -m unittest tests.test_data_quality tests.test_fund_flow tests.test_saima_export tests.test_market_stability
```

在线冒烟请**少量、有界**（需要能访问 AKShare；TuShare 无 token 会跳过，不要对空表压测）：

```bash
python examples/test_data_source.py
```

### 5. 导出 Saima 资金流快照

把市场级 `market_fund_bias`（大盘主力 / 北向 / 行业板块榜）写成 JSON，供外部治理仓落盘到 `/workspace/Saima/inbox/biga/YYYY-MM-DD.json`。单腿超时或无 Token 会降级，三腿全挂或仅北向零信息也输出合法快照（`bias=中性`、`quality_ok=false`、`score_delta=0`）。`as_of_date` 是快照请求日，行情日看 `latest_trade_date` / 各腿 `data_date`。不在目标目录执行 git。

```bash
python -m src.cli.export_saima_snapshot --date 2026-11-06 --inbox-dir /workspace/Saima/inbox/biga
python -m src.cli.export_saima_snapshot --output /tmp/2026-11-06.json
```

`--date` 默认取 Asia/Shanghai 当日。成功时 stdout 一行：

```
BigA fund_flow 2026-11-06 archived bias=偏多 quality_ok=true path=/workspace/Saima/inbox/biga/2026-11-06.json
```

离线单测：

```bash
python -m unittest tests.test_saima_export
```

## 使用指南

- **交易决策**：买卖信号、止损止盈、仓位；K 线周期（日/周/月）会传给数据层
- **股票分析**：历史行情 + 技术指标，可在 AKShare / TuShare 间切换
- **股票筛选**：按交易所、市值（万元）、涨跌幅、成交量（手）、停牌过滤
- **投资组合**：用实时 `price` 估值
- **市场分析**：指数、涨跌分布、排行、板块/个股/北向资金流向与图表（超时/断连/空 JSON 会写出诊断；无 HTTP 码则为 unknown，不把启发式包装当成 429）

指标说明见 [TRADING_INDICATORS_GUIDE.md](TRADING_INDICATORS_GUIDE.md)。故障见 [TROUBLESHOOTING.md](TROUBLESHOOTING.md)。

## 项目结构

```
bigA/
├── app.py
├── requirements.txt
├── config/config.yaml
├── .env.example
├── src/
│   ├── data/                      # 数据采集
│   │   ├── __init__.py
│   │   ├── config.py              # YAML + 环境变量
│   │   ├── quality.py             # 列名/类型/清洗
│   │   ├── calendar.py            # Asia/Shanghai 交易时段
│   │   ├── cache.py / fetch.py    # 持久缓存、并发合并、有界重试与诊断
│   │   ├── akshare_data.py
│   │   └── tushare_data.py
│   ├── analysis/                 # 技术指标 + 资金流分析 + Saima 快照
│   ├── cli/                      # python -m src.cli.export_saima_snapshot
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
├── tests/test_fund_flow.py
├── tests/test_market_stability.py
├── tests/test_saima_export.py
└── data/                          # 本地缓存目录（gitignored）
```

## 注意事项

1. **TuShare** 需要 `TUSHARE_TOKEN` 和相应积分/权限。没有 token 时不要搜仓库或日志里的密钥；北向独立备用不可用，等待本地配置。东财 DC 接口不是 AKShare 的独立备用。
2. **AKShare** 依赖东财/新浪等站点，可能超时、断连或返回非 JSON。适配器有界重试并缓存快照；**不能保证**远端恢复。启发式 `Push2RateLimitError` 不是 HTTP 429。
3. 停牌、周末、退市股票可能只有历史或空报价；实时失败时会用最近一根 K 线的收盘价兜底。
4. 本工具仅供研究，不构成投资建议。

## 许可证

MIT License
