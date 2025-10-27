# PowerShell Setup Script for AlgoIndicesScrap
# Alternative to Makefile for Windows PowerShell users

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "AlgoIndicesScrap - Windows Setup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Create directory structure
Write-Host "Creating directory structure..." -ForegroundColor Yellow

$directories = @(
    "data\raw",
    "data\processed",
    "data\models",
    "data\.cache",
    "logs",
    "results\plots",
    "results\reports"
)

foreach ($dir in $directories) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
        Write-Host "  Created: $dir" -ForegroundColor Green
    } else {
        Write-Host "  Exists: $dir" -ForegroundColor Gray
    }
}

# Copy .env example
if (-not (Test-Path ".env")) {
    Write-Host "`nCreating .env file..." -ForegroundColor Yellow
    Copy-Item ".env.example" ".env"
    Write-Host "  Created: .env" -ForegroundColor Green
} else {
    Write-Host "`n.env file already exists" -ForegroundColor Gray
}

# Install dependencies
Write-Host "`nInstalling Python dependencies..." -ForegroundColor Yellow
Write-Host "This may take a few minutes..." -ForegroundColor Gray

try {
    python -m pip install --upgrade pip --quiet
    python -m pip install -r requirements.txt --quiet
    Write-Host "  Dependencies installed successfully!" -ForegroundColor Green
} catch {
    Write-Host "  Error installing dependencies: $_" -ForegroundColor Red
    exit 1
}

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "Setup Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "`nNext steps:" -ForegroundColor Yellow
Write-Host "1. Edit .env file with your MT5 credentials" -ForegroundColor White
Write-Host "2. Run: python src/extractors/mt5_extractor.py --all" -ForegroundColor White
Write-Host "3. Run: jupyter notebook notebooks/" -ForegroundColor White
Write-Host "`nFor more commands, see QUICKSTART.md" -ForegroundColor Gray
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

Read-Host "Press Enter to continue"
