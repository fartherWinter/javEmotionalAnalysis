param(
  [string]$Python = "python"
)
$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$root = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = $root
& $Python -m runtime.laya_decision.laya_worker --check
if ($LASTEXITCODE -ne 0) { Write-Warning "Laya model unavailable; worker can still use safe fallback." }
