# 故障排查指南

## 常见问题及解决方案

### 问题1：虚拟环境激活失败
**错误信息**：
```
'venv\Scripts\activate.bat' is not recognized as an internal or external command
ERROR: Failed to activate virtual environment!
```

**原因**：虚拟环境创建不完整或损坏

**解决方案**：
1. **自动重建**（推荐）
   ```bash
   rebuild_venv.bat
   ```
   这将自动删除旧环境并重建完整的新环境

2. **手动重建**
   ```bash
   rmdir /s /q venv
   run.bat
   ```

### 问题2：控制台乱码
**错误信息**：显示类似 `姝ｅ湪鍒涘缓铏氭嫙鐜...` 的乱码

**原因**：Windows控制台编码问题

**解决方案**：
已修复！现在的 `run.bat` 已经包含编码修复：
```batch
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
```

如果仍有问题，检查环境变量：
```batch
chcp 65001
set PYTHONIOENCODING=utf-8
```

### 问题3：Python未找到
**错误信息**：
```
ERROR: Python not found!
Please install Python 3.8 or later.
```

**解决方案**：
1. 检查Python是否安装：
   ```bash
   python --version
   ```

2. 如果没有安装，请：
   - 访问 https://www.python.org/downloads/
   - 下载并安装Python 3.8或更高版本
   - 安装时勾选"Add Python to PATH"

### 问题4：依赖安装失败
**错误信息**：
```
ERROR: Failed to install dependencies
```

**解决方案**：
1. 检查网络连接
2. 尝试使用国内镜像：
   ```bash
   pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
   ```

3. 或者逐个安装依赖：
   ```bash
   venv\Scripts\python.exe -m pip install streamlit
   venv\Scripts\python.exe -m pip install akshare
   venv\Scripts\python.exe -m pip install plotly
   ```

### 问题5：Streamlit启动失败
**错误信息**：
```
ModuleNotFoundError: No module named 'streamlit'
```

**解决方案**：
```bash
venv\Scripts\python.exe -m pip install streamlit
```

然后重新运行：
```bash
run.bat
```

### 问题6：端口被占用
**错误信息**：
```
Address already in use
```

**解决方案**：
1. 找到占用8501端口的进程并关闭
2. 或修改端口（编辑 `app.py` 或通过命令行）：
   ```bash
   streamlit run app.py --server.port 8502
   ```

### 问题7：数据获取失败 / `ModuleNotFoundError: src.data`
**错误信息**：
```
Failed to fetch data from AKShare
ModuleNotFoundError: No module named 'src.data'
```

**解决方案**：
1. 确认仓库包含 `src/data/akshare_data.py` 与 `src/data/tushare_data.py`（从项目根目录运行）
2. 检查网络，确认能访问东财/新浪或 TuShare
3. 设置 `TUSHARE_TOKEN` 后，AKShare 不可用或指数/概况为空时会一跳回退到 TuShare（反之亦然）
4. 运行 `python examples/test_data_source.py` 看是哪一层失败
5. 热门代码：000001, 000002, 600519, 600000
6. 代码必须是 6 位，`1` / `0001` 不会再被补成 `000001`

### 问题8：缺少必要的列（open, close等）
**错误信息**：
```
缺少必要的列: open
```

**原因**：AKShare返回的列名可能是中文，需要映射

**解决方案**：
`src/data/quality.py` 会把常见中英列名映射为英文，并做类型转换：
- `开盘` → `open`
- `收盘` → `close`
- `最高` → `high`
- `最低` → `low`
- `成交量` → `volume`

若仍缺列，展开「调试信息」查看原始列名，或升级 AKShare：`pip install -U akshare`。

### 问题9：AKShare API兼容性问题
**错误信息**：
```
stock_zh_a_hist 失败: '前复权'
```

**解决方案**：
1. 更新AKShare到最新版本：
   ```bash
   venv\Scripts\pip.exe install --upgrade akshare
   ```
