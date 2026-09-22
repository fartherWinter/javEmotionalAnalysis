param([string]$Python = "", [switch]$SkipTests)
$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$root = Split-Path -Parent $PSScriptRoot
if (-not $Python) { $Python = Join-Path $root ".venv/Scripts/python.exe" }
Push-Location $root
try {
    if (-not $SkipTests) {
        $env:QT_QPA_PLATFORM = "offscreen"
        & $Python -m pytest tests runtime/laya_decision/tests -q
        if ($LASTEXITCODE -ne 0) { throw "Tests failed" }
        Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
    }
    & $Python -m PyInstaller --noconfirm --clean --log-level WARN --onedir --windowed --name JevLocalAssistant --add-data "runtime/laya_decision;runtime/laya_decision" --add-data "docs;docs" --collect-data certifi launch_desktop.py
    if ($LASTEXITCODE -ne 0) { throw "Build failed" }
    & $Python -m scripts.collect_notices
    if ($LASTEXITCODE -ne 0) { throw "Collect notices failed" }
    Copy-Item -Path (Join-Path $root "docs/*.md") -Destination (Join-Path $root "dist/JevLocalAssistant")
    Compress-Archive -Path (Join-Path $root "dist/JevLocalAssistant") -DestinationPath (Join-Path $root "dist/JevLocalAssistant-windows.zip") -Force
    Write-Output "Built: dist/JevLocalAssistant-windows.zip"
} finally { Pop-Location }
