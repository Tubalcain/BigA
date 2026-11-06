# 快速开始指南

## 一键启动

### Windows用户（推荐）
双击运行 `run.bat` 或在命令行执行：
```bash
.\run.bat
```

**编码问题修复**：已修复Windows控制台中文乱码问题，现在可以正常显示中文。

如果仍遇到乱码，在启动前执行 `chcp 65001` 并设置 `PYTHONIOENCODING=utf-8`。

### Linux/Mac用户
运行启动脚本：
```bash
chmod +x run.sh
./run.sh
```

## 手动启动

### 1. 创建虚拟环境
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Linux/Mac
python3 -m venv venv
source venv/bin/activate
```

### 2. 安装依赖
```bash
pip install -r requirements.txt
```

**如果遇到依赖安装错误**，运行：
```bash
install_minimal.bat
```

或手动安装：
```bash
venv\Scripts\pip.exe install akshare streamlit plotly pandas numpy requests python-dateutil
```

详细问题排查见 [TROUBLESHOOTING.md](TROUBLESHOOTING.md)

### 3. 运行应用
```bash
run.bat
# 或
streamlit run app.py
```

应用将在 http://localhost:8501 启动

## 配置数据源

### AKShare（推荐，无需注册）
AKShare 已默认启用。实现位于 `src/data/akshare_data.py`。

### TuShare（可选，需注册）
1. 访问 https://tushare.pro 注册账号并取得 token  
2. **不要把真实 token 提交到 git**  
3. 用环境变量或本地 `.env`（可从 `.env.example` 复制）：

```bash
# Windows
set TUSHARE_TOKEN=your_token_here

# Linux/Mac
export TUSHARE_TOKEN=your_token_here
```

`config/config.yaml` 里的 `tushare.token` 请保持为空；环境变量优先。
主源失败时默认回退到另一源（`data_sources.fallback: true`）。

## 使用示例

### 1. 查看股票行情
1. 点击"股票分析"
2. 输入股票代码（如：000001）
3. 点击"开始分析"
4. 查看K线图和技术指标

### 2. 筛选股票
1. 点击"股票筛选"
2. 设置筛选条件
3. 点击"开始筛选"
4. 查看结果并导出

### 3. 管理投资组合
1. 点击"投资组合"
2. 添加持仓信息
3. 查看收益分析
4. 导出报告

### 4. 看资金流向
1. 打开「市场分析」→「资金流向」
2. 切换 今日 / 3日 / 5日 / 10日 与行业/概念/地域
3. 先看顶部「资金面倾向（1–5日）」：偏多/偏空/中性/分化，不是涨跌预测
4. 再看流入/流出榜、主力 vs 小单、北向趋势（金额单位：万元）
5. 「股票分析」与「交易决策」对同一只股票用同一套个股级资金面输入（个股 + 价资 + 市场主力 + 北向）；分析页不改交易评分
6. 「交易决策」拆开展示技术评分 / 资金软分 / 综合参考分；软分不改买卖动作。坏腿只剔除该腿，分化或无可用腿时软分为 0
7. 「股票筛选」可叠加排名；「该周期净流入>0」用排名接口，不逐股拉历史

## 测试数据源

运行测试脚本检查数据源是否正常：

```bash
# 离线：schema / 缓存 / 配置 / 资金流分析
python -m unittest tests.test_data_quality tests.test_fund_flow

# 在线冒烟：AKShare 必测，TuShare 无 token 则跳过
python examples/test_data_source.py
```

## 常见问题

### Q: 获取数据失败？
A: 检查网络连接，确保可以访问AKShare或TuShare服务器。页面空态会显示 `describe_data_problems`（例如代码不是 6 位、源不可用），源切换会显示 `source_switch_note`。工厂 `get_data_source` 不悄悄换源；页面用 `get_active_client`，当前源不可用会换到另一源。不要把短代码当成 000001。开始日期晚于结束日期时会先交换再请求上游；`2024-1-2` 这类日期也能解析。

### Q: TuShare token如何获取？
A: 访问 https://tushare.pro 注册并获取token。

### Q: 如何添加更多功能？
A: 参考 `examples/` 目录下的示例代码。

## 技术栈

- **UI框架**: Streamlit
- **数据源**: AKShare + TuShare  
- **可视化**: Plotly
- **分析模块**: 自研（`src/analysis`）；OpenBB 未集成

## 许可证

MIT License

## 联系方式

如有问题，请提交Issue。

