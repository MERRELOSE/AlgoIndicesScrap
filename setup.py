"""
Setup script for AlgoIndicesScrap
"""

from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

with open("requirements.txt", "r", encoding="utf-8") as fh:
    requirements = [line.strip() for line in fh if line.strip() and not line.startswith("#")]

setup(
    name="algoindicessrap",
    version="0.1.0",
    author="Your Name",
    author_email="your.email@example.com",
    description="Reverse engineering and prediction of Deriv synthetic indices algorithms",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/AlgoIndicesScrap",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Intended Audience :: Financial and Insurance Industry",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "Topic :: Office/Business :: Financial :: Investment",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
    python_requires=">=3.10",
    install_requires=requirements,
    extras_require={
        "dev": [
            "pytest>=7.3.0",
            "pytest-cov>=4.1.0",
            "black>=23.3.0",
            "flake8>=6.0.0",
            "mypy>=1.3.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "extract-mt5=src.extractors.mt5_extractor:main",
            "analyze-stats=src.analyzers.statistical_analyzer:main",
            "detect-patterns=src.analyzers.pattern_detector:main",
            "train-lstm=src.models.lstm_predictor:main",
            "run-backtest=src.backtesting.backtest_engine:main",
        ],
    },
)
