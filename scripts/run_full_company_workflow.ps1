# Windows PowerShell Runner for Company Intelligence Workflow
param(
    [string]$Company = $env:COMPANY,
    [string]$Country = $env:COUNTRY,
    [string]$Depth = $env:DEPTH,
    [string]$OutputDir = $env:OUTPUT_DIR,
    [string]$MemoryDb = $env:COMPANY_MEMORY_DB
)

$ErrorActionPreference = "Stop"

if (-not $Company) { $Company = "ORCHVATE" }
if (-not $Country) { $Country = "India" }
if (-not $Depth) { $Depth = "comprehensive" }
if (-not $OutputDir) { $OutputDir = "reports/orchvate-india" }
if (-not $MemoryDb) { $MemoryDb = Join-Path $env:USERPROFILE ".cache\deepresearch\company_intelligence.sqlite3" }

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
Set-Location $RepoRoot

Write-Host "=== Zerone Prospect Intelligence Workflow ===" -ForegroundColor Cyan
Write-Host "Repository root: $RepoRoot"

# 1. Verify .env
if (-not (Test-Path ".env")) {
    Write-Error "Missing .env in repository root. Copy .env.example to .env and configure credentials first."
    exit 2
}

# 2. Check git ignore
$gitIgnored = git check-ignore -q .env 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Error ".env is not ignored by Git; refusing to continue."
    exit 2
}
Write-Host "[OK] .env exists and is git-ignored." -ForegroundColor Green

# 3. Find python in venv
$VenvPy = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPy)) {
    Write-Error "Missing virtual environment at .venv. Please run: py -3.11 -m venv .venv; .\.venv\Scripts\pip install -r requirements.txt"
    exit 2
}

# 4. Check credentials safely
Write-Host "`nChecking environment credentials..." -ForegroundColor Yellow
& $VenvPy -c @"
import os
from dotenv import load_dotenv
load_dotenv()
keys = ('AI_MODEL', 'AZURE_AI_API_KEY', 'AZURE_AI_ENDPOINT', 'AZURE_AI_DEPLOYMENT', 'COMPANIES_HOUSE_API_KEY', 'OPENROUTER_API_KEY', 'OPENAI_API_KEY', 'TAVILY_API_KEY')
for k in keys:
    val = os.getenv(k)
    status = 'SET' if val else 'MISSING'
    print(f'  {k:25}: {status}')
"@

# 5. Run test suite
Write-Host "`nRunning test suite (pytest)..." -ForegroundColor Yellow
$env:PYTHONPATH = "."
& $VenvPy -m pytest -q
if ($LASTEXITCODE -ne 0) {
    Write-Error "Tests failed. Aborting workflow."
    exit 1
}
Write-Host "[OK] All tests passed." -ForegroundColor Green

# 6. Compile check
Write-Host "`nRunning compilation checks..." -ForegroundColor Yellow
& $VenvPy -m compileall -q app src webapp tests scripts
if ($LASTEXITCODE -ne 0) {
    Write-Error "Compile check failed."
    exit 1
}
Write-Host "[OK] Compilation check passed." -ForegroundColor Green

# 7. Run research workflow
Write-Host "`nLaunching Company Research Workflow..." -ForegroundColor Cyan
Write-Host "  Company    : $Company"
Write-Host "  Country    : $Country"
Write-Host "  Depth      : $Depth"
Write-Host "  Output Dir : $OutputDir"
Write-Host "  Memory DB  : $MemoryDb"

if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
}

& $VenvPy -m app research `
    --company $Company `
    --country $Country `
    --depth $Depth `
    --output-dir $OutputDir `
    --memory-db $MemoryDb

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n[OK] Workflow complete! Artifacts created in $OutputDir" -ForegroundColor Green
} else {
    Write-Host "`nWorkflow exited with code $LASTEXITCODE" -ForegroundColor Red
}
