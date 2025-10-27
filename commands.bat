@echo off
REM Quick commands for Windows users
REM Usage: commands.bat [command]

if "%1"=="" goto help
if "%1"=="help" goto help
if "%1"=="install" goto install
if "%1"=="extract" goto extract
if "%1"=="extract-symbol" goto extract-symbol
if "%1"=="analyze" goto analyze
if "%1"=="train" goto train
if "%1"=="backtest" goto backtest
if "%1"=="notebook" goto notebook
if "%1"=="clean" goto clean
goto help

:help
echo ========================================
echo AlgoIndicesScrap - Available Commands
echo ========================================
echo.
echo Usage: commands.bat [command]
echo.
echo Commands:
echo   help            - Show this help
echo   install         - Install dependencies
echo   extract         - Extract all symbols from MT5
echo   extract-symbol  - Extract specific symbol
echo   analyze         - Run statistical analysis
echo   train           - Train LSTM model
echo   backtest        - Run backtest
echo   notebook        - Start Jupyter notebook
echo   clean           - Clean temporary files
echo.
echo ========================================
goto end

:install
echo Installing dependencies...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
echo Done!
goto end

:extract
echo Extracting all symbols from MT5...
python src/extractors/mt5_extractor.py --all --days 365
goto end

:extract-symbol
set /p symbol="Enter symbol name (e.g., Volatility 10 Index): "
echo Extracting %symbol%...
python src/extractors/mt5_extractor.py --symbol "%symbol%" --timeframe M1 --days 365
goto end

:analyze
echo Running statistical analysis...
python src/analyzers/statistical_analyzer.py
goto end

:train
echo Training LSTM model...
python src/models/lstm_predictor.py
goto end

:backtest
echo Running backtest...
python src/backtesting/backtest_engine.py
goto end

:notebook
echo Starting Jupyter notebook...
jupyter notebook notebooks/
goto end

:clean
echo Cleaning temporary files...
for /d /r %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d"
del /s /q *.pyc 2>nul
del /s /q *.pyo 2>nul
del /s /q *.log 2>nul
echo Done!
goto end

:end
