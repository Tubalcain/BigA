@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
REM BigA Stock Analysis - Windows启动脚本

echo ========================================
echo BigA Stock Analysis
echo BigA Stock Analysis Platform
echo ========================================
echo.

REM 检查Python是否安装
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found!
    echo Please install Python 3.8 or later.
    pause
    exit /b 1
)

echo Checking Python installation...
python --version
echo.

REM 检查虚拟环境
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment!
        pause
        exit /b 1
    )
    echo Virtual environment created successfully.
    goto :activate_venv
)

REM 检查虚拟环境是否完整
if not exist "venv\Scripts\activate.bat" (
    echo Virtual environment is corrupted. Recreating...
    rmdir /s /q venv
    python -m venv venv
    if errorlevel 1 (
        echo ERROR: Failed to recreate virtual environment!
        pause
        exit /b 1
    )
    echo Virtual environment recreated successfully.
    goto :activate_venv
)

echo Virtual environment already exists.

:activate_venv
echo.

REM 激活虚拟环境
echo Activating virtual environment...
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
    if errorlevel 1 (
        echo WARNING: activate.bat failed. Trying alternative activation...
        call venv\Scripts\python.exe -m pip install --upgrade pip --quiet
        goto :install_deps
    )
) else (
    echo Using venv\Scripts\python.exe directly...
)

REM 升级pip
echo Upgrading pip...
venv\Scripts\python.exe -m pip install --upgrade pip --quiet

REM 安装依赖
:install_deps
echo.
echo Installing dependencies...
echo This may take a few minutes...
venv\Scripts\python.exe -m pip install -r requirements.txt --no-cache-dir

echo.
echo Checking critical dependencies...
venv\Scripts\python.exe -c "import akshare" 2>nul
if errorlevel 1 (
    echo Installing AKShare...
    venv\Scripts\python.exe -m pip install akshare
)

venv\Scripts\python.exe -c "import streamlit" 2>nul
if errorlevel 1 (
    echo Installing Streamlit...
    venv\Scripts\python.exe -m pip install streamlit
)

venv\Scripts\python.exe -c "import plotly" 2>nul
if errorlevel 1 (
    echo Installing Plotly...
    venv\Scripts\python.exe -m pip install plotly
)

echo Dependencies check completed.

REM 运行应用
echo.
echo ========================================
echo Starting BigA Stock Analysis...
echo The application will open at http://localhost:8501
echo Press Ctrl+C to stop the application
echo ========================================
echo.

REM 使用虚拟环境中的streamlit
if exist "venv\Scripts\streamlit.exe" (
    venv\Scripts\streamlit.exe run app.py
) else (
    echo Installing Streamlit...
    venv\Scripts\python.exe -m pip install streamlit
    venv\Scripts\streamlit.exe run app.py
)

pause

