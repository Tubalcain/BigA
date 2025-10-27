@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8

echo ========================================
echo Installing Dependencies for BigA Stock Analysis
echo ========================================
echo.

REM 检查虚拟环境
if not exist "venv\Scripts\python.exe" (
    echo ERROR: Virtual environment not found!
    echo Please run rebuild_venv.bat first.
    pause
    exit /b 1
)

echo Virtual environment found.
echo.

REM 升级pip
echo Upgrading pip...
venv\Scripts\python.exe -m pip install --upgrade pip --quiet

echo.
echo Installing core dependencies...
echo.

REM 核心依赖
echo [1/3] Installing core packages...
venv\Scripts\python.exe -m pip install pandas>=2.0.0 numpy>=1.24.0 requests>=2.31.0 --quiet

echo [2/3] Installing AKShare...
venv\Scripts\python.exe -m pip install akshare>=1.12.0 --quiet

echo [3/3] Installing Streamlit and Plotly...
venv\Scripts\python.exe -m pip install streamlit>=1.28.0 plotly>=5.17.0 streamlit-aggrid>=0.3.4 --quiet

REM 可选依赖
echo.
echo Installing optional packages...
venv\Scripts\python.exe -m pip install tushare pyyaml python-dateutil beautifulsoup4 lxml matplotlib seaborn --quiet 2>nul

echo.
echo Checking installation...
venv\Scripts\python.exe -c "import akshare; import streamlit; import plotly; print('All core dependencies installed successfully!')"

if errorlevel 1 (
    echo WARNING: Some dependencies may not be working correctly.
    echo.
    echo You can manually install them:
    echo venv\Scripts\pip.exe install akshare streamlit plotly
) else (
    echo.
    echo ========================================
    echo Dependencies installed successfully!
    echo You can now run: run.bat
    echo ========================================
)

echo.
pause

