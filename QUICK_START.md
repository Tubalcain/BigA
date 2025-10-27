# 快速开始指南

## 一键启动

### Windows用户（推荐）
双击运行 `run.bat` 或在命令行执行：
```bash
.\run.bat
```

**编码问题修复**：已修复Windows控制台中文乱码问题，现在可以正常显示中文。

如果仍遇到乱码，请参考 [ENCODING_FIX.md](ENCODING_FIX.md) 文件。

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
AKShare已默认启用，可以直接使用。

### TuShare（可选，需注册）
1. 访问 https://tushare.pro 注册账号
2. 获取Token
3. 设置环境变量：
```bash
# Windows
set TUSHARE_TOKEN=your_token_here

# Linux/Mac
export TUSHARE_TOKEN=your_token_here
```

或在 `config/config.yaml` 中配置。

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

## 测试数据源

运行测试脚本检查数据源是否正常：

```bash
python examples/test_data_source.py
```

## 常见问题

### Q: 获取数据失败？
A: 检查网络连接，确保可以访问AKShare或TuShare服务器。

### Q: TuShare token如何获取？
A: 访问 https://tushare.pro 注册并获取token。

### Q: 如何添加更多功能？
A: 参考 `examples/` 目录下的示例代码。

## 技术栈

- **UI框架**: Streamlit
- **数据源**: AKShare + TuShare  
- **可视化**: Plotly
- **分析框架**: OpenBB (参考)

## 许可证

MIT License

## 联系方式

如有问题，请提交Issue。

