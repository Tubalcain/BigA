# 依赖安装问题解决方案

## 常见错误及解决方案

### 错误1：No module named 'akshare'
**错误信息**：
```
No module named 'akshare'
```

### 错误2：pandas-ta 安装失败
**错误信息**：
```
ERROR: Could not find a version that satisfies the requirement pandas-ta>=0.3.14b0
```
**解决方案**：已从requirements.txt中移除，应用使用自实现的技术指标。

## 快速解决

### 方法1：最小安装（推荐，最快）
```bash
install_minimal.bat
```
只安装必需的5个包，快速且稳定。

### 方法2：完整安装
```bash
install_deps.bat
```

### 方法3：使用run.bat（自动安装）
```bash
run.bat
```
现在 `run.bat` 会自动检查并安装缺少的依赖。

### 方法4：手动安装核心依赖
打开命令行，执行：

```bash
# 进入项目目录
cd d:\work\workspace\demo\bigA

# 激活虚拟环境
venv\Scripts\activate

# 安装核心依赖
pip install akshare
pip install streamlit
pip install plotly
pip install pandas numpy
```

### 方法4：使用国内镜像（如果安装慢）
```bash
venv\Scripts\pip.exe install -i https://pypi.tuna.tsinghua.edu.cn/simple akshare streamlit plotly pandas numpy
```

## 验证安装

运行以下命令检查依赖是否正确安装：

```bash
venv\Scripts\python.exe -c "import akshare; print('AKShare installed')"
venv\Scripts\python.exe -c "import streamlit; print('Streamlit installed')"
venv\Scripts\python.exe -c "import plotly; print('Plotly installed')"
```

如果都显示成功信息，说明安装正确。

## 完整依赖列表

核心依赖：
- ✅ **akshare** - 股票数据源（必须）
- ✅ **streamlit** - Web框架（必须）
- ✅ **plotly** - 图表可视化（必须）
- ✅ **pandas** - 数据处理（必须）
- ✅ **numpy** - 数值计算（必须）

可选依赖：
- tushare - 专业级数据源
- streamlit-aggrid - 数据表格
- matplotlib - 图表
- seaborn - 统计可视化

## 如果仍然失败

### 1. 完全重新安装
```bash
# 删除虚拟环境
rmdir /s /q venv

# 运行重建脚本
rebuild_venv.bat
```

### 2. 检查Python版本
```bash
python --version
```
需要 Python 3.8 或更高版本。

### 3. 检查网络连接
确保可以访问：
- https://pypi.org/
- 或使用国内镜像

### 4. 逐个安装依赖
如果批量安装失败，可以逐个安装：

```bash
venv\Scripts\pip.exe install akshare
venv\Scripts\pip.exe install streamlit
venv\Scripts\pip.exe install plotly
venv\Scripts\pip.exe install pandas
venv\Scripts\pip.exe install numpy
```

## 常见问题

### Q: 安装AKShare时超时
A: 使用清华镜像：
```bash
venv\Scripts\pip.exe install -i https://pypi.tuna.tsinghua.edu.cn/simple akshare
```

### Q: 提示权限错误
A: 以管理员身份运行命令行

### Q: 提示pip不是最新版本
A: 先升级pip：
```bash
venv\Scripts\python.exe -m pip install --upgrade pip
```

## 技术支持

如果以上方法都无法解决问题，请检查：
1. Python版本是否正确
2. 虚拟环境是否正确激活
3. 网络连接是否正常
4. 是否需要管理员权限

