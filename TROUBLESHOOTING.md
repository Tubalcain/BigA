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

### 问题7：数据获取失败
**错误信息**：
```
Failed to fetch data from AKShare
```

**解决方案**：
1. 检查网络连接
2. AKShare服务器可能暂时不可用，稍后重试
3. 可以配置TuShare作为备选数据源
4. 尝试使用推荐的股票代码：000001, 600519

### 问题8：缺少必要的列（open, close等）
**错误信息**：
```
缺少必要的列: open
```

**原因**：AKShare返回的列名可能是中文，需要映射

**解决方案**：
已自动修复！代码现在会自动将中文列名映射为英文：
- `开盘` → `open`
- `收盘` → `close`
- `最高` → `high`
- `最低` → `low`
- `成交量` → `volume`

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

### 问题10：某些股票无法获取数据
**错误信息**：
```
未能获取股票 XXX 的数据
```

**可能原因**：
1. 股票已退市
2. 代码错误
3. 数据源暂时不可用

**解决方案**：
1. 使用推荐的热门股票代码测试
2. 检查股票代码是否为6位数字
3. 查看应用中的"调试信息"了解详情

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

