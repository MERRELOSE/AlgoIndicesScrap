.PHONY: help install install-dev clean test lint format extract analyze train backtest notebook

help:
	@echo "Available commands:"
	@echo "  make install       - Install dependencies"
	@echo "  make install-dev   - Install development dependencies"
	@echo "  make clean         - Clean temporary files"
	@echo "  make test          - Run tests"
	@echo "  make lint          - Run linting"
	@echo "  make format        - Format code"
	@echo "  make extract       - Extract data from MT5"
	@echo "  make analyze       - Run statistical analysis"
	@echo "  make train         - Train LSTM model"
	@echo "  make backtest      - Run backtest"
	@echo "  make notebook      - Start Jupyter notebook"

install:
	pip install -r requirements.txt

install-dev:
	pip install -r requirements.txt
	pip install -e ".[dev]"

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name "*.log" -delete
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -exec rm -rf {} +
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	rm -rf build/ dist/

test:
	pytest tests/ -v --cov=src --cov-report=html --cov-report=term

lint:
	flake8 src/ tests/
	mypy src/

format:
	black src/ tests/
	isort src/ tests/

# Data extraction
extract:
	python src/extractors/mt5_extractor.py --all --days 365

extract-symbol:
	@read -p "Enter symbol name: " symbol; \
	python src/extractors/mt5_extractor.py --symbol "$$symbol" --timeframe M1 --days 365

# Analysis
analyze:
	python src/analyzers/statistical_analyzer.py

analyze-patterns:
	python src/analyzers/pattern_detector.py

# Model training
train:
	python src/models/lstm_predictor.py

train-config:
	@read -p "Enter config file path: " config; \
	python src/models/lstm_predictor.py --config "$$config"

# Backtesting
backtest:
	python src/backtesting/backtest_engine.py

# Jupyter
notebook:
	jupyter notebook notebooks/

# Setup
setup:
	mkdir -p data/{raw,processed,models}
	mkdir -p logs
	mkdir -p results/{plots,reports}
	cp .env.example .env
	@echo "✅ Project structure created!"
	@echo "⚠️  Please edit .env file with your MT5 credentials"

# Quick start
quickstart: setup install
	@echo "✅ Installation complete!"
	@echo ""
	@echo "Next steps:"
	@echo "1. Edit .env file with your MT5 credentials"
	@echo "2. Run 'make extract' to get data from MT5"
	@echo "3. Run 'make notebook' to start analyzing"