2. 代码已自动适配，尝试多种API调用方式
3. 如果仍失败，使用推荐股票代码：000001, 000002, 600519
4. 适配器会依次尝试 `adjust=""` / 不传 adjust / 不传日期，再回退 TuShare

### 问题10：某些股票无法获取数据
**错误信息**：
```
未能获取股票 XXX 的数据
```

**可能原因**：
1. 股票已退市
2. 代码错误（必须是 6 位，`000001.SZ` 可以，`1` 不行）
3. 数据源暂时不可用（未安装 akshare / 未配置 TUSHARE_TOKEN）
4. 开始日期晚于结束日期（会先交换再请求上游，页面提示 `date_range_swapped`）
5. 所选数据源不可用（页面会提示已切换到另一源）

**解决方案**：
1. 使用推荐的热门股票代码测试
2. 检查股票代码是否为6位数字
3. 查看应用中的空态说明 /「调试信息」（`issues` / `error`）
4. 投资组合若没有有效报价，会提示「暂用成本价」，盈亏此时不可靠

### 问题11：TuShare 提示未配置
**原因**：YAML 里 token 为空，且没有 `TUSHARE_TOKEN`。

**解决方案**：
```bash
export TUSHARE_TOKEN=your_token_here   # Windows: set TUSHARE_TOKEN=...
python examples/test_data_source.py
```
不要把真实 token 写进 `config/config.yaml` 后提交。

### 问题12：东方财富提示「IP 被临时限流」
全市场快照 `stock_zh_a_spot_em` 分页多，短时间重复请求会被封 5–40 分钟。适配器**不会对限流再重试**，并回退到新浪 `stock_zh_a_spot`。等待恢复期间不要循环点「开始筛选」。

### 问题13：周末或停牌看不到实时价
适配器会用最近一根 K 线收盘价兜底；`status=halted` 表示停牌。交易日历见 `get_trade_calendar()`。

### 问题14：资金流向是空表 / 只有部分板块
东财个股与板块资金接口和全市场快照一样容易限流。适配器会：
1. 写 `df.attrs['issues']`（页面 caption 能看到）
2. 在 `fallback: true` 时试另一源
3. **不会**把沪深股通当日一行当成行业排名

金额统一为 **万元**。TuShare 的行业/大盘资金（`moneyflow_ind_dc` / `moneyflow_mkt_dc`）常需较高积分，没权限时回退 AKShare。TuShare 行业/个股排名只有日频：选 5 日等周期时会空表或回退 AKShare，并把实际周期写进 `actual_period`，不会盖「5日」假章。概念/地域互相重叠，页面不会把板块加总冒充全市场。北向优先用 `moneyflow_hsgt`（TuShare）或东财沪深港通历史（AKShare）。不要对空表循环刷新。

验证：

```bash
python -m unittest tests.test_fund_flow
python examples/test_data_source.py
```

## 快速诊断命令

### 检查Python
```bash
python --version
```

### 检查虚拟环境
```bash
dir venv\Scripts
```

应该看到：
- activate.bat
- python.exe
- pip.exe
- streamlit.exe（安装后）

### 测试虚拟环境
```bash
venv\Scripts\python.exe -m pip list
```

### 重新安装所有依赖
```bash
venv\Scripts\pip.exe install --force-reinstall -r requirements.txt
```

## 完全重置方案

如果所有方法都失败，完全重置：

```bash
# 1. 删除虚拟环境
rmdir /s /q venv

# 2. 删除缓存
rmdir /s /q __pycache__
rmdir /s /q .streamlit 2>nul

# 3. 重建环境
python -m venv venv
venv\Scripts\python.exe -m pip install --upgrade pip
venv\Scripts\pip.exe install -r requirements.txt

# 4. 运行应用
venv\Scripts\streamlit.exe run app.py
```

## 获取帮助

如果以上方法都不能解决问题：
1. 检查Python版本：`python --version`（需要>=3.8）
2. 查看完整错误信息
3. 提交Issue时包含：
   - Python版本
   - 操作系统版本
   - 完整错误信息
   - 已经尝试的解决方案

