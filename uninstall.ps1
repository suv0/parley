# Removes Parley: stops it, takes its hook out of Claude Code, removes its shortcuts and its files.
# Keeps your settings file (config.toml) unless you pass -All.
param([switch]$All)

$ErrorActionPreference = 'Stop'
$data = Join-Path $env:USERPROFILE '.parley'
$venvPython = Join-Path $data 'venv\Scripts\python.exe'

if (Test-Path $venvPython) {
    & $venvPython -m parley uninstall
    Start-Sleep -Milliseconds 500
}
if (Test-Path $data) {
    Get-ChildItem -Force $data | Where-Object { $All -or $_.Name -ne 'config.toml' } | Remove-Item -Recurse -Force
    if ($All) { Remove-Item -Recurse -Force $data }
    Write-Host "Removed the Python environment, models and logs from $data."
}
if (-not $All -and (Test-Path (Join-Path $data 'config.toml'))) {
    Write-Host "Kept your settings in $data\config.toml (pass -All to remove them too)."
}
Write-Host 'Parley is uninstalled.' -ForegroundColor Green
