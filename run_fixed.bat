@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8

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
) else (
    echo Virtual environment already exists.
)

echo.

REM 激活虚拟环境
echo Activating virtual environment...
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo ERROR: Failed to activate virtual environment!
    pause
    exit /b 1
)

REM 升级pip
echo Upgrading pip...
python -m pip install --upgrade pip --quiet

REM 安装依赖
echo.
echo Installing dependencies...
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo WARNING: Some dependencies may not have been installed correctly.
)

REM 运行应用
echo.
echo ========================================
echo Starting BigA Stock Analysis...
echo The application will open at http://localhost:8501
echo Press Ctrl+C to stop the application
echo ========================================
echo.
streamlit run app.py

pause

