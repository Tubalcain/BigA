# AKShare API兼容性问题修复

## 问题描述

在使用AKShare获取股票历史数据时遇到以下错误：
```
stock_zh_a_hist 失败: '前复权'
stock_zh_a_hist_min_em 失败: 'NoneType' object is not subscriptable
```

## 原因分析

1. **版本兼容性问题**：不同版本的AKShare API参数格式不同
2. **API变化**：某些版本的AKShare可能不支持`adjust="前复权"`这样的参数
3. **参数格式**：需要根据AKShare版本调整参数格式

## 已实施的修复

### 1. 改进数据获取逻辑
在 `src/data/akshare_data.py` 中：
- 添加了多层回退方案
- 使用最稳定的API调用方式
- 自动适配不同版本的AKShare

### 2. 创建简化版本
新建了 `src/data/akshare_data_simple.py`：
- 使用最简单、最兼容的方法
- 不依赖复权参数
- 包含完整的错误处理

### 3. 多方案回退
现在的获取逻辑：
1. 方法1: `stock_zh_a_hist(symbol, period="daily", start_date, end_date, adjust="")`
2. 方法2: `stock_zh_a_hist(symbol, period="daily", start_date, end_date)` (无adjust参数)
3. 方法3: `stock_zh_a_hist(symbol, period="daily")` (无日期限制)
4. 方法4: 使用简化版本 `get_stock_history_simple()`

## 推荐的AKShare版本

**推荐版本**：`akshare>=1.12.0`

```bash
# 检查当前版本
pip show akshare

# 更新到最新版本
pip install --upgrade akshare

# 或者安装推荐版本
pip install akshare==1.12.0
```

## 测试数据获取

### 方法1：运行测试脚本
```bash
python test_stock.py
```

### 方法2：直接测试简化版本
```bash
python -c "from src.data.akshare_data_simple import get_stock_history_simple; df = get_stock_history_simple('000001'); print(df)"
```

## 使用建议

### 对于热门股票（推荐）
使用以下代码进行测试：
- **000001** - 平安银行
- **000002** - 万科A  
- **600519** - 贵州茅台
- **600000** - 浦发银行

这些股票流动性好，数据稳定，API支持完善。

### 对于特殊股票
如果遇到特定股票无法获取数据：
1. 检查股票是否退市
2. 尝试不同的数据源（AKShare/TuShare）
3. 运行测试脚本查看详细错误信息
4. 参考 `STOCK_DATA_GUIDE.md`

## 更新代码

如果遇到API兼容性问题，可以：

### 方案1：更新AKShare
```bash
venv\Scripts\pip.exe install --upgrade akshare
```

### 方案2：使用特定版本
```bash
venv\Scripts\pip.exe install akshare==1.12.0
```

### 方案3：降级到稳定版本
```bash
venv\Scripts\pip.exe install akshare==1.11.0
```

## 验证修复

运行以下命令检查AKShare版本和数据获取：
```python
import akshare as ak
print(f"AKShare版本: {ak.__version__}")

# 测试热门股票
df = ak.stock_zh_a_hist(symbol='000001', period='daily', 
                        start_date='20240101', end_date='20241201', adjust='')
print(f"数据行数: {len(df)}")
```

## 技术细节

### 调整参数的变化
- **旧版本**: `adjust="前复权"` 或 `adjust="后复权"`
- **新版本**: `adjust=""` 或直接不传adjust参数
- **最稳定**: 使用`adjust=""`或完全不指定adjust参数

### 日期格式
- 输入格式：`'YYYY-MM-DD'` 或 `'YYYYMMDD'`
- 代码会自动转换
- API需要：`YYYYMMDD`格式

### 数据标准化
- 自动检测列名（中文/英文）
- 自动转换数据类型
- 自动排序和过滤

## 后续改进计划

1. ✅ 添加多层回退机制
2. ✅ 创建简化版本备用方法
3. ✅ 改进错误处理和日志
4. 📋 添加数据缓存机制（规划中）
5. 📋 支持更多数据源（规划中）

## 问题反馈

如果仍然遇到问题：
1. 运行 `python test_stock.py` 查看详细错误
2. 检查AKShare版本：`pip show akshare`
3. 尝试更新：`pip install --upgrade akshare`
4. 提交Issue时包含：
   - AKShare版本
   - Python版本
   - 完整错误信息

