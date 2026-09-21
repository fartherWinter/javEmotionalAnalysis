param(
  [string]$Python = "python",
  [string]$Venv = (Join-Path $PSScriptRoot "..\.venv-laya")
)
$ErrorActionPreference = "Stop"
& $Python --version
if (-not (Test-Path (Join-Path $Venv "Scripts\python.exe"))) { & $Python -m venv $Venv }
$pythonPath = Join-Path $Venv "Scripts\python.exe"
& $pythonPath -m pip install --upgrade pip
& $pythonPath -m pip install -r (Join-Path $PSScriptRoot "..\runtime\laya_decision\requirements.txt")
Write-Output "Environment ready: $pythonPath"
Write-Output "Install a reviewed and pinned Laya/model package separately; chat-time downloads are disabled."
