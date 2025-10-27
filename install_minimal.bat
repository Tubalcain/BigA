@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8

echo ========================================
echo Installing Minimal Dependencies
echo Only essential packages for BigA Stock Analysis
echo ========================================
echo.

REM 检查虚拟环境
if not exist "venv\Scripts\python.exe" (
    echo ERROR: Virtual environment not found!
    echo Please run: rebuild_venv.bat
    pause
    exit /b 1
)

echo.
echo Installing essential packages only...
echo.

REM 核心依赖 - 这是运行应用必须的
echo [1/5] Installing Pandas and NumPy...
venv\Scripts\python.exe -m pip install pandas numpy --quiet

echo [2/5] Installing AKShare...
venv\Scripts\python.exe -m pip install akshare --quiet

echo [3/5] Installing Streamlit...
venv\Scripts\python.exe -m pip install streamlit --quiet

echo [4/5] Installing Plotly...
venv\Scripts\python.exe -m pip install plotly --quiet

echo [5/5] Installing utilities...
venv\Scripts\python.exe -m pip install requests python-dateutil --quiet

echo.
echo Checking installation...
venv\Scripts\python.exe -c "import akshare; import streamlit; import plotly; import pandas; print('SUCCESS! All core packages installed.')"

if errorlevel 1 (
    echo FAILED: Some packages not installed correctly.
    echo Please check the errors above.
    pause
    exit /b 1
) else (
    echo.
    echo ========================================
    echo Installation completed successfully!
    echo You can now run: run.bat
    echo ========================================
)

echo.
pause

