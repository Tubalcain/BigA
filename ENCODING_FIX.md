# 编码问题解决方案

## 问题描述
在Windows系统启动应用时，控制台出现乱码，如：`姝ｅ湪鍒涘缓铏氭嫙鐜...`

## 原因
Windows控制台默认使用GBK/CP936编码，而项目使用UTF-8编码的中文字符。

## 解决方案

### 方案1：使用修复后的启动脚本（推荐）
已经修复了 `run.bat` 文件，添加了：
```batch
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
```

现在直接运行：
```bash
run.bat
```

### 方案2：手动设置编码
如果还有问题，可以手动设置：

#### 在命令行中
```bash
chcp 65001
set PYTHONIOENCODING=utf-8
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

#### 在PowerShell中
```powershell
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING="utf-8"
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

### 方案3：永久设置系统编码
修改PowerShell配置文件：
```powershell
# 打开配置文件
notepad $PROFILE

# 添加以下内容
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
```

## 验证修复
运行 `run.bat` 后，应该看到正常的中文输出：
```
========================================
BigA Stock Analysis
BigA Stock Analysis Platform
========================================

Checking Python installation...
Python 3.xx.x

Virtual environment already exists.

Activating virtual environment...

Upgrading pip...

Installing dependencies...
========================================
Starting BigA Stock Analysis...
The application will open at http://localhost:8501
```

## 附加说明
- `chcp 65001` - 将控制台代码页设置为UTF-8（65001）
- `set PYTHONIOENCODING=utf-8` - 设置Python IO编码为UTF-8
- 这对Windows中文显示非常重要

## 如果问题仍然存在
1. 确认Python版本 >= 3.8
2. 检查系统区域设置
3. 使用新创建的 `run_fixed.bat` 文件

## 技术细节
- Windows默认代码页：GBK (936)
- UTF-8代码页：65001
- Python IO编码：通过环境变量 PYTHONIOENCODING 控制

