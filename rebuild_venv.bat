@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8

echo ========================================
echo BigA Stock Analysis - Rebuild Virtual Environment
echo ========================================
echo.

echo Removing old virtual environment...
if exist "venv" (
    rmdir /s /q venv
    echo Old virtual environment removed.
)

echo.
echo Creating new virtual environment...
python -m venv venv

if errorlevel 1 (
    echo ERROR: Failed to create virtual environment!
    pause
    exit /b 1
)

echo Virtual environment created successfully.
echo.
echo Activating virtual environment...
call venv\Scripts\activate.bat

if errorlevel 1 (
    echo WARNING: activate.bat not found. Using direct python path.
) else (
    echo Virtual environment activated.
)

echo.
echo Upgrading pip...
venv\Scripts\python.exe -m pip install --upgrade pip

echo.
echo Installing dependencies...
venv\Scripts\python.exe -m pip install -r requirements.txt

if errorlevel 1 (
    echo WARNING: Some dependencies may not have been installed correctly.
)

echo.
echo ========================================
echo Virtual environment rebuilt successfully!
echo You can now run: run.bat
echo ========================================
echo.

pause

