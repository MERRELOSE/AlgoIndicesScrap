@echo off
REM Setup script for Windows
REM Alternative to Makefile for Windows users

echo ========================================
echo AlgoIndicesScrap - Windows Setup
echo ========================================
echo.

REM Create directory structure
echo Creating directory structure...
if not exist "data\raw" mkdir "data\raw"
if not exist "data\processed" mkdir "data\processed"
if not exist "data\models" mkdir "data\models"
if not exist "data\.cache" mkdir "data\.cache"
if not exist "logs" mkdir "logs"
if not exist "results\plots" mkdir "results\plots"
if not exist "results\reports" mkdir "results\reports"

REM Copy .env example
if not exist ".env" (
    echo Creating .env file...
    copy .env.example .env
) else (
    echo .env file already exists
)

REM Install dependencies
echo.
echo Installing Python dependencies...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo.
echo ========================================
echo Setup Complete!
echo ========================================
echo.
echo Next steps:
echo 1. Edit .env file with your MT5 credentials
echo 2. Run: python src/extractors/mt5_extractor.py --all
echo 3. Run: jupyter notebook notebooks/
echo.
echo For more commands, see QUICKSTART.md
echo ========================================
pause
