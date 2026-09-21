param(
  [string]$Python = "python",
  [string]$Venv = (Join-Path $PSScriptRoot "..\.venv-laya")
)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$env:PYTHONPATH = $root
$env:LAYA_ALLOW_NETWORK = "0"
$env:HF_HUB_OFFLINE = "1"
$pythonPath = $Python
if (Test-Path (Join-Path $Venv "Scripts\python.exe")) { $pythonPath = Join-Path $Venv "Scripts\python.exe" }
& $pythonPath -m runtime.laya_decision.laya_worker
